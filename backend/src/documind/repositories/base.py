"""Persistence interfaces. Every method takes ``user_id``: there is deliberately no way to read
or write another tenant's data, which is what makes per-user isolation enforceable."""

import builtins
from collections.abc import Collection, Sequence
from dataclasses import dataclass, field
from typing import Literal, Protocol

import numpy as np
from numpy.typing import NDArray

from documind.core.config import RetrievalMode
from documind.domain import (
    Citation,
    Conversation,
    ConversationMessage,
    DailyUsage,
    Document,
    DocumentPatch,
    DocumentStatus,
    EmbeddedChunk,
    IngestJob,
    ScoredChunk,
    TokenUsage,
)


class DocumentRepository(Protocol):
    async def create(self, document: Document) -> None: ...

    async def get(self, user_id: str, document_id: str) -> Document | None: ...

    async def list(self, user_id: str) -> list[Document]: ...

    async def update(
        self,
        user_id: str,
        document_id: str,
        patch: DocumentPatch,
        *,
        expected_status: Collection[DocumentStatus] | None = None,
    ) -> Document:
        """Apply ``patch`` atomically. Raises NotFoundError if the document is missing and
        ConflictError if its current status is not in ``expected_status``."""
        ...

    async def delete(self, user_id: str, document_id: str) -> None: ...


class VectorStore(Protocol):
    """Swappable vector index (in-Lambda NumPy today; pgvector/OpenSearch/S3 Vectors later)."""

    async def upsert(self, user_id: str, chunks: Sequence[EmbeddedChunk]) -> None: ...

    async def search(
        self,
        user_id: str,
        query: NDArray[np.float32],
        *,
        query_text: str,
        top_k: int,
        document_ids: Collection[str],
        mode: RetrievalMode = RetrievalMode.DENSE,
        candidates: int = 30,
    ) -> list[ScoredChunk]:
        """Best-first chunks from ``document_ids`` (``query_text`` feeds keyword search)."""
        ...

    async def delete_document(self, user_id: str, document_id: str) -> None: ...


@dataclass(frozen=True, slots=True)
class PresignedUpload:
    url: str
    fields: dict[str, str]
    expires_in: int


class BlobStore(Protocol):
    def presign_upload(self, key: str, *, max_bytes: int, expires_in: int) -> PresignedUpload: ...

    async def size(self, key: str) -> int | None:
        """Object size in bytes, or None if it doesn't exist."""
        ...

    async def get(self, key: str) -> bytes: ...

    async def delete(self, key: str) -> None: ...


class JobQueue(Protocol):
    async def enqueue(self, job: IngestJob) -> None: ...


class RateLimiter(Protocol):
    async def hit(self, user_id: str, bucket: str, *, limit: int, window_seconds: int) -> None:
        """Count one request in the current fixed window; raise RateLimitedError when the
        user already made ``limit`` requests in it."""
        ...


class UsageRepository(Protocol):
    async def add(self, user_id: str, day: str, usage: TokenUsage, *, expires_at: int) -> None:
        """Atomically add one request's tokens to the user's counter for ``day``."""
        ...

    async def get(self, user_id: str, day: str) -> DailyUsage: ...

    # The service-wide counter (all users together) lives under its own key, never a user's.
    async def add_service(self, day: str, usage: TokenUsage, *, expires_at: int) -> None: ...

    async def get_service(self, day: str) -> DailyUsage: ...


@dataclass(frozen=True, slots=True)
class NewMessage:
    role: Literal["user", "assistant"]
    content: str
    citations: list[Citation] = field(default_factory=list)


class ConversationRepository(Protocol):
    async def create(self, conversation: Conversation) -> None: ...

    async def get(self, user_id: str, conversation_id: str) -> Conversation | None: ...

    async def list(self, user_id: str) -> list[Conversation]: ...

    async def messages(
        self, user_id: str, conversation_id: str
    ) -> builtins.list[ConversationMessage]: ...  # `list` is shadowed by the method above

    async def append(
        self, user_id: str, conversation_id: str, messages: Sequence[NewMessage]
    ) -> Conversation:
        """Store messages with the next sequential indexes (allocated atomically, so concurrent
        requests can't collide). Raises NotFoundError for an unknown conversation."""
        ...

    async def set_summary(
        self, user_id: str, conversation_id: str, summary: str, summarized_through: int
    ) -> None: ...

    async def update(
        self,
        user_id: str,
        conversation_id: str,
        *,
        title: str | None = None,
        document_ids: Sequence[str] | None = None,
    ) -> Conversation:
        """Change the given fields (None = leave unchanged). Raises NotFoundError."""
        ...

    async def delete(self, user_id: str, conversation_id: str) -> None: ...
