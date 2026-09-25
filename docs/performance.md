# Performance and load testing

**What was measured:**
- where time goes on each question;
- what limits throughput on the AWS free tier;
- what changed after fixing the biggest bottleneck.

All numbers are from 25 September 2026. Raw Locust output is in [`backend/loadtest/results/`](../backend/loadtest/results/). How to rerun everything is in [`backend/loadtest/README.md`](../backend/loadtest/README.md).

## Summary
| | Before | After |
|---|---|---|
| **DynamoDB read units per question** | 84 | **0.5** (a miss costs 84.5 once per Lambda instance per document) |
| **Question throughput allowed by prod's 15 read units per second** | ~0.18 per second (~11 a minute, for all users together) | ~30 per second (no longer the limit) |
| Time to first token on AWS | not measured | **3.0 s median**, 4.8 s max (7 questions) |
| API cold start (Lambda `Init Duration`) | 2.0–3.5 s, median 3.3 s (11 samples) | 1.9–3.2 s (3 samples, see below) |

## 1. Finding the bottleneck: local load test
**Setup:**
- Locust ran 20 simulated users for 2 minutes against the docker-compose stack (DynamoDB Local + moto).
- Each user asked a question about NIST SP 800-63B (80 pages, 148 chunks), then waited 2–5 s.
- OpenAI was replaced by the fake provider with 0.5 s per call and real-size (1,536-dim) vectors, so the test cost nothing.
- **DynamoDB Local never throttles.** So the key measurement is the read capacity each question *consumes*, which DynamoDB reports per query (`ReturnConsumedCapacity`) and the API logs as `ReadUnits`.

| Local, 20 users, 2 min | Questions | Failures | Time to first token (median / p95) | Read units per question (median) |
|---|---|---|---|---|
| Cache off | 384 | 0 | 1.53 s / 1.6 s | **84** |
| Cache on | 405 | 0 | 1.51 s / 1.6 s | **0.5** (401 hits, 4 misses) |

**Why 84:**
- Retrieval is exact vector search in the Lambda, so every question read every chunk of the selected documents.
- Each chunk is about 4.7 KB: the text plus a 3 KB float16 vector.
- 148 chunks is about 700 KB. At 0.5 read units per 4 KB (eventually consistent reads), that's about 84 units.
- Prod's table has 15 read units per second (dev + prod must stay within the free 25). So one question used 5.6 seconds' worth of capacity.
- Local latency barely changes, because DynamoDB Local is in-process-fast. On AWS, the same reads get throttled once burst capacity runs out.

**Fix: an in-Lambda LRU cache** of decoded chunks per (user, document), capped at 20,000 chunks.
- **No invalidation is needed.** A ready document's chunks never change; re-uploading creates a new document id. A deleted document drops out of the "ready" list that every search starts from.
- **Tenants never share entries,** because keys include the user id.
- **Scope of the benefit.** The cache lives only as long as the Lambda instance, so each new instance pays the 84-unit read once per document it serves.

## 2. On AWS (dev, real OpenAI)
**Setup:**
- 2 users for 60 seconds against the dev Function URL, with real OpenAI.
- Kept small because dev allows each account 100k tokens a day.
- Cost about $0.004 in OpenAI tokens, and $0 on AWS.

**Results:**
- 7 questions, **0 failures**.
- Time to first token: median **3.0 s**, max **4.8 s**.
- Server-side, the first question on each of the 2 Lambda instances read **84.5 units** (cache miss). Every later question read **0.5**.
- Ingesting the PDF (80 pages, 148 chunks) took **14.9 s** in the worker.

### Where the time goes: one traced question (X-Ray)
| Step | Time |
|---|---|
| 4 DynamoDB calls (rate limit, quotas, document list) | ~4 ms each |
| Embed the question (OpenAI) | 219 ms |
| Vector search + BM25 (from the cache) | 1 ms |
| **Rerank 20 candidates (OpenAI, `reasoning_effort=none`)** | **2,130 ms** |
| Stream the answer (OpenAI) | 2,128 ms |
| Save the turn, record usage (DynamoDB) | ~15 ms |

**With DynamoDB fixed, the next bottleneck is the LLM reranker: about 90% of the time before the first word.** The evaluation found it worth +18 points Recall@1 and +5 points correctness ([evaluation.md](evaluation.md)), so it shouldn't simply be removed. Options to measure with the eval harness next:
- 10 candidates instead of 20;
- shorter passages sent to the reranker (400 characters instead of 800);
- rerank only when the top retrieval scores are close.

## 3. Cold starts
**What was tried:**
- pypdf is imported only when a PDF is parsed (only the worker does that).
- The embedding tokenizer is loaded only when an input might exceed a token limit.
- The API's memory went from 1,024 MB to 2,048 MB. Lambda's CPU share grows with memory, and 2,048 MB is about 1.2 vCPUs.

**What startup is made of.** Profiled inside AWS's `public.ecr.aws/lambda/python:3.13` image, limited to 1.16 CPUs:

| Step | Time |
|---|---|
| fastapi + uvicorn | ~0.2 s |
| openai SDK | ~0.2 s |
| numpy | ~0.15 s |
| boto3 | ~0.06 s |
| OpenTelemetry (new) | ~0.04 s |
| rest of the app | ~0.12 s |
| building services (clients, tokenizer) | ~0.2 s |
| **App code in total** | **~1.0 s** |

**Result.** Lambda reports 1.9–3.2 s for the whole init phase, so 1–2 s is the platform: sandbox start, the Web Adapter extension, the Python runtime, and first reads of the 140 MB layer. Three samples after the change (1.9, 3.0, 3.2 s) against a median of 3.3 s before is too few to call a clear improvement.

**Options that would help, and what they cost:**
| Option | Effect | Cost |
|---|---|---|
| Keep-warm ping (EventBridge Scheduler every 5 minutes) | Keeps one instance warm, so most single visitors never see a cold start | Free |
| SnapStart for Python | Restores from a snapshot | Billed per cached snapshot and per restore: not free |
| Provisioned concurrency | No cold starts | Billed per hour: not free |

## 4. Capacity on the free tier (prod)
| Limit | Value | Questions it allows |
|---|---|---|
| DynamoDB reads (15 units/s) | 0.5 units per cached question | ~30/s (was ~0.18/s) |
| Lambda concurrency (account limit 10, shared by API and worker) | ~4.5 s per streamed answer | ~2 answers/s at full concurrency |
| Per-user rate limit | 20 questions a minute | per user |
| **Service-wide daily cap** | 1M tokens a day | **~200 questions a day** (about $0.12 of OpenAI) |

The binding constraints are now the daily cap, deliberately (it bounds the OpenAI bill), and Lambda concurrency.

## 5. Observability now in place
- **Traces.** Each request, including the full stream, plus DynamoDB/S3/SQS calls, OpenAI calls, vector search and rerank go to X-Ray. The worker continues the API's trace through SQS's `AWSTraceHeader`.
  - The code uses OpenTelemetry. A small exporter calls `PutTraceSegments`, because the X-Ray SDK reaches end of support in February 2027 and the OpenTelemetry Lambda layer conflicts with the Lambda Web Adapter.
- **Metrics (prod).** 5 custom metrics via Embedded Metric Format: `TimeToFirstTokenMs`, `LatencyMs`, `CostUSD`, `ReadUnits`, `IngestSeconds`.
- **Dashboard.** `documind-prod` shows those metrics next to Lambda, DynamoDB and SQS metrics.
- **Alarms (6 of the 10 free per account):**
  - API errors;
  - API throttles;
  - ingestion dead letters;
  - slow first token (p95 over 8 s);
  - DynamoDB read throttling;
  - daily OpenAI spend over $0.50.
