"""Persistence interfaces. Every method takes ``user_id``: there is deliberately no way to read
or write another tenant's data, which is what makes per-user isolation enforceable."""

from collections.abc import Collection, Sequence
from dataclasses import dataclass
from typing import Protocol

import numpy as np
from numpy.typing import NDArray

from documind.core.config import RetrievalMode
from documind.domain import (
    Document,
    DocumentPatch,
    DocumentStatus,
    EmbeddedChunk,
    IngestJob,
    ScoredChunk,
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
