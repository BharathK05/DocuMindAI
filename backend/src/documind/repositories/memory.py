"""In-process implementations for unit tests and the single-process Gradio demo."""

import asyncio
from collections.abc import Callable, Collection, Coroutine, Sequence
from typing import Any

import numpy as np
from numpy.typing import NDArray

from documind.core.config import RetrievalMode
from documind.core.errors import ConflictError, NotFoundError
from documind.domain import (
    Document,
    DocumentPatch,
    DocumentStatus,
    EmbeddedChunk,
    IngestJob,
    ScoredChunk,
    utcnow,
)
from documind.repositories.base import PresignedUpload
from documind.repositories.search import rank


class InMemoryDocumentRepository:
    def __init__(self) -> None:
        self._docs: dict[tuple[str, str], Document] = {}
        self._lock = asyncio.Lock()

    async def create(self, document: Document) -> None:
        self._docs[(document.user_id, document.document_id)] = document

    async def get(self, user_id: str, document_id: str) -> Document | None:
        return self._docs.get((user_id, document_id))

    async def list(self, user_id: str) -> list[Document]:
        docs = [d for (uid, _), d in self._docs.items() if uid == user_id]
        return sorted(docs, key=lambda d: d.created_at, reverse=True)

    async def update(
        self,
        user_id: str,
        document_id: str,
        patch: DocumentPatch,
        *,
        expected_status: Collection[DocumentStatus] | None = None,
    ) -> Document:
        async with self._lock:
            current = self._docs.get((user_id, document_id))
            if current is None:
                raise NotFoundError("Document not found.")
            if expected_status is not None and current.status not in expected_status:
                raise ConflictError(f"Document is {current.status}.")
            updated = current.model_copy(
                update={**patch.model_dump(exclude_unset=True), "updated_at": utcnow()}
            )
            self._docs[(user_id, document_id)] = updated
            return updated

    async def delete(self, user_id: str, document_id: str) -> None:
        self._docs.pop((user_id, document_id), None)


class InMemoryVectorStore:
    def __init__(self) -> None:
        self._chunks: dict[str, list[EmbeddedChunk]] = {}

    async def upsert(self, user_id: str, chunks: Sequence[EmbeddedChunk]) -> None:
        keys = {(c.chunk.document_id, c.chunk.index) for c in chunks}
        existing = [
            c
            for c in self._chunks.get(user_id, [])
            if (c.chunk.document_id, c.chunk.index) not in keys
        ]
        self._chunks[user_id] = existing + list(chunks)

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
        scoped = [c for c in self._chunks.get(user_id, []) if c.chunk.document_id in document_ids]
        if not scoped:
            return []
        ranked = rank(
            [c.chunk.search_text for c in scoped],
            np.vstack([c.vector for c in scoped]),
            query,
            query_text,
            top_k=top_k,
            mode=mode,
            candidates=candidates,
        )
        return [ScoredChunk(scoped[i].chunk, score) for i, score in ranked]

    async def delete_document(self, user_id: str, document_id: str) -> None:
        self._chunks[user_id] = [
            c for c in self._chunks.get(user_id, []) if c.chunk.document_id != document_id
        ]


class InMemoryBlobStore:
    def __init__(self) -> None:
        self.objects: dict[str, bytes] = {}

    def presign_upload(self, key: str, *, max_bytes: int, expires_in: int) -> PresignedUpload:
        return PresignedUpload(url=f"memory://{key}", fields={"key": key}, expires_in=expires_in)

    async def size(self, key: str) -> int | None:
        data = self.objects.get(key)
        return None if data is None else len(data)

    async def get(self, key: str) -> bytes:
        try:
            return self.objects[key]
        except KeyError:
            raise NotFoundError("Upload not found.") from None

    async def delete(self, key: str) -> None:
        self.objects.pop(key, None)


JobHandler = Callable[[IngestJob], Coroutine[Any, Any, None]]


class InlineJobQueue:
    """Runs jobs as background tasks in the same process instead of going through SQS."""

    def __init__(self) -> None:
        self.handler: JobHandler | None = None
        self._tasks: set[asyncio.Task[None]] = set()

    async def enqueue(self, job: IngestJob) -> None:
        if self.handler is None:
            raise RuntimeError("InlineJobQueue has no handler bound")
        task = asyncio.create_task(self.handler(job))
        self._tasks.add(task)  # keep a reference so the task isn't garbage-collected mid-run
        task.add_done_callback(self._tasks.discard)

    async def drain(self) -> None:
        """Wait for all queued jobs (used by tests)."""
        # Filter on done() rather than looping on the set itself: a finished task stays in the
        # set until its done-callback runs, and awaiting an already-finished gather never
        # yields to the event loop, so that callback would never get a chance to run.
        while pending := [t for t in self._tasks if not t.done()]:
            await asyncio.gather(*pending, return_exceptions=True)
