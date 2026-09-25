"""Centralised, typed configuration. Every tunable lives here and is read from the environment."""

from enum import StrEnum
from functools import lru_cache

from pydantic import Field, SecretStr, model_validator
from pydantic_settings import BaseSettings, SettingsConfigDict


class Backend(StrEnum):
    MEMORY = "memory"  # in-process fakes: unit tests and the Gradio demo
    AWS = "aws"  # DynamoDB + S3 + SQS (real AWS, or local emulators via *_endpoint_url)


class LLMProviderName(StrEnum):
    OPENAI = "openai"
    FAKE = "fake"  # deterministic offline provider: tests, load tests, no-key local runs


class ChunkingStrategy(StrEnum):
    RECURSIVE = "recursive"  # fixed-size character chunks (original pipeline)
    STRUCTURED = "structured"  # boilerplate removal + token chunks + section context


class RetrievalMode(StrEnum):
    DENSE = "dense"  # embeddings only
    HYBRID = "hybrid"  # embeddings + BM25 keyword search, fused with reciprocal rank fusion


class RerankerName(StrEnum):
    NONE = "none"
    LLM = "llm"  # listwise reranking by the chat model


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_prefix="DOCUMIND_", env_file=".env", env_file_encoding="utf-8", extra="ignore"
    )

    env: str = "local"
    log_level: str = "INFO"
    cors_origins: list[str] = ["http://localhost:3000"]
    # Replaced by Cognito/JWT auth in Phase 4; until then every request acts as this user.
    dev_user_id: str = "local-dev-user"

    # --- Infrastructure wiring -------------------------------------------------------------
    backend: Backend = Backend.MEMORY
    aws_region: str = "us-east-1"
    dynamodb_table: str = "documind-local"
    dynamodb_endpoint_url: str | None = None
    s3_bucket: str = "documind-uploads-local"
    s3_endpoint_url: str | None = None
    # Presigned URLs embed the host they were signed for. In docker-compose the API reaches S3
    # at http://moto:5000 but the browser needs http://localhost:5000, hence a separate value.
    s3_public_endpoint_url: str | None = None
    sqs_queue_name: str = "documind-ingest"
    sqs_endpoint_url: str | None = None
    sqs_max_receive_count: int = 3  # must match the queue's redrive policy

    # --- LLM provider --------------------------------------------------------------------------
    llm_provider: LLMProviderName = LLMProviderName.OPENAI
    # Locally read from OPENAI_API_KEY; on AWS fetched from this SSM SecureString at cold start.
    openai_api_key: SecretStr | None = Field(default=None, validation_alias="OPENAI_API_KEY")
    openai_api_key_ssm_parameter: str | None = None
    chat_model: str = "gpt-6-luna"
    chat_context_window: int = 1_050_000
    # gpt-6-luna is a reasoning model; "low" keeps latency and hidden reasoning tokens down.
    chat_reasoning_effort: str | None = "low"
    chat_max_output_tokens: int = 1_000
    chat_tokenizer: str = "o200k_base"
    embedding_model: str = "text-embedding-3-small"
    embedding_dimensions: int = 1536
    embedding_tokenizer: str = "cl100k_base"
    embedding_max_input_tokens: int = 8191
    embedding_batch_max_items: int = 256
    embedding_batch_max_tokens: int = 100_000  # API hard limit is 300k tokens per request
    embedding_concurrency: int = 4
    # USD per 1M tokens, for cost logging and quotas (standard tier, verified 2026-09-24).
    chat_input_usd_per_mtok: float = 0.10
    chat_output_usd_per_mtok: float = 0.50
    embedding_usd_per_mtok: float = 0.02
    llm_timeout_seconds: float = 30.0
    llm_max_retries: int = 3  # SDK retries 408/409/429/5xx with exponential backoff + jitter

    # --- Ingestion & retrieval -----------------------------------------------------------------
    upload_max_bytes: int = 20 * 1024 * 1024
    upload_max_pages: int = 300
    presign_expiry_seconds: int = 300
    # Each retrieval improvement is a switch so the eval harness can measure it in isolation
    # (see backend/evals). Defaults are the best configuration found there.
    chunking_strategy: ChunkingStrategy = ChunkingStrategy.STRUCTURED
    chunk_size: int = 500  # characters, "recursive" strategy
    chunk_overlap: int = 75
    chunk_tokens: int = 350  # tokens, "structured" strategy
    chunk_overlap_tokens: int = 50
    retrieval_mode: RetrievalMode = RetrievalMode.HYBRID
    retrieval_candidates: int = 30  # per-retriever pool before fusion / reranking
    # +18 pts Recall@1, +5 pts correctness for ~+1.4 s p50 and ~3x (sub-cent) cost per query.
    reranker: RerankerName = RerankerName.LLM
    rerank_candidates: int = 20
    # Ranking passages needs no deliberation; "none" keeps the extra call fast.
    rerank_reasoning_effort: str | None = "none"
    retrieval_top_k: int = 5
    context_token_budget: int = 3_000  # max tokens of retrieved text sent to the model
    prompt_version: int = 2
    max_history_messages: int = 10
    max_question_chars: int = 2_000

    @model_validator(mode="after")
    def _check(self) -> "Settings":
        if self.chunk_overlap >= self.chunk_size:
            raise ValueError("chunk_overlap must be smaller than chunk_size")
        return self


@lru_cache
def get_settings() -> Settings:
    return Settings()
