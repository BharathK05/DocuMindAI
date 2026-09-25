"""Document lifecycle: request an upload URL → confirm upload → (async ingestion) → list/delete."""

import logging
import time
import uuid
from dataclasses import dataclass

from documind.core.config import Settings
from documind.core.errors import (
    ConflictError,
    InvalidInputError,
    NotFoundError,
    PayloadTooLargeError,
)
from documind.domain import Document, DocumentPatch, DocumentStatus, IngestJob
from documind.repositories.base import (
    BlobStore,
    DocumentRepository,
    JobQueue,
    PresignedUpload,
    RateLimiter,
    VectorStore,
)

logger = logging.getLogger(__name__)

MAX_FILENAME_CHARS = 255
UPLOAD_WINDOW_SECONDS = 3600


@dataclass(frozen=True, slots=True)
class UploadTicket:
    document: Document
    upload: PresignedUpload


def validate_upload(filename: str, size_bytes: int, max_bytes: int) -> str:
    name = filename.strip().replace("\\", "/").rsplit("/", 1)[-1]  # drop any client path
    if not name or len(name) > MAX_FILENAME_CHARS:
        raise InvalidInputError("Filename must be 1-255 characters.")
    if not name.lower().endswith(".pdf"):
        raise InvalidInputError("Only PDF files are supported.")
    if size_bytes <= 0:
        raise InvalidInputError("File is empty.")
    if size_bytes > max_bytes:
        raise PayloadTooLargeError(f"File exceeds the {max_bytes // (1024 * 1024)} MB limit.")
    return name


class DocumentService:
    def __init__(
        self,
        settings: Settings,
        documents: DocumentRepository,
        vectors: VectorStore,
        blobs: BlobStore,
        queue: JobQueue,
        limiter: RateLimiter,
    ) -> None:
        self._settings = settings
        self._documents = documents
        self._vectors = vectors
        self._blobs = blobs
        self._queue = queue
        self._limiter = limiter

    async def create_upload(self, user_id: str, filename: str, size_bytes: int) -> UploadTicket:
        name = validate_upload(filename, size_bytes, self._settings.upload_max_bytes)
        await self._limiter.hit(
            user_id,
            "upload",
            limit=self._settings.rate_limit_uploads_per_hour,
            window_seconds=UPLOAD_WINDOW_SECONDS,
        )
        document = Document(
            user_id=user_id,
            document_id=uuid.uuid4().hex,
            filename=name,
            status=DocumentStatus.AWAITING_UPLOAD,
            size_bytes=size_bytes,
            # If the client never uploads, DynamoDB's TTL removes this record automatically.
            expires_at=int(time.time()) + self._settings.upload_ttl_seconds,
        )
        await self._documents.create(document)
        upload = self._blobs.presign_upload(
            document.blob_key,
            max_bytes=self._settings.upload_max_bytes,
            expires_in=self._settings.presign_expiry_seconds,
        )
        logger.info("upload requested", extra={"document_id": document.document_id})
        return UploadTicket(document, upload)

    async def complete_upload(self, user_id: str, document_id: str) -> Document:
        document = await self.get(user_id, document_id)
        if document.status is not DocumentStatus.AWAITING_UPLOAD:
            raise ConflictError(f"Upload already completed (document is {document.status}).")
        size = await self._blobs.size(document.blob_key)
        if size is None:
            raise InvalidInputError("The file has not been uploaded yet.")
        if size > self._settings.upload_max_bytes:
            # S3 already enforces this via the presigned POST policy; re-checking here means we
            # never rely on a single control (and local emulators don't enforce the policy).
            await self._blobs.delete(document.blob_key)
            raise PayloadTooLargeError("The uploaded file exceeds the size limit.")
        # Conditional transition: a double "complete" call can't enqueue the job twice.
        document = await self._documents.update(
            user_id,
            document_id,
            DocumentPatch(status=DocumentStatus.PENDING, size_bytes=size, expires_at=None),
            expected_status={DocumentStatus.AWAITING_UPLOAD},
        )
        await self._queue.enqueue(IngestJob(user_id, document_id))
        logger.info("ingestion queued", extra={"document_id": document_id, "bytes": size})
        return document

    async def get(self, user_id: str, document_id: str) -> Document:
        document = await self._documents.get(user_id, document_id)
        if document is None:
            raise NotFoundError("Document not found.")
        return document

    async def list(self, user_id: str) -> list[Document]:
        return await self._documents.list(user_id)

    async def delete(self, user_id: str, document_id: str) -> None:
        document = await self.get(user_id, document_id)
        # Order matters: remove searchable data first so a partial failure never leaves chunks
        # that are still retrievable after the user asked for deletion.
        await self._vectors.delete_document(user_id, document_id)
        await self._blobs.delete(document.blob_key)
        await self._documents.delete(user_id, document_id)
        logger.info("document deleted", extra={"document_id": document_id})
