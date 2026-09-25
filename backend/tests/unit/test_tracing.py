"""OpenTelemetry spans → X-Ray segment documents, and the exporter's batching."""

import json
from typing import Any

from opentelemetry.sdk.extension.aws.trace import AwsXRayIdGenerator
from opentelemetry.sdk.trace import ReadableSpan, TracerProvider
from opentelemetry.sdk.trace.export import SimpleSpanProcessor, SpanExportResult
from opentelemetry.sdk.trace.export.in_memory_span_exporter import InMemorySpanExporter
from opentelemetry.trace import SpanKind, Status, StatusCode

from documind.core import tracing


def finished_spans() -> list[ReadableSpan]:
    memory = InMemorySpanExporter()
    provider = TracerProvider(id_generator=AwsXRayIdGenerator())
    provider.add_span_processor(SimpleSpanProcessor(memory))
    tracer = provider.get_tracer("test")
    with tracer.start_as_current_span("POST /v1/query/{id}", kind=SpanKind.SERVER) as root:
        root.set_attribute("request_id", "abc")
        with tracer.start_as_current_span(
            "DynamoDB.Query",
            kind=SpanKind.CLIENT,
            attributes={
                "rpc.system": "aws-api",
                "rpc.service": "DynamoDB",
                "rpc.method": "Query",
                "aws.dynamodb.table_names": ("documind-prod-data",),
            },
        ):
            pass
        with tracer.start_as_current_span("OpenAI chat", kind=SpanKind.CLIENT) as llm:
            llm.set_attribute("model", "gpt-6-luna")
            llm.set_status(Status(StatusCode.ERROR))
    return list(memory.get_finished_spans())


def by_name(docs: list[dict[str, Any]]) -> dict[str, dict[str, Any]]:
    return {d["name"]: d for d in docs}


def test_spans_become_a_segment_tree() -> None:
    docs = by_name([tracing.to_segment(s, "documind-api") for s in finished_spans()])
    root, dynamo, llm = docs["documind-api"], docs["DynamoDB"], docs["OpenAI chat"]

    assert root["trace_id"].startswith("1-") and len(root["trace_id"]) == 35
    assert "type" not in root and root["origin"] == "AWS::Lambda::Function"
    assert root["annotations"] == {"request_id": "abc"}
    assert root["end_time"] >= root["start_time"]

    assert dynamo["type"] == "subsegment" and dynamo["parent_id"] == root["id"]
    assert dynamo["namespace"] == "aws"
    assert dynamo["aws"] == {"operation": "Query", "table_name": "documind-prod-data"}
    assert "annotations" not in dynamo  # AWS attributes aren't copied as annotations

    assert llm["namespace"] == "remote" and llm["fault"] is True
    assert llm["annotations"] == {"model": "gpt-6-luna"}
    assert {d["trace_id"] for d in docs.values()} == {root["trace_id"]}


class FakeXRay:
    def __init__(self, fail: bool = False) -> None:
        self.calls: list[list[str]] = []
        self.fail = fail

    def put_trace_segments(self, TraceSegmentDocuments: list[str]) -> dict[str, Any]:
        if self.fail:
            raise RuntimeError("throttled")
        self.calls.append(TraceSegmentDocuments)
        return {"UnprocessedTraceSegments": []}


def test_exporter_batches_documents_and_survives_errors() -> None:
    spans = finished_spans() * 20  # 60 spans → batches of 50 + 10
    client = FakeXRay()
    assert tracing.XRayExporter(client, "svc").export(spans) is SpanExportResult.SUCCESS
    assert [len(c) for c in client.calls] == [50, 10]
    assert json.loads(client.calls[0][0])["trace_id"].startswith("1-")
    failing = tracing.XRayExporter(FakeXRay(fail=True), "svc")
    assert failing.export(spans) is SpanExportResult.FAILURE  # logged, never raised


def test_everything_is_a_no_op_when_tracing_is_off() -> None:
    assert tracing.current_header() is None
    assert tracing.context_from_header("Root=1-5759e988-bd862e3fe1be46a994272793") is None
    with tracing.attached(None), tracing.span("work") as current:
        assert not current.is_recording()
    tracing.flush()  # nothing to flush, no error
