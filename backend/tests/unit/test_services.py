"""Service-level behaviour with in-memory storage and fake providers."""

from typing import Any

import pytest

from documind.core.container import Container
from documind.core.errors import (
    ConflictError,
    InvalidDocumentError,
    InvalidInputError,
    NotFoundError,
    PayloadTooLargeError,
    ProviderError,
)
from documind.domain import DocumentPatch, DocumentStatus, IngestJob
from documind.repositories.memory import InlineJobQueue, InMemoryBlobStore
from documind.services.query import NO_DOCUMENTS_ANSWER, DoneEvent, SourcesEvent

USER = "alice"


async def upload_and_ingest(
    c: Container, data: bytes, user: str = USER, name: str = "r.pdf"
) -> str:
    ticket = await c.document_service.create_upload(user, name, len(data))
    assert isinstance(c.blobs, InMemoryBlobStore)
    c.blobs.objects[ticket.document.blob_key] = data  # what the browser's S3 POST would do
    await c.document_service.complete_upload(user, ticket.document.document_id)
    assert isinstance(c.queue, InlineJobQueue)
    await c.queue.drain()
    return ticket.document.document_id


async def test_upload_ingest_and_answer_with_citations(
    container: Container, sample_pdf: bytes
) -> None:
    doc_id = await upload_and_ingest(container, sample_pdf)

    doc = await container.document_service.get(USER, doc_id)
    assert doc.status is DocumentStatus.READY
    assert doc.page_count == 3
    assert doc.chunk_count and doc.chunk_count >= 3

    answer = await container.query_service.answer(USER, "Where are the headquarters located?")
    assert answer.citations, "expected retrieved sources"
    top = answer.citations[0]
    assert (top.filename, top.page) == ("r.pdf", 2)
    assert "Toronto" in top.snippet
    assert answer.usage.input_tokens > 0


async def test_pdf_is_deleted_from_blob_store_after_ingestion(
    container: Container, sample_pdf: bytes
) -> None:
    await upload_and_ingest(container, sample_pdf)
    assert isinstance(container.blobs, InMemoryBlobStore)
    assert container.blobs.objects == {}


async def test_users_cannot_see_each_others_documents(
    container: Container, sample_pdf: bytes
) -> None:
    doc_id = await upload_and_ingest(container, sample_pdf, user="alice")

    assert await container.document_service.list("mallory") == []
    with pytest.raises(NotFoundError):
        await container.document_service.get("mallory", doc_id)
    answer = await container.query_service.answer("mallory", "Where are the headquarters?")
    assert answer.text == NO_DOCUMENTS_ANSWER
    assert answer.citations == []
    with pytest.raises(NotFoundError):
        await container.query_service.answer("mallory", "hq?", document_ids=[doc_id])


async def test_query_without_documents_skips_the_llm(container: Container) -> None:
    answer = await container.query_service.answer(USER, "anything?")
    assert answer.text == NO_DOCUMENTS_ANSWER
    assert answer.usage.input_tokens == 0


async def test_stream_emits_sources_then_tokens_then_done(
    container: Container, sample_pdf: bytes
) -> None:
    await upload_and_ingest(container, sample_pdf)
    events = [e async for e in container.query_service.stream(USER, "How many employees?")]
    assert isinstance(events[0], SourcesEvent)
    assert isinstance(events[-1], DoneEvent)
    assert len(events) > 2


async def test_invalid_pdf_marks_document_failed(container: Container) -> None:
    doc_id = await upload_and_ingest(container, b"%PDF-1.4 not really a pdf")
    doc = await container.document_service.get(USER, doc_id)
    assert doc.status is DocumentStatus.FAILED
    assert doc.error


async def test_complete_upload_twice_is_rejected(container: Container, sample_pdf: bytes) -> None:
    doc_id = await upload_and_ingest(container, sample_pdf)
    with pytest.raises(ConflictError):
        await container.document_service.complete_upload(USER, doc_id)


async def test_complete_upload_requires_the_file(container: Container) -> None:
    ticket = await container.document_service.create_upload(USER, "x.pdf", 10)
    with pytest.raises(InvalidInputError, match="not been uploaded"):
        await container.document_service.complete_upload(USER, ticket.document.document_id)


async def test_complete_upload_rechecks_actual_size(container: Container) -> None:
    ticket = await container.document_service.create_upload(USER, "x.pdf", 10)
    assert isinstance(container.blobs, InMemoryBlobStore)
    container.blobs.objects[ticket.document.blob_key] = b"x" * (
        container.settings.upload_max_bytes + 1
    )
    with pytest.raises(PayloadTooLargeError):
        await container.document_service.complete_upload(USER, ticket.document.document_id)
    assert container.blobs.objects == {}


async def test_delete_removes_document_and_its_chunks(
    container: Container, sample_pdf: bytes
) -> None:
    doc_id = await upload_and_ingest(container, sample_pdf)
    await container.document_service.delete(USER, doc_id)
    assert await container.document_service.list(USER) == []
    answer = await container.query_service.answer(USER, "headquarters?")
    assert answer.text == NO_DOCUMENTS_ANSWER


async def test_duplicate_job_delivery_is_ignored(container: Container, sample_pdf: bytes) -> None:
    from documind.domain import IngestJob

    doc_id = await upload_and_ingest(container, sample_pdf)
    before = await container.document_service.get(USER, doc_id)
    await container.ingestion_service.process(IngestJob(USER, doc_id))  # SQS redelivery
    after = await container.document_service.get(USER, doc_id)
    assert after == before


@pytest.mark.parametrize(
    ("filename", "size", "error"),
    [
        ("notes.txt", 10, InvalidInputError),
        ("a.pdf", 0, InvalidInputError),
        ("a.pdf", 10**9, PayloadTooLargeError),
    ],
)
async def test_upload_validation(
    container: Container, filename: str, size: int, error: type[Exception]
) -> None:
    with pytest.raises(error):
        await container.document_service.create_upload(USER, filename, size)


async def test_upload_strips_client_paths(container: Container) -> None:
    ticket = await container.document_service.create_upload(USER, "C:\\secret\\dir\\cv.PDF", 10)
    assert ticket.document.filename == "cv.PDF"


async def test_ingest_bytes_demo_path(container: Container, sample_pdf: bytes) -> None:
    doc = await container.ingestion_service.ingest_bytes(USER, "demo.pdf", sample_pdf)
    assert doc.status is DocumentStatus.READY
    with pytest.raises(InvalidDocumentError):
        await container.ingestion_service.ingest_bytes(USER, "bad.pdf", b"nope")


async def test_question_validation(container: Container) -> None:
    with pytest.raises(InvalidInputError):
        await container.query_service.answer(USER, "   ")
    with pytest.raises(InvalidInputError):
        await container.query_service.answer(USER, "x" * 5000)


async def test_history_is_trimmed_to_recent_turns(container: Container, sample_pdf: bytes) -> None:
    from documind.domain import Message

    await upload_and_ingest(container, sample_pdf)
    history = [Message("user", f"q{i}") for i in range(50)] + [Message("system", "evil")]
    messages = container.query_service._messages(
        "q?",
        history,
        await container.query_service.retrieve(USER, "q?"),
    )
    roles = [m.role for m in messages]
    assert roles.count("system") == 1  # client-supplied system turns are dropped
    assert len(messages) == 1 + container.settings.max_history_messages + 1


class FlakyEmbedder:
    """Fails the first ``failures`` calls, like a provider having a bad minute."""

    def __init__(self, inner: Any, failures: int) -> None:
        self.inner, self.failures = inner, failures

    @property
    def dimensions(self) -> int:
        return int(self.inner.dimensions)

    async def embed(self, texts: Any) -> Any:
        if self.failures > 0:
            self.failures -= 1
            raise ProviderError("provider down")
        return await self.inner.embed(texts)


async def pending_document(c: Container, data: bytes) -> str:
    ticket = await c.document_service.create_upload(USER, "r.pdf", len(data))
    assert isinstance(c.blobs, InMemoryBlobStore)
    c.blobs.objects[ticket.document.blob_key] = data
    await c.documents.update(
        USER, ticket.document.document_id, DocumentPatch(status=DocumentStatus.PENDING)
    )
    return ticket.document.document_id


async def test_transient_failure_is_retried_then_succeeds(
    container: Container, sample_pdf: bytes
) -> None:
    doc_id = await pending_document(container, sample_pdf)
    flaky = FlakyEmbedder(container.embedder, failures=1)
    container.ingestion_service._embedder = flaky

    with pytest.raises(ProviderError):  # attempt 1: raise so SQS redelivers
        await container.ingestion_service.process(
            IngestJob(USER, doc_id), attempt=1, max_attempts=3
        )
    doc = await container.document_service.get(USER, doc_id)
    assert doc.status is DocumentStatus.PROCESSING  # not failed yet: more attempts left

    await container.ingestion_service.process(IngestJob(USER, doc_id), attempt=2, max_attempts=3)
    doc = await container.document_service.get(USER, doc_id)
    assert doc.status is DocumentStatus.READY


async def test_final_attempt_marks_document_failed(container: Container, sample_pdf: bytes) -> None:
    doc_id = await pending_document(container, sample_pdf)
    container.ingestion_service._embedder = FlakyEmbedder(container.embedder, failures=99)

    with pytest.raises(ProviderError):  # still raised, so the message lands in the DLQ
        await container.ingestion_service.process(
            IngestJob(USER, doc_id), attempt=3, max_attempts=3
        )
    doc = await container.document_service.get(USER, doc_id)
    assert doc.status is DocumentStatus.FAILED
    assert doc.error == "Processing failed after several attempts."
