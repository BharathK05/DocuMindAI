"""Composition root: the one place that picks concrete implementations from config.

Built once per process (per Lambda cold start), so SDK clients and HTTP connections are reused
across requests.
"""

from dataclasses import dataclass
from typing import Any

import boto3
from botocore.config import Config
from openai import AsyncOpenAI

from documind.core.config import Backend, LLMProviderName, RerankerName, Settings
from documind.providers.base import EmbeddingProvider, LLMProvider
from documind.providers.fake import FakeEmbeddingProvider, FakeLLMProvider
from documind.providers.openai_provider import OpenAIChatProvider, OpenAIEmbeddingProvider
from documind.repositories.base import (
    BlobStore,
    ConversationRepository,
    DocumentRepository,
    JobQueue,
    RateLimiter,
    UsageRepository,
    VectorStore,
)
from documind.repositories.conversations import (
    DynamoConversationRepository,
    InMemoryConversationRepository,
)
from documind.repositories.dynamodb import (
    ChunkCache,
    DynamoDocumentRepository,
    DynamoTable,
    DynamoVectorStore,
)
from documind.repositories.memory import (
    InlineJobQueue,
    InMemoryBlobStore,
    InMemoryDocumentRepository,
    InMemoryVectorStore,
)
from documind.repositories.s3 import S3BlobStore
from documind.repositories.sqs import SqsJobQueue
from documind.repositories.usage import (
    DynamoRateLimiter,
    DynamoUsageRepository,
    InMemoryRateLimiter,
    InMemoryUsageRepository,
)
from documind.services.chat import ChatService
from documind.services.context import ContextManager, TokenCounter
from documind.services.conversations import ConversationService
from documind.services.documents import DocumentService
from documind.services.ingestion import IngestionService
from documind.services.query import QueryService
from documind.services.rerank import LLMReranker
from documind.services.titles import TitleGenerator
from documind.services.usage import UsageService

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
    conversation_service: ConversationService
    usage_service: UsageService
    chat_service: ChatService


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


def _providers(settings: Settings) -> tuple[EmbeddingProvider, LLMProvider, LLMProvider]:
    """(embedder, answering LLM, reranking LLM)."""
    if settings.llm_provider is LLMProviderName.FAKE:
        delay = settings.fake_latency_ms / 1000
        return (
            FakeEmbeddingProvider(settings.fake_embedding_dimensions, delay_seconds=delay),
            FakeLLMProvider(delay_seconds=delay),
            FakeLLMProvider(delay_seconds=delay),
        )
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
    rerank_llm = OpenAIChatProvider(
        client, model=settings.chat_model, reasoning_effort=settings.rerank_reasoning_effort
    )
    return embedder, llm, rerank_llm


@dataclass
class _Storage:
    documents: DocumentRepository
    vectors: VectorStore
    blobs: BlobStore
    queue: JobQueue
    conversations: ConversationRepository
    usage: UsageRepository
    limiter: RateLimiter


def _storage(settings: Settings) -> _Storage:
    if settings.backend is Backend.MEMORY:
        return _Storage(
            InMemoryDocumentRepository(),
            InMemoryVectorStore(),
            InMemoryBlobStore(),
            InlineJobQueue(),
            InMemoryConversationRepository(),
            InMemoryUsageRepository(),
            InMemoryRateLimiter(),
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
    return _Storage(
        DynamoDocumentRepository(table),
        DynamoVectorStore(table, ChunkCache(settings.vector_cache_max_chunks)),
        S3BlobStore(s3, s3_presign, settings.s3_bucket),
        SqsJobQueue(sqs, queue_url),
        DynamoConversationRepository(table),
        DynamoUsageRepository(table),
        DynamoRateLimiter(table),
    )


def build_container(settings: Settings) -> Container:
    st = _storage(settings)
    embedder, llm, rerank_llm = _providers(settings)
    ingestion = IngestionService(settings, st.documents, st.vectors, st.blobs, embedder)
    if isinstance(st.queue, InlineJobQueue):
        st.queue.handler = ingestion.process
    query = QueryService(
        settings,
        st.documents,
        st.vectors,
        embedder,
        llm,
        reranker=LLMReranker(rerank_llm) if settings.reranker is RerankerName.LLM else None,
    )
    counter = TokenCounter(settings.chat_tokenizer)
    usage = UsageService(settings, st.usage)
    conversations = ConversationService(st.conversations)
    return Container(
        settings=settings,
        documents=st.documents,
        vectors=st.vectors,
        blobs=st.blobs,
        queue=st.queue,
        embedder=embedder,
        llm=llm,
        document_service=DocumentService(
            settings, st.documents, st.vectors, st.blobs, st.queue, st.limiter
        ),
        ingestion_service=ingestion,
        query_service=query,
        conversation_service=conversations,
        usage_service=usage,
        chat_service=ChatService(
            settings,
            query,
            conversations,
            st.conversations,
            ContextManager(settings, llm, counter),
            counter,
            usage,
            st.limiter,
            TitleGenerator(rerank_llm),  # low-effort model: a title needs no reasoning
        ),
    )
