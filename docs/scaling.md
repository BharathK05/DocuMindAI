# Design tradeoffs and scaling

**Scope:**
- what limits DocuMind today;
- what breaks first at 10× and 100× the load;
- what I'd change, and pay for, at each stage.

**Sources.** Current numbers are measured ([performance.md](performance.md), [evaluation.md](evaluation.md)). Prices are approximate us-east-1 list prices, only to compare orders of magnitude; check the AWS pricing pages before deciding.

## Where it stands today (free tier, measured)
| Resource | Limit | What it allows |
|---|---|---|
| **Service-wide daily cap** (deliberate) | 1M tokens a day | **~200 questions a day** (~$0.12 of OpenAI) |
| Lambda concurrency (account limit 10, API and worker share it) | ~4.5 s per streamed answer | ~2 answers a second at full concurrency |
| DynamoDB reads (prod 15 RCU) | 0.5 units per question when cached; 84 on a cache miss (80-page PDF) | ~30 a second cached; bursts of new Lambda instances can throttle |
| Ingestion (SQS → worker, `maximum_concurrency = 2`) | ~15 s per 80-page PDF | ~8 PDFs a minute |
| Cognito | 10k monthly active users | 10k users |
| OpenAI | ~$0.0006 per question; rate limits depend on the account's usage tier | Bounded by the caps above |

**Cost per question at scale:** OpenAI ~$0.0006, and AWS ~$0 inside the free tier. So **the bill is OpenAI's long before it's AWS's.**

## At 10× (~100 daily users, ~2,000 questions a day, peaks of ~5 questions a second)
| What breaks first | Why | Change | Cost |
|---|---|---|---|
| **The service-wide cap** turns people away | It's set to ~200 questions a day on purpose | Raise `global_daily_token_quota`; keep the per-user quota and the daily-cost alarm | OpenAI ≈ $1.20 a day |
| **Lambda concurrency** (10) throttles at ~2 answers a second | Each streaming answer holds an instance for ~4.5 s, mostly waiting on OpenAI | Ask AWS for a higher concurrency quota (free; typically 1,000) | Lambda beyond 400k GB-s ≈ $0.0000133 per GB-s (arm), a few dollars a month |
| **DynamoDB throttling on cache misses** | More instances means more cold caches; each miss reads the whole document (84 units) at 15 units a second | Store each document's vectors as **one S3 object** (float16 matrix): one GET instead of ~84 read units, and keep text in DynamoDB; or switch the table to on-demand | S3 GETs ≈ $0.0004 per 1,000; on-demand reads ≈ $0.125 per million |
| **More cold starts** | Scale-out creates instances | Keep-warm ping (free) for the first instance; **provisioned concurrency** for peak hours if cold starts show in p95 | Provisioned concurrency is billed per hour |
| **Reranker latency** (~2.1 s of the wait before the first word) and **OpenAI rate limits** | ~5 questions a second × ~5k tokens is ~1.5M tokens a minute | Fewer or shorter rerank candidates (verified with the eval harness); cache repeated questions in DynamoDB with TTL; a higher OpenAI usage tier | Mostly OpenAI tier limits, not dollars |
| **Ingestion queue delay** | `maximum_concurrency = 2` | Raise it, while watching OpenAI embedding rate limits; use the Batch API for bulk imports | Small |

At 10× the architecture stays the same. It's configuration, quota requests, and moving vectors off DynamoDB.

## At 100× (~1,000 daily users, ~20,000 questions a day, peaks of 20–50 questions a second; larger libraries per user)
| What breaks | Why | Move to | Tradeoff |
|---|---|---|---|
| **In-Lambda exact vector search** | A user with 1,000 documents has ~150k chunks, ~1 GB of float32 vectors: too slow to load or scan per question, too big for the cache | An **ANN index**: **S3 Vectors** (serverless, pay per use), **OpenSearch Serverless** (vector and BM25 in one engine), or **Aurora PostgreSQL + pgvector** (HNSW index + `tsvector` for BM25, plus relational data) | Approximate search needs recall monitoring (the eval harness already measures recall@k). OpenSearch and Aurora have always-on minimum capacity. ADR 1 keeps this a one-class swap behind `VectorStore` |
| **Lambda as the API tier** | Streaming answers are I/O-bound: Lambda bills the whole wait, one request per instance. At tens of concurrent streams, one async process could serve them all | **Containers** (ECS Fargate or App Runner, behind an ALB), with the same FastAPI app and Dockerfile; keep Lambda for the ingestion worker | ALB ≈ $16+ a month plus load-balancer capacity units (LCUs), and tasks run 24/7; no cold starts, much cheaper per question at steady load |
| **DynamoDB hot partitions** | All of a user's data shares one partition key; a partition serves ≤ 3,000 RCU / 1,000 WCU. The document list is read on every question | Keep chunk text and vectors in the vector store; shard very large tenants' chunk keys (`USER#<id>#<shard>`); cache the document list per instance; on-demand capacity | More key-design complexity |
| **Answer latency and OpenAI cost** | 20k questions a day × $0.0006 ≈ $12 a day, and tokens-per-minute limits | Semantic cache for repeated questions; a cheaper model or distillation for reranking, or a cross-encoder in a container; prompt caching for the fixed system prompt | Cache freshness; quality must be re-measured with the eval harness |
| **Observability cost** | Beyond 100k traces a month (~$5 per million), 5 GB of logs, 10 custom metrics | Lower trace sampling; log level `WARNING` for request logs; keep EMF metrics few and aggregated | Less detail per request |
| **Abuse and security** | Public sign-up, per-user quotas only | **AWS WAF** on CloudFront (rate-based rules, bot control), CAPTCHA at sign-up, per-organisation quotas | ~$5 a month plus per rule and per request |
| **Ingestion of scanned PDFs, big batches** | No OCR; one PDF per invocation | **Step Functions** pipeline: Textract OCR → chunk → embed (Batch API) → index | Textract is billed per page |
| **Availability** | Single region | DynamoDB global tables, and a second region behind CloudFront origin failover | Roughly doubles infrastructure |

## Tradeoffs I'd defend in an interview
- **Exact search now, ANN later.** At hundreds to thousands of chunks per user, exact search is cheap, has perfect recall, and needs no infrastructure. The switch point is measurable (p95 search time, read units per question), and the `VectorStore` interface keeps the migration contained.
- **Lambda now, containers later.** Lambda wins while traffic is idle most of the day ($0). It loses once many concurrent streaming answers keep instances busy, because each instance serves one request while waiting on OpenAI.
- **Provisioned DynamoDB.** It throttles instead of billing: the right failure mode for a $0 project, and the wrong one for paying users. Switch to on-demand, or autoscaling, when throughput matters more than a guaranteed $0.
- **Caps are features.** Per-user quotas, a service-wide cap and a spend alarm make the worst case a polite `429`, not an invoice. At scale they become per-plan limits.
- **Measure before optimising.** The load test found the real bottleneck (read units per question). Tracing then showed the next one (the reranker), which a guess would likely have missed.
