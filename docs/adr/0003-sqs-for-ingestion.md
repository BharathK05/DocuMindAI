# 3. SQS between upload and ingestion

- **Status:** accepted (2026-09-24)

## Context
Ingesting a PDF means parsing, chunking, embedding and storing it, and takes 5–30 s (80 pages took 14.9 s on AWS). It calls OpenAI, which can rate-limit or fail. Uploads must not block a request for that long. A failure must not lose the document silently, and a burst of uploads must not exhaust the account's 10 concurrent executions.

## Decision
1. **Direct upload.** The browser uploads the PDF **directly to S3** with a presigned POST. A size policy in the form limits it to 20 MB, and the API re-checks the size, because some S3 emulators don't enforce the policy.
2. **Queue.** `POST /documents/{id}/complete` puts a job on **SQS**, and the worker Lambda consumes it:
   - `batch_size = 1`: one PDF per invocation.
   - `maximum_concurrency = 2`: at most 2 PDFs at once.
   - `ReportBatchItemFailures`: only failed messages are retried.
3. **Retries.** A message is retried 3 times, then goes to a **dead-letter queue**. A CloudWatch alarm emails when the DLQ is not empty.
4. **Idempotence.** Chunk keys are deterministic, so a retried job overwrites rather than duplicating. The document's status moves `pending → processing → ready | failed` with conditional updates.
5. **Tracing.** The job carries the API's trace context (`AWSTraceHeader`), so the upload and its ingestion show as one trace in X-Ray.

## Consequences
**Good:**
- **Fast upload requests,** with retries, back-pressure and a DLQ, and no extra code for them.
- **$0.** SQS is free up to 1M requests a month.
- **Bursts are absorbed.** They queue instead of throttling the API.

**Bad:**
- **At-least-once delivery.** Hence idempotent ingestion and conditional status updates.
- **Polling.** The client polls for status (`GET /documents/{id}`); there's no push notification.

## Alternatives considered
| Option | Why not |
|---|---|
| Ingest inside the upload request | Slow requests, lost work on timeout, no retries |
| S3 event notification straight to Lambda | Fewer moving parts, but the size/ownership check in `complete` would be skipped, and retry/DLQ control is weaker |
| EventBridge | Adds routing we don't need; SQS gives batching and concurrency control |
| Step Functions | Useful for multi-step workflows with branching; ingestion is one step (~25 free state transitions per document would add up) |

## Revisit when
- Ingestion grows multiple independent stages, such as OCR, summaries or thumbnails. Step Functions then fits better.
- Users need a push notification when a document is ready: a WebSocket or SSE status channel.
