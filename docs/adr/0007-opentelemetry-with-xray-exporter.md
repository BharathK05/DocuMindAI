# 7. Tracing: OpenTelemetry in code, exported to X-Ray by a small custom exporter

- **Status:** accepted (2026-09-25)

## Context
One question crosses the API Lambda, DynamoDB, OpenAI (embed, rerank, answer), and for uploads SQS and the worker Lambda. Finding the slow step needs distributed tracing. Constraints:
- **X-Ray is free** up to 100k traces a month.
- **The AWS X-Ray SDKs** entered maintenance mode in February 2026 and reach **end of support in February 2027.** AWS recommends OpenTelemetry.
- **The AWS OpenTelemetry Lambda layer can't wrap the API.** It starts through `AWS_LAMBDA_EXEC_WRAPPER`, which the Lambda Web Adapter already uses (ADR 2).
- **Streamed responses outlive the request handler.** So a request's span must end when the body finishes, not when headers are sent.

## Decision
- **Instrumentation.** Code uses the vendor-neutral **OpenTelemetry API** (`core/tracing.py`):
  - one span per HTTP request, kept open until the stream ends;
  - spans for the OpenAI calls (with a "first token" event), vector search and rerank;
  - boto3 calls instrumented automatically (DynamoDB, S3, SQS).
- **Export.** A ~100-line `XRayExporter` converts finished spans to X-Ray segment documents and calls **`PutTraceSegments`** through boto3. There's no daemon or collector, and it's batched in the background.
- **Parenting.** Spans hang under Lambda's own trace (active tracing):
  - the API reads it from the `X-Amzn-Trace-Id` request header, which the Web Adapter forwards;
  - the worker continues the API's trace from the SQS message's `AWSTraceHeader`.
- **Sampling** follows Lambda's decision. Requests that arrive without a trace keep 5%.
- **Metrics.** Kept separate from tracing: CloudWatch **Embedded Metric Format** log lines. They're prod only, because each metric name counts toward the 10 free custom metrics.

## Consequences
**Good:**
- **One trace shows the whole question with timings.** The first production trace immediately showed the reranker taking ~2.1 s of ~2.4 s before the first word.
- **Portable instrumentation.** Moving to an OpenTelemetry collector or another backend changes only the exporter.
- **Small footprint.** ~0.8 MB of dependencies and ~35 ms of import time.

**Bad:**
- **We own a small exporter:** the segment format, batching and error handling. It's covered by unit tests.
- **Export can be delayed or lost.** It runs in a background thread; a frozen Lambda delays export, and spans can be lost if an instance is shut down before flushing. The worker flushes explicitly after each invocation.

## Alternatives considered
| Option | Why not |
|---|---|
| AWS X-Ray SDK for Python | End of support February 2027 |
| AWS OpenTelemetry Lambda layer (collector + auto-instrumentation) | Conflicts with the Web Adapter's exec wrapper; heavier cold start |
| Logs only (timings in JSON lines) | No cross-service view; still used for per-request fields |
