"""The AWS-backed repositories (DynamoDB, S3, SQS) against moto's in-process AWS emulation."""

from collections.abc import Iterator

import boto3
import numpy as np
import pytest
from moto import mock_aws

from documind.core.config import Backend, LLMProviderName, Settings
from documind.core.container import Container, build_container
from documind.core.errors import ConflictError, NotFoundError
from documind.domain import (
    Chunk,
    Document,
    DocumentPatch,
    DocumentStatus,
    EmbeddedChunk,
)
from documind.providers.base import l2_normalize
from documind.repositories.sqs import SqsJobQueue
from documind.scripts.bootstrap_local import bootstrap
from documind.worker import handle_message


@pytest.fixture
def aws_settings(monkeypatch: pytest.MonkeyPatch) -> Iterator[Settings]:
    for key in ("AWS_ACCESS_KEY_ID", "AWS_SECRET_ACCESS_KEY"):
        monkeypatch.setenv(key, "testing")
    with mock_aws():
        settings = Settings(
            _env_file=None,
            backend=Backend.AWS,
            llm_provider=LLMProviderName.FAKE,
            chunk_size=200,
            chunk_overlap=30,
        )
        bootstrap(settings)
        yield settings


@pytest.fixture
def aws(aws_settings: Settings) -> Container:
    return build_container(aws_settings)


def doc(user: str = "u1", doc_id: str = "d" * 32) -> Document:
    return Document(
        user_id=user, document_id=doc_id, filename="a.pdf", status=DocumentStatus.PENDING
    )


async def test_document_repository_roundtrip_and_conditional_update(aws: Container) -> None:
    repo = aws.documents
    await repo.create(doc())
    fetched = await repo.get("u1", "d" * 32)
    assert fetched is not None and fetched.status is DocumentStatus.PENDING

    updated = await repo.update(
        "u1",
        "d" * 32,
        DocumentPatch(status=DocumentStatus.PROCESSING, page_count=4),
        expected_status={DocumentStatus.PENDING},
    )
    assert (updated.status, updated.page_count) == (DocumentStatus.PROCESSING, 4)

    with pytest.raises(ConflictError):
        await repo.update(
            "u1",
            "d" * 32,
            DocumentPatch(status=DocumentStatus.PROCESSING),
            expected_status={DocumentStatus.PENDING},
        )
    with pytest.raises(NotFoundError):
        await repo.update("u1", "missing", DocumentPatch(error="x"))

    assert await repo.get("u2", "d" * 32) is None  # another tenant's partition
    assert [d.document_id for d in await repo.list("u1")] == ["d" * 32]


async def test_vector_store_search_is_scoped_by_user_and_document(aws: Container) -> None:
    rng = np.random.default_rng(1)
    vectors = l2_normalize(rng.normal(size=(60, aws.embedder.dimensions)).astype(np.float32))
    chunks = [
        EmbeddedChunk(
            Chunk(
                document_id="docA" if i < 30 else "docB", index=i, page=1 + i % 5, text=f"chunk {i}"
            ),
            vectors[i],
        )
        for i in range(60)
    ]
    await aws.vectors.upsert("u1", chunks)

    hits = await aws.vectors.search(
        "u1", vectors[3], query_text="", top_k=3, document_ids={"docA", "docB"}
    )
    assert hits[0].chunk.index == 3
    assert hits[0].score == pytest.approx(1.0, abs=1e-2)  # float16 storage

    only_b = await aws.vectors.search(
        "u1", vectors[3], query_text="", top_k=5, document_ids={"docB"}
    )
    assert all(h.chunk.document_id == "docB" for h in only_b)

    assert (
        await aws.vectors.search("u2", vectors[3], query_text="", top_k=3, document_ids={"docA"})
        == []
    )

    await aws.vectors.delete_document("u1", "docA")
    remaining = await aws.vectors.search(
        "u1", vectors[3], query_text="", top_k=100, document_ids={"docA", "docB"}
    )
    assert len(remaining) == 30


async def test_s3_presigned_post_carries_size_limit(aws: Container) -> None:
    upload = aws.blobs.presign_upload("uploads/u1/x.pdf", max_bytes=1000, expires_in=60)
    assert upload.fields["key"] == "uploads/u1/x.pdf"
    assert "policy" in upload.fields
    assert await aws.blobs.size("uploads/u1/x.pdf") is None


async def test_end_to_end_through_sqs(aws: Container, sample_pdf: bytes) -> None:
    ticket = await aws.document_service.create_upload("u1", "report.pdf", len(sample_pdf))
    s3 = boto3.client("s3", region_name=aws.settings.aws_region)
    s3.put_object(Bucket=aws.settings.s3_bucket, Key=ticket.document.blob_key, Body=sample_pdf)
    await aws.document_service.complete_upload("u1", ticket.document.document_id)

    assert isinstance(aws.queue, SqsJobQueue)
    received = aws.queue.client.receive_message(QueueUrl=aws.queue.queue_url)
    message = received["Messages"][0]
    await handle_message(aws, message["Body"], receive_count=1)

    document = await aws.document_service.get("u1", ticket.document.document_id)
    assert document.status is DocumentStatus.READY
    assert await aws.blobs.size(ticket.document.blob_key) is None  # PDF deleted after indexing
    answer = await aws.query_service.answer("u1", "Where are the headquarters?")
    assert answer.citations[0].page == 2


async def test_worker_poll_deletes_successes_and_keeps_failures(
    aws: Container, sample_pdf: bytes
) -> None:
    from documind.worker import poll_once

    assert isinstance(aws.queue, SqsJobQueue)
    queue = aws.queue
    ticket = await aws.document_service.create_upload("u1", "r.pdf", len(sample_pdf))
    boto3.client("s3", region_name=aws.settings.aws_region).put_object(
        Bucket=aws.settings.s3_bucket, Key=ticket.document.blob_key, Body=sample_pdf
    )
    await aws.document_service.complete_upload("u1", ticket.document.document_id)
    assert await poll_once(aws, queue, wait_seconds=0) == 1  # processed and deleted

    queue.client.send_message(QueueUrl=queue.queue_url, MessageBody="not json")
    assert await poll_once(aws, queue, wait_seconds=0) == 0  # failed: left for redelivery
    attrs = queue.client.get_queue_attributes(
        QueueUrl=queue.queue_url, AttributeNames=["ApproximateNumberOfMessagesNotVisible"]
    )["Attributes"]
    assert attrs["ApproximateNumberOfMessagesNotVisible"] == "1"


async def test_dynamo_rate_limiter_usage_and_ttl(aws_settings: Settings) -> None:
    from documind.core.errors import RateLimitedError
    from documind.domain import TokenUsage
    from documind.repositories.dynamodb import DynamoTable
    from documind.repositories.usage import DynamoRateLimiter, DynamoUsageRepository

    client = boto3.client("dynamodb", region_name=aws_settings.aws_region)
    table = DynamoTable(client, aws_settings.dynamodb_table)
    ttl = client.describe_time_to_live(TableName=aws_settings.dynamodb_table)
    assert ttl["TimeToLiveDescription"]["AttributeName"] == "expires_at"

    limiter = DynamoRateLimiter(table, clock=lambda: 1_000_000.0)
    await limiter.hit("u1", "query", limit=2, window_seconds=60)
    await limiter.hit("u1", "query", limit=2, window_seconds=60)
    with pytest.raises(RateLimitedError):
        await limiter.hit("u1", "query", limit=2, window_seconds=60)
    await limiter.hit("u2", "query", limit=2, window_seconds=60)  # separate partition

    usage = DynamoUsageRepository(table)
    await usage.add("u1", "2026-09-25", TokenUsage(100, 10), expires_at=2_000_000_000)
    await usage.add("u1", "2026-09-25", TokenUsage(50, 5), expires_at=2_000_000_000)
    day = await usage.get("u1", "2026-09-25")
    assert (day.input_tokens, day.output_tokens, day.requests) == (150, 15, 2)
    assert (await usage.get("u2", "2026-09-25")).total_tokens == 0


async def test_dynamo_conversations(aws_settings: Settings) -> None:
    from documind.domain import Citation, Conversation
    from documind.repositories.base import NewMessage
    from documind.repositories.conversations import DynamoConversationRepository
    from documind.repositories.dynamodb import DynamoTable

    table = DynamoTable(
        boto3.client("dynamodb", region_name=aws_settings.aws_region), aws_settings.dynamodb_table
    )
    repo = DynamoConversationRepository(table)
    cid = "c" * 32
    await repo.create(Conversation(user_id="u1", conversation_id=cid, title="Tiers"))
    citation = Citation(1, "d" * 32, "csf.pdf", 12, 0.9, "Tier 1: Partial")
    await repo.append(
        "u1", cid, [NewMessage("user", "q1"), NewMessage("assistant", "a1", [citation])]
    )
    updated = await repo.append(
        "u1", cid, [NewMessage("user", "q2"), NewMessage("assistant", "a2")]
    )
    assert updated.message_count == 4

    messages = await repo.messages("u1", cid)
    assert [(m.index, m.content) for m in messages] == [(0, "q1"), (1, "a1"), (2, "q2"), (3, "a2")]
    assert messages[1].citations[0].page == 12

    await repo.set_summary("u1", cid, "summary so far", 2)
    stored = await repo.get("u1", cid)
    assert stored is not None and (stored.summary, stored.summarized_through) == (
        "summary so far",
        2,
    )
    assert await repo.get("u2", cid) is None  # other tenants can't see it
    with pytest.raises(NotFoundError):
        await repo.append("u2", cid, [NewMessage("user", "x")])

    renamed = await repo.update("u1", cid, title="CSF tiers", document_ids=["d1", "d2"])
    assert (renamed.title, renamed.document_ids, renamed.message_count) == (
        "CSF tiers",
        ["d1", "d2"],
        4,
    )
    assert (await repo.update("u1", cid, document_ids=[])).title == "CSF tiers"
    with pytest.raises(NotFoundError):
        await repo.update("u2", cid, title="x")

    await repo.delete("u1", cid)
    assert await repo.get("u1", cid) is None
    assert await repo.messages("u1", cid) == []


async def test_dynamo_document_expiry_is_set_then_cleared(
    aws: Container, sample_pdf: bytes
) -> None:
    ticket = await aws.document_service.create_upload("u1", "r.pdf", len(sample_pdf))
    stored = await aws.documents.get("u1", ticket.document.document_id)
    assert stored is not None and stored.expires_at is not None
    boto3.client("s3", region_name=aws.settings.aws_region).put_object(
        Bucket=aws.settings.s3_bucket, Key=ticket.document.blob_key, Body=sample_pdf
    )
    completed = await aws.document_service.complete_upload("u1", ticket.document.document_id)
    assert completed.expires_at is None
