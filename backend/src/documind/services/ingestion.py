"""Ingestion pipeline: PDF bytes → pages → chunks → embeddings → vector store.

Runs in the worker (SQS-triggered Lambda in AWS). SQS delivers at-least-once, so ``process`` is
idempotent: status transitions are conditional and chunk keys are deterministic.
"""

import asyncio
import contextlib
import logging
import time
import uuid

from documind.core.config import ChunkingStrategy, Settings
from documind.core.errors import ConflictError, InvalidDocumentError, NotFoundError
from documind.domain import (
    Chunk,
    Document,
    DocumentPatch,
    DocumentStatus,
    EmbeddedChunk,
    IngestJob,
)
from documind.ingestion.chunking import chunk_pages
from documind.ingestion.pdf import ParsedPdf, parse_pdf
from documind.ingestion.structure import structured_chunks
from documind.providers.base import EmbeddingProvider
from documind.repositories.base import BlobStore, DocumentRepository, VectorStore
from documind.services.documents import validate_upload

logger = logging.getLogger(__name__)


class IngestionService:
    def __init__(
        self,
        settings: Settings,
        documents: DocumentRepository,
        vectors: VectorStore,
        blobs: BlobStore,
        embedder: EmbeddingProvider,
    ) -> None:
        self._settings = settings
        self._documents = documents
        self._vectors = vectors
        self._blobs = blobs
        self._embedder = embedder

    async def process(self, job: IngestJob, *, attempt: int = 1, max_attempts: int = 1) -> None:
        """Ingest one uploaded document. Raises on transient failure so the queue retries."""
        log = {"document_id": job.document_id, "attempt": attempt}
        try:
            document = await self._documents.update(
                job.user_id,
                job.document_id,
                DocumentPatch(status=DocumentStatus.PROCESSING, error=None),
                expected_status={DocumentStatus.PENDING, DocumentStatus.PROCESSING},
            )
        except (NotFoundError, ConflictError) as exc:
            # Deleted meanwhile, or a duplicate delivery of an already-finished job.
            logger.info("ingestion skipped", extra={**log, "reason": exc.message})
            return

        try:
            data = await self._blobs.get(document.blob_key)
            page_count, chunk_count = await self._index(document, data)
        except InvalidDocumentError as exc:
            await self._fail(document, exc.message)
            await self._blobs.delete(document.blob_key)
            return
        except Exception:
            logger.exception("ingestion attempt failed", extra=log)
            if attempt >= max_attempts:
                await self._fail(document, "Processing failed after several attempts.")
            raise  # let SQS retry; after max attempts the message lands in the DLQ

        await self._finish(document, page_count, chunk_count)
        # PDFs aren't needed once indexed; deleting them keeps S3 storage (and cost) near zero.
        await self._blobs.delete(document.blob_key)

    async def ingest_bytes(self, user_id: str, filename: str, data: bytes) -> Document:
        """Synchronous path used by the single-process Gradio demo (no S3/SQS involved)."""
        name = validate_upload(filename, len(data), self._settings.upload_max_bytes)
        document = Document(
            user_id=user_id,
            document_id=uuid.uuid4().hex,
            filename=name,
            status=DocumentStatus.PROCESSING,
            size_bytes=len(data),
        )
        await self._documents.create(document)
        try:
            page_count, chunk_count = await self._index(document, data)
        except InvalidDocumentError as exc:
            await self._fail(document, exc.message)
            raise
        return await self._finish(document, page_count, chunk_count)

    async def _index(self, document: Document, data: bytes) -> tuple[int, int]:
        started = time.perf_counter()
        if len(data) > self._settings.upload_max_bytes:
            raise InvalidDocumentError("The file exceeds the upload size limit.")
        # pypdf is CPU-bound; a worker thread keeps the event loop responsive.
        parsed = await asyncio.to_thread(parse_pdf, data, max_pages=self._settings.upload_max_pages)
        pages = parsed.pages
        chunks = await asyncio.to_thread(self._chunk, document, parsed)
        if not chunks:
            raise InvalidDocumentError("No usable text was found in the PDF.")
        vectors = await self._embedder.embed([c.search_text for c in chunks])
        await self._vectors.upsert(
            document.user_id,
            [EmbeddedChunk(c, v) for c, v in zip(chunks, vectors, strict=True)],
        )
        logger.info(
            "document indexed",
            extra={
                "document_id": document.document_id,
                "pages": len(pages),
                "chunks": len(chunks),
                "duration_ms": round((time.perf_counter() - started) * 1000),
            },
        )
        return len(pages), len(chunks)

    def _chunk(self, document: Document, parsed: ParsedPdf) -> list[Chunk]:
        s = self._settings
        if s.chunking_strategy is ChunkingStrategy.STRUCTURED:
            return structured_chunks(
                parsed.pages,
                document_id=document.document_id,
                title=parsed.title or document.filename.rsplit(".", 1)[0],
                chunk_tokens=s.chunk_tokens,
                overlap_tokens=s.chunk_overlap_tokens,
                tokenizer=s.embedding_tokenizer,
            )
        return chunk_pages(
            parsed.pages,
            document_id=document.document_id,
            chunk_size=s.chunk_size,
            overlap=s.chunk_overlap,
        )

    async def _finish(self, document: Document, page_count: int, chunk_count: int) -> Document:
        try:
            return await self._documents.update(
                document.user_id,
                document.document_id,
                DocumentPatch(
                    status=DocumentStatus.READY, page_count=page_count, chunk_count=chunk_count
                ),
                expected_status={DocumentStatus.PROCESSING},
            )
        except NotFoundError:
            # The user deleted the document while we were indexing it: remove what we wrote.
            await self._vectors.delete_document(document.user_id, document.document_id)
            raise

    async def _fail(self, document: Document, reason: str) -> None:
        logger.warning(
            "ingestion failed", extra={"document_id": document.document_id, "reason": reason}
        )
        with contextlib.suppress(NotFoundError):  # deleted meanwhile: nothing left to mark
            await self._documents.update(
                document.user_id,
                document.document_id,
                DocumentPatch(status=DocumentStatus.FAILED, error=reason),
            )
