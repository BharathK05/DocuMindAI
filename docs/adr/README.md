# Architecture Decision Records

Short records of the choices that shape DocuMind. Each one covers the context, the decision, its consequences, the alternatives, and when to revisit it. Numbers come from [evaluation.md](../evaluation.md) and [performance.md](../performance.md).

| # | Decision | In one line |
|---|---|---|
| [1](0001-vector-search-in-lambda-on-dynamodb.md) | Exact vector search in Lambda, chunks in DynamoDB | $0 and exact; fine for thousands of chunks per user; an LRU cache cut reads 84 → 0.5 units per question |
| [2](0002-serverless-lambda-function-urls.md) | Lambda + Function URLs + Lambda Web Adapter | No idle cost, native streaming, unmodified FastAPI; the price is 2–3 s cold starts |
| [3](0003-sqs-for-ingestion.md) | SQS between upload and ingestion | Retries, a dead-letter queue and back-pressure for free; idempotent, at-least-once processing |
| [4](0004-chunking-and-retrieval-pipeline.md) | Structured chunks, hybrid search, LLM rerank | Correctness 0.78 → 0.96, Recall@1 → 0.80; the reranker is now the main latency |
| [5](0005-designing-for-zero-dollars.md) | Designing for a $0 AWS bill | Always-free services only, provisioned DynamoDB, bounded fan-out, spend caps and alarms |
| [6](0006-llm-provider-interface.md) | LLM provider behind an interface | Models and prices from config; a fake provider for tests and load tests |
| [7](0007-opentelemetry-with-xray-exporter.md) | OpenTelemetry → X-Ray via a small exporter | X-Ray SDK is end-of-life in 2027; the OpenTelemetry layer conflicts with the Web Adapter |
| [8](0008-static-web-app-on-cloudfront.md) | Static Next.js on S3 + CloudFront | One build for every environment via runtime `config.json`; Lighthouse 100 |
| [9](0009-server-side-conversations-and-quotas.md) | Server-side history, context budget, quotas | History can't be forged; 16k-token budget with summaries; check-then-charge caps |
