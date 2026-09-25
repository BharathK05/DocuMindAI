"""Distributed tracing: OpenTelemetry in the code, AWS X-Ray as the backend.

Code uses the vendor-neutral OpenTelemetry API (``span("retrieve")``). When tracing is enabled
(on AWS), spans are exported to X-Ray, so one question can be followed through

    API Lambda ─► DynamoDB / OpenAI (embed, rerank, answer)
              └─► SQS ─► worker Lambda ─► S3 / OpenAI (embed) / DynamoDB

Why this shape:
* The X-Ray SDKs reach end of support in February 2027; AWS recommends OpenTelemetry.
* The OpenTelemetry Lambda layer can't be used for the API: it needs AWS_LAMBDA_EXEC_WRAPPER,
  which the Lambda Web Adapter already occupies. So spans are exported by ``XRayExporter``
  below with the X-Ray PutTraceSegments API (via boto3, already in the package).
* Lambda's own trace (active tracing) is the parent: the API receives it in the
  X-Amzn-Trace-Id request header, the worker in the _X_AMZN_TRACE_ID variable. The API passes
  the context to the worker through the SQS message's AWSTraceHeader attribute.

With tracing disabled (tests, local runs) every call here is a cheap no-op.
"""

import json
import logging
import os
import re
from collections.abc import Iterator, Mapping, Sequence
from contextlib import AbstractContextManager, contextmanager
from typing import TYPE_CHECKING, Any, cast

from opentelemetry import context as otel_context
from opentelemetry import trace
from opentelemetry.trace import Span, SpanKind, Status, StatusCode

if TYPE_CHECKING:
    from opentelemetry.sdk.trace import ReadableSpan, TracerProvider
    from opentelemetry.sdk.trace.export import SpanExporter, SpanExportResult

logger = logging.getLogger(__name__)

TRACE_HEADER = "X-Amzn-Trace-Id"
_tracer = trace.get_tracer("documind")
_provider: "TracerProvider | None" = None
_NAME_UNSAFE = re.compile(r"[^\w\s.:/%&#=+\-@]")
_KEY_UNSAFE = re.compile(r"[^A-Za-z0-9_]")


@contextmanager
def span(
    name: str, *, kind: SpanKind = SpanKind.INTERNAL, **attributes: str | int | float | bool
) -> Iterator[Span]:
    """Time a block as a span (child of the current one). Exceptions mark it as failed."""
    with _tracer.start_as_current_span(name, kind=kind, attributes=attributes) as current:
        yield current


def start(
    name: str,
    *,
    kind: SpanKind = SpanKind.INTERNAL,
    parent: otel_context.Context | None = None,
    **attributes: str | int | float | bool,
) -> Span:
    """A span that isn't made current, for spans that outlive a ``with`` block (a streamed
    response) or live in async generators, which resume in other contexts where detaching a
    current span fails. The caller must call ``.end()``."""
    return _tracer.start_span(name, context=parent, kind=kind, attributes=attributes)


def use(current: Span) -> AbstractContextManager[Span]:
    """Make ``current`` the parent of spans started inside the block, without ending it."""
    return trace.use_span(current, end_on_exit=False)


def setup(service_name: str, *, enabled: bool, region: str) -> None:
    """Install the X-Ray exporter and auto-instrument boto3 calls (DynamoDB, S3, SQS)."""
    global _provider
    if not enabled or _provider is not None:
        return
    import boto3
    from opentelemetry.instrumentation.botocore import BotocoreInstrumentor
    from opentelemetry.propagate import set_global_textmap
    from opentelemetry.propagators.aws import AwsXRayPropagator
    from opentelemetry.sdk.extension.aws.trace import AwsXRayIdGenerator
    from opentelemetry.sdk.resources import Resource
    from opentelemetry.sdk.trace import TracerProvider
    from opentelemetry.sdk.trace.export import BatchSpanProcessor
    from opentelemetry.sdk.trace.sampling import ParentBased, TraceIdRatioBased

    provider = TracerProvider(
        resource=Resource.create({"service.name": service_name}),
        id_generator=AwsXRayIdGenerator(),  # X-Ray trace ids start with a timestamp
        # Follow Lambda's sampling decision; without one, keep 5% of traces.
        sampler=ParentBased(root=TraceIdRatioBased(0.05)),
    )
    exporter = XRayExporter(boto3.client("xray", region_name=region), service_name)
    processor = BatchSpanProcessor(cast("SpanExporter", exporter), schedule_delay_millis=1000)
    provider.add_span_processor(processor)
    trace.set_tracer_provider(provider)
    set_global_textmap(AwsXRayPropagator())
    BotocoreInstrumentor().instrument()  # type: ignore[no-untyped-call]
    _provider = provider


def flush() -> None:
    """Export pending spans now (a frozen Lambda can't run the background exporter)."""
    if _provider is not None:
        _provider.force_flush(timeout_millis=2000)


def context_from_header(header: str | None) -> otel_context.Context | None:
    """The trace context in an X-Amzn-Trace-Id value (from Lambda, SQS or an HTTP header)."""
    if not header or _provider is None:
        return None
    from opentelemetry.propagate import extract

    return extract({TRACE_HEADER: header})


def current_header() -> str | None:
    """The current context as an X-Amzn-Trace-Id value, e.g. to put on an SQS message."""
    if _provider is None:
        return None
    from opentelemetry.propagate import inject

    carrier: dict[str, str] = {}
    inject(carrier)
    return carrier.get(TRACE_HEADER)


def lambda_context() -> otel_context.Context | None:
    """The invocation's own trace (set by Lambda when active tracing is on)."""
    return context_from_header(os.environ.get("_X_AMZN_TRACE_ID"))


@contextmanager
def attached(ctx: otel_context.Context | None) -> Iterator[None]:
    """Make ``ctx`` the parent for spans started inside the block."""
    if ctx is None:
        yield
        return
    token = otel_context.attach(ctx)
    try:
        yield
    finally:
        otel_context.detach(token)


def mark_error(current: Span, exc: BaseException) -> None:
    current.set_status(Status(StatusCode.ERROR, type(exc).__name__))


# --- Export --------------------------------------------------------------------------------------


def _xray_trace_id(trace_id: int) -> str:
    h = format(trace_id, "032x")
    return f"1-{h[:8]}-{h[8:]}"


def to_segment(span: "ReadableSpan", service_name: str) -> dict[str, Any]:
    """Convert a finished span to an X-Ray segment document.

    A span with a parent (in this process, or Lambda's own segment) becomes an independent
    subsegment under it. A span without one (e.g. a request that arrived untraced) becomes a
    top-level segment named after the service.
    """
    ctx = span.get_span_context()
    assert ctx is not None and span.start_time is not None and span.end_time is not None
    attributes: Mapping[str, Any] = span.attributes or {}
    doc: dict[str, Any] = {
        "name": _NAME_UNSAFE.sub("_", span.name)[:200] or "span",
        "id": format(ctx.span_id, "016x"),
        "trace_id": _xray_trace_id(ctx.trace_id),
        "start_time": span.start_time / 1e9,
        "end_time": span.end_time / 1e9,
    }
    if span.parent is not None:
        doc["type"] = "subsegment"
        doc["parent_id"] = format(span.parent.span_id, "016x")
    else:
        doc["name"] = service_name
        doc["origin"] = "AWS::Lambda::Function"
    if attributes.get("rpc.system") == "aws-api":
        # Show as the AWS service on the X-Ray trace map (DynamoDB, S3, SQS).
        doc["namespace"] = "aws"
        doc["name"] = str(attributes.get("rpc.service", doc["name"]))
        doc["aws"] = {"operation": attributes.get("rpc.method")}
        if table := attributes.get("aws.dynamodb.table_names"):
            doc["aws"]["table_name"] = table[0] if isinstance(table, Sequence) else table
    elif span.kind is SpanKind.CLIENT:
        doc["namespace"] = "remote"  # e.g. the OpenAI API
    if span.status.status_code is StatusCode.ERROR:
        doc["fault"] = True
    annotations = {
        _KEY_UNSAFE.sub("_", k): v
        for k, v in attributes.items()
        if isinstance(v, (str, int, float, bool)) and not k.startswith(("rpc.", "aws."))
    }
    if annotations:
        doc["annotations"] = dict(list(annotations.items())[:50])
    return doc


class XRayExporter:
    """OpenTelemetry span exporter that calls X-Ray's PutTraceSegments (no daemon/collector)."""

    def __init__(self, client: Any, service_name: str) -> None:
        self._client = client
        self._service = service_name

    def export(self, spans: Sequence["ReadableSpan"]) -> "SpanExportResult":
        from opentelemetry.instrumentation.utils import suppress_instrumentation
        from opentelemetry.sdk.trace.export import SpanExportResult

        documents = [json.dumps(to_segment(s, self._service)) for s in spans]
        try:
            # Don't trace the exporter's own AWS calls (that would trace forever).
            with suppress_instrumentation():
                for start in range(0, len(documents), 50):
                    response = self._client.put_trace_segments(
                        TraceSegmentDocuments=documents[start : start + 50]
                    )
                    if failed := response.get("UnprocessedTraceSegments"):
                        logger.warning("x-ray rejected segments", extra={"failed": failed[:3]})
        except Exception:
            logger.warning("x-ray export failed", exc_info=True)
            return SpanExportResult.FAILURE
        return SpanExportResult.SUCCESS

    def shutdown(self) -> None:
        pass

    def force_flush(self, timeout_millis: int = 30_000) -> bool:
        return True
