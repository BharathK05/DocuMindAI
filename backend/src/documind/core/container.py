"""Composition root: the one place that picks concrete implementations from config.

Built once per process (per Lambda cold start), so SDK clients and HTTP connections are reused
across requests.
"""

from dataclasses import dataclass
from typing import Any

import boto3
from botocore.config import Config
from openai import AsyncOpenAI

from documind.core.config import Backend, LLMProviderName, Settings
from documind.providers.base import EmbeddingProvider, LLMProvider
from documind.providers.fake import FakeEmbeddingProvider, FakeLLMProvider
from documind.providers.openai_provider import OpenAIChatProvider, OpenAIEmbeddingProvider
from documind.repositories.base import BlobStore, DocumentRepository, JobQueue, VectorStore
from documind.repositories.dynamodb import DynamoDocumentRepository, DynamoTable, DynamoVectorStore
from documind.repositories.memory import (
    InlineJobQueue,
    InMemoryBlobStore,
    InMemoryDocumentRepository,
    InMemoryVectorStore,
)
from documind.repositories.s3 import S3BlobStore
from documind.repositories.sqs import SqsJobQueue
from documind.services.documents import DocumentService
from documind.services.ingestion import IngestionService
from documind.services.query import QueryService

_RETRIES: Any = {"max_attempts": 5, "mode": "adaptive"}
_BOTO_CONFIG = Config(connect_timeout=5, read_timeout=10, retries=_RETRIES)
# SQS long polls hold the connection open for up to 20 s, so its read timeout must be longer.
_SQS_CONFIG = Config(connect_timeout=5, read_timeout=30, retries=_RETRIES)


@dataclass
class Container:
    settings: Settings
    documents: DocumentRepository
    vectors: VectorStore
    blobs: BlobStore
    queue: JobQueue
    embedder: EmbeddingProvider
    llm: LLMProvider
    document_service: DocumentService
    ingestion_service: IngestionService
    query_service: QueryService


def _client(service: str, settings: Settings, endpoint_url: str | None) -> Any:
    return boto3.client(  # type: ignore[call-overload]
        service,
        region_name=settings.aws_region,
        endpoint_url=endpoint_url,
        config=_SQS_CONFIG if service == "sqs" else _BOTO_CONFIG,
    )


def _openai_api_key(settings: Settings) -> str:
    if settings.openai_api_key is not None:
        return settings.openai_api_key.get_secret_value()
    if settings.openai_api_key_ssm_parameter:
        ssm = _client("ssm", settings, None)
        response = ssm.get_parameter(
            Name=settings.openai_api_key_ssm_parameter, WithDecryption=True
        )
        return str(response["Parameter"]["Value"])
    raise RuntimeError(
        "OPENAI_API_KEY is not set. Add it to backend/.env, or set "
        "DOCUMIND_LLM_PROVIDER=fake to run without a key."
    )


def _providers(settings: Settings) -> tuple[EmbeddingProvider, LLMProvider]:
    if settings.llm_provider is LLMProviderName.FAKE:
        return FakeEmbeddingProvider(), FakeLLMProvider()
    client = AsyncOpenAI(
        api_key=_openai_api_key(settings),
        timeout=settings.llm_timeout_seconds,
        max_retries=settings.llm_max_retries,
    )
    embedder = OpenAIEmbeddingProvider(
        client,
        model=settings.embedding_model,
        dimensions=settings.embedding_dimensions,
        tokenizer=settings.embedding_tokenizer,
        max_input_tokens=settings.embedding_max_input_tokens,
        batch_max_items=settings.embedding_batch_max_items,
        batch_max_tokens=settings.embedding_batch_max_tokens,
        concurrency=settings.embedding_concurrency,
    )
    llm = OpenAIChatProvider(
        client, model=settings.chat_model, reasoning_effort=settings.chat_reasoning_effort
    )
    return embedder, llm


def _storage(settings: Settings) -> tuple[DocumentRepository, VectorStore, BlobStore, JobQueue]:
    if settings.backend is Backend.MEMORY:
        return (
            InMemoryDocumentRepository(),
            InMemoryVectorStore(),
            InMemoryBlobStore(),
            InlineJobQueue(),
        )
    table = DynamoTable(
        _client("dynamodb", settings, settings.dynamodb_endpoint_url), settings.dynamodb_table
    )
    s3 = _client("s3", settings, settings.s3_endpoint_url)
    s3_presign = _client(
        "s3", settings, settings.s3_public_endpoint_url or settings.s3_endpoint_url
    )
    sqs = _client("sqs", settings, settings.sqs_endpoint_url)
    queue_url = sqs.get_queue_url(QueueName=settings.sqs_queue_name)["QueueUrl"]
    return (
        DynamoDocumentRepository(table),
        DynamoVectorStore(table),
        S3BlobStore(s3, s3_presign, settings.s3_bucket),
        SqsJobQueue(sqs, queue_url),
    )


def build_container(settings: Settings) -> Container:
    documents, vectors, blobs, queue = _storage(settings)
    embedder, llm = _providers(settings)
    ingestion = IngestionService(settings, documents, vectors, blobs, embedder)
    if isinstance(queue, InlineJobQueue):
        queue.handler = ingestion.process
    return Container(
        settings=settings,
        documents=documents,
        vectors=vectors,
        blobs=blobs,
        queue=queue,
        embedder=embedder,
        llm=llm,
        document_service=DocumentService(settings, documents, vectors, blobs, queue),
        ingestion_service=ingestion,
        query_service=QueryService(settings, documents, vectors, embedder, llm),
    )
