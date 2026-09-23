"""Ingestion worker.

``handle_message`` is the unit of work; in AWS (Phase 5) an SQS-triggered Lambda calls it per
record. Locally, ``python -m documind.worker`` long-polls the queue and does the same thing.
"""

import asyncio
import logging

from documind.core.config import Backend, get_settings
from documind.core.container import Container, build_container
from documind.core.logging import configure_logging
from documind.repositories.sqs import SqsJobQueue, decode_job

logger = logging.getLogger(__name__)


async def handle_message(container: Container, body: str, receive_count: int) -> None:
    """Process one queue message. Raising leaves the message on the queue for a retry."""
    await container.ingestion_service.process(
        decode_job(body),
        attempt=receive_count,
        max_attempts=container.settings.sqs_max_receive_count,
    )


async def run(container: Container) -> None:
    queue = container.queue
    if not isinstance(queue, SqsJobQueue):
        raise RuntimeError("The standalone worker needs DOCUMIND_BACKEND=aws (SQS).")
    client = queue.client
    logger.info("worker started", extra={"queue_url": queue.queue_url})
    backoff = 1.0
    while True:
        try:
            response = await asyncio.to_thread(
                client.receive_message,
                QueueUrl=queue.queue_url,
                MaxNumberOfMessages=1,  # one PDF at a time keeps memory bounded
                WaitTimeSeconds=20,  # long polling: fewer empty receives (and requests)
                MessageSystemAttributeNames=["ApproximateReceiveCount"],
            )
        except Exception:
            # Queue briefly unreachable: back off instead of crashing the worker.
            logger.exception("receive failed", extra={"retry_in_s": backoff})
            await asyncio.sleep(backoff)
            backoff = min(backoff * 2, 30.0)
            continue
        backoff = 1.0
        for message in response.get("Messages", []):
            receive_count = int(message["Attributes"]["ApproximateReceiveCount"])
            try:
                await handle_message(container, message["Body"], receive_count)
            except Exception:
                # Visibility timeout expires → SQS redelivers; after maxReceiveCount → DLQ.
                logger.exception("message failed", extra={"receive_count": receive_count})
                continue
            await asyncio.to_thread(
                client.delete_message,
                QueueUrl=queue.queue_url,
                ReceiptHandle=message["ReceiptHandle"],
            )


def main() -> None:
    settings = get_settings()
    configure_logging(settings.log_level)
    if settings.backend is not Backend.AWS:
        raise SystemExit("Set DOCUMIND_BACKEND=aws to run the standalone worker.")
    asyncio.run(run(build_container(settings)))


if __name__ == "__main__":
    main()
