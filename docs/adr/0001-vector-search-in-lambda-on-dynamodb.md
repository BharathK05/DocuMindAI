# 1. Exact vector search inside the Lambda, with chunks stored in DynamoDB

- **Status:** accepted (2026-09-24). A per-instance cache was added on 2026-09-25.
- **Deciders:** project owner. Measured with the eval harness and a load test.

## Context
Every question needs the chunks most similar to it. The usual answers are a vector database: pgvector on Postgres, OpenSearch, Pinecone, or S3 Vectors. The constraints here:
- **$0 a month.**
- **Per-user isolation.**
- **Small corpora:** a user uploads tens of PDFs, i.e. hundreds to a few thousand chunks.
- **Hybrid retrieval:** BM25 as well as embeddings, because the eval showed exact identifiers like `GV.SC-04` need keyword matching.

Always-on vector databases cost money even when idle:
- **RDS/Aurora with pgvector:** an instance-hour or capacity-unit minimum.
- **OpenSearch Serverless:** a minimum number of OCUs (OpenSearch Compute Units).
- **Hosted vector databases:** a paid tier beyond their free quotas.

## Decision
- **Storage.** Chunks, with their text, page, section context and a **float16** vector, are stored in the single DynamoDB table under the user's partition (`PK = USER#<id>`, `SK = CHUNK#<doc>#<idx>`).
- **Search.** At question time the API reads the selected documents' chunks and ranks them **exactly** in NumPy (cosine similarity) together with BM25, merged by reciprocal rank fusion.
- **Cache.** Decoded chunks are kept per (user, document) in an LRU cache in the Lambda instance. A ready document's chunks never change, so the cache needs no invalidation.

## Consequences
**Good:**
- **$0,** and no extra service to run or secure.
- **Exact search.** No approximate-index recall loss, and no index tuning.
- **Isolation by construction.** A query can only read one user's partition.
- **Easy to add ranking features.** Hybrid search and reranking live in plain Python.
- **Measured cost.** One question on an 80-page PDF used **84 read units uncached, 0.5 cached** ([performance.md](../performance.md)).

**Bad:**
- **Cost grows with corpus size.** Search cost is linear in the chunks searched: CPU per question, and a DynamoDB read on every cache miss. Fine for thousands of chunks per user, not millions.
- **The cache is per instance.** Every new Lambda instance pays the full read once per document it serves.
- **Chunks are copied into the Lambda's memory.** The cache is capped at 20,000 chunks (about 150 MB decoded) to bound it.

## Alternatives considered
| Option | Why not (now) |
|---|---|
| pgvector on RDS/Aurora | Hourly minimum and a VPC; overkill for thousands of vectors |
| OpenSearch Serverless | Minimum capacity is billed around the clock |
| Pinecone / hosted vector DBs | Another vendor, keys and data location; free tiers have limits |
| S3 Vectors | Cheap, pay-per-use, and the best next step; but no BM25, so keyword search would need a second path |
| Precomputed index in the Lambda package | Documents are uploaded at runtime, per user |

## Revisit when
- Users routinely search more than ~20k chunks per question; or
- p95 vector-search time passes ~200 ms; or
- cache-miss reads cause DynamoDB throttling.

The code keeps this swap cheap: search sits behind the `VectorStore` protocol (`repositories/base.py`), so a pgvector, OpenSearch or S3 Vectors implementation would replace one class. See [scaling.md](../scaling.md).
