"""SQS job queue. SQS delivers at-least-once, so the ingestion handler must be idempotent."""

import asyncio
import json
from dataclasses import asdict
from typing import TYPE_CHECKING

from documind.domain import IngestJob

if TYPE_CHECKING:
    from mypy_boto3_sqs import SQSClient


def encode_job(job: IngestJob) -> str:
    return json.dumps(asdict(job))


def decode_job(body: str) -> IngestJob:
    data = json.loads(body)
    return IngestJob(user_id=data["user_id"], document_id=data["document_id"])


class SqsJobQueue:
    def __init__(self, client: "SQSClient", queue_url: str) -> None:
        self.client = client
        self.queue_url = queue_url

    async def enqueue(self, job: IngestJob) -> None:
        await asyncio.to_thread(
            self.client.send_message, QueueUrl=self.queue_url, MessageBody=encode_job(job)
        )
