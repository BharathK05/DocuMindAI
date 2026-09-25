"""AWS Lambda entry point for the ingestion worker (triggered by SQS).

Handler: ``documind.lambda_worker.handler``. The event source mapping must enable
``ReportBatchItemFailures`` so that only the failed messages in a batch are retried, instead of
the whole batch (which would re-ingest documents that already succeeded).

The container and event loop live at module level: Lambda reuses the process across warm
invocations, so SDK clients and HTTP connection pools are built once per cold start. A single
long-lived loop is required because the OpenAI client's connection pool is bound to the loop it
was created on; ``asyncio.run`` per invocation would close that loop and break the next call.
"""

import asyncio
import logging
from typing import Any

from opentelemetry.trace import SpanKind

from documind.core import tracing
from documind.core.config import get_settings
from documind.core.container import Container, build_container
from documind.core.logging import configure_logging
from documind.worker import handle_message

logger = logging.getLogger(__name__)

_loop = asyncio.new_event_loop()
_container: Container | None = None


def _get_container() -> Container:
    global _container
    if _container is None:
        settings = get_settings()
        configure_logging(settings.log_level)
        tracing.setup(
            "documind-worker", enabled=settings.tracing_enabled, region=settings.aws_region
        )
        _container = build_container(settings)
    return _container


async def _process(event: dict[str, Any]) -> dict[str, Any]:
    container = _get_container()
    failures: list[dict[str, str]] = []
    for record in event.get("Records", []):
        message_id = record["messageId"]
        attributes = record.get("attributes", {})
        receive_count = int(attributes.get("ApproximateReceiveCount", "1"))
        # Continue the API's trace (carried on the message), else this invocation's own.
        parent = tracing.context_from_header(attributes.get("AWSTraceHeader"))
        try:
            with (
                tracing.attached(parent or tracing.lambda_context()),
                tracing.span("ingest document", kind=SpanKind.CONSUMER, message_id=message_id),
            ):
                await handle_message(container, record["body"], receive_count)
        except Exception:
            logger.exception(
                "record failed", extra={"message_id": message_id, "receive_count": receive_count}
            )
            failures.append({"itemIdentifier": message_id})
    return {"batchItemFailures": failures}


def handler(event: dict[str, Any], context: Any) -> dict[str, Any]:
    try:
        return _loop.run_until_complete(_process(event))
    finally:
        tracing.flush()  # Lambda freezes the process after returning; export spans first
