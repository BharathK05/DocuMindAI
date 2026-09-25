"""The SQS-triggered Lambda handler: partial batch failures and container reuse."""

from collections.abc import Iterator
from typing import Any

import pytest

from documind import lambda_worker
from documind.core.container import Container
from documind.domain import DocumentPatch, DocumentStatus, IngestJob
from documind.repositories.memory import InMemoryBlobStore
from documind.repositories.sqs import encode_job


@pytest.fixture
def worker(container: Container) -> Iterator[Container]:
    lambda_worker._container = container  # inject the in-memory container
    yield container
    lambda_worker._container = None


def sqs_event(*bodies: str) -> dict[str, Any]:
    return {
        "Records": [
            {"messageId": f"m{i}", "body": body, "attributes": {"ApproximateReceiveCount": "1"}}
            for i, body in enumerate(bodies)
        ]
    }


def test_handler_ingests_and_reports_only_failed_records(
    worker: Container, sample_pdf: bytes
) -> None:
    async def pending_upload() -> str:
        ticket = await worker.document_service.create_upload("u1", "r.pdf", len(sample_pdf))
        assert isinstance(worker.blobs, InMemoryBlobStore)
        worker.blobs.objects[ticket.document.blob_key] = sample_pdf
        await worker.documents.update(
            "u1",
            ticket.document.document_id,
            DocumentPatch(status=DocumentStatus.PENDING),  # as complete_upload leaves it
        )
        return ticket.document.document_id

    doc_id = lambda_worker._loop.run_until_complete(pending_upload())
    good = encode_job(IngestJob("u1", doc_id))
    result = lambda_worker.handler(sqs_event(good, "not json"), None)

    assert result == {"batchItemFailures": [{"itemIdentifier": "m1"}]}
    doc = lambda_worker._loop.run_until_complete(worker.document_service.get("u1", doc_id))
    assert doc.status is DocumentStatus.READY


def test_handler_reuses_the_event_loop_across_invocations(worker: Container) -> None:
    assert lambda_worker.handler({"Records": []}, None) == {"batchItemFailures": []}
    assert lambda_worker.handler({"Records": []}, None) == {"batchItemFailures": []}
    assert not lambda_worker._loop.is_closed()
