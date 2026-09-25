# Architecture

**Components:**
- a static web app;
- a streaming API on Lambda;
- an ingestion worker behind a queue;
- one DynamoDB table.

Everything is in Terraform ([`infra/`](../infra/)) and deployed by GitHub Actions through OIDC. Each choice is explained in the [ADRs](adr/).

## System
```mermaid
flowchart LR
    user(["Browser"])

    subgraph edge["Edge"]
        cf["CloudFront<br/>HTTPS + security headers"]
        site[("S3<br/>static Next.js site<br/>+ config.json")]
    end

    subgraph auth["Identity"]
        cognito["Cognito user pool<br/>SRP sign-in, JWTs"]
    end

    subgraph app["API (Lambda, arm64)"]
        url["Function URL<br/>response streaming"]
        api["FastAPI via Lambda Web Adapter<br/>auth, limits, retrieval, chat"]
        cache[["in-memory chunk cache"]]
    end

    subgraph data["Data"]
        ddb[("DynamoDB, one table<br/>documents, chunks + vectors,<br/>chats, usage, rate limits")]
        uploads[("S3 uploads<br/>PDFs deleted after indexing")]
        queue["SQS ingest queue<br/>+ dead-letter queue"]
    end

    worker["Worker Lambda<br/>parse, chunk, embed, store"]
    openai["OpenAI API<br/>embeddings, rerank, answers"]
    ssm["SSM Parameter Store<br/>OpenAI key"]
    obs["CloudWatch + X-Ray<br/>logs, metrics, traces, alarms"]

    user --> cf --> site
    user -- "sign in" --> cognito
    user -- "questions (SSE stream)" --> url --> api
    user -- "presigned POST" --> uploads
    api --- cache
    api --> ddb
    api --> queue --> worker
    worker --> uploads
    worker --> ddb
    api --> openai
    worker --> openai
    api -. "key at cold start" .-> ssm
    worker -.-> ssm
    api -.-> obs
    worker -.-> obs
```

## Upload and ingestion
```mermaid
sequenceDiagram
    autonumber
    participant B as Browser
    participant A as API Lambda
    participant S3 as S3 uploads
    participant Q as SQS
    participant W as Worker Lambda
    participant O as OpenAI
    participant D as DynamoDB

    B->>A: POST /v1/documents (name, size)
    A->>D: document = awaiting_upload (TTL 1 day)
    A-->>B: presigned POST (20 MB limit in the policy)
    B->>S3: upload the PDF directly
    B->>A: POST /v1/documents/{id}/complete
    A->>S3: HEAD: check it exists and its real size
    A->>D: status = pending
    A->>Q: job + trace context (AWSTraceHeader)
    Q->>W: one message per invocation (max 2 at once)
    W->>D: status = processing (conditional)
    W->>S3: read the PDF
    W->>W: parse pages, strip headers and TOC, structured chunks
    W->>O: embed chunks (batched)
    W->>D: chunks + float16 vectors (idempotent keys)
    W->>D: status = ready
    W->>S3: delete the PDF
    loop until ready or failed
        B->>A: GET /v1/documents/{id}
    end
    Note over Q,W: Failure: retried 3 times, then the dead-letter queue (alarm)
```

## Asking a question
```mermaid
sequenceDiagram
    autonumber
    participant B as Browser
    participant A as API Lambda
    participant D as DynamoDB
    participant O as OpenAI

    B->>A: POST /v1/query/stream (question, chat id) + JWT
    A->>A: verify the Cognito JWT (cached public keys)
    A->>D: rate limit, user quota, service-wide cap
    A->>D: chat history, document list
    A->>O: embed the question (~0.2 s)
    A->>A: vector + BM25 search, RRF (cache hit ~1 ms)
    A->>O: rerank the top 20 (~2 s)
    A-->>B: event: sources (citations)
    A->>O: answer from the top 5 chunks, streamed
    loop tokens
        A-->>B: event: token
    end
    A->>D: add usage (atomic), save both messages
    A-->>B: event: done (usage, context bar, quota bar)
    opt first answer in a chat
        A->>O: write a 3-7 word title
        A-->>B: event: title
    end
```

## Data model (one DynamoDB table)
Every user-owned item is under the user's partition, so isolation is structural: no repository method can read without a user id.

| Item | PK | SK | Notes |
|---|---|---|---|
| Document | `USER#<id>` | `DOC#<doc>` | Status, pages, chunks; `expires_at` while awaiting upload |
| Chunk | `USER#<id>` | `CHUNK#<doc>#<index:05d>` | Text, page, section context, float16 vector (~4.7 KB) |
| Conversation | `USER#<id>` | `CONV#<chat>` | Title, attached documents, message counter, running summary |
| Message | `USER#<id>` | `MSG#<chat>#<index:06d>` | Role, content, citations |
| Rate-limit window | `USER#<id>` | `RATE#<bucket>#<window>` | Fixed-window counter, TTL |
| Daily usage | `USER#<id>` | `USAGE#<YYYY-MM-DD>` | Tokens and requests; TTL after 35 days |
| Service-wide usage | `SERVICE` | `USAGE#<YYYY-MM-DD>` | All users together, for the global cap |

**Throughput:**
- **Capacity.** Provisioned: prod 15/15, dev 5/5, which fits the free 25/25.
- **Read costs per question:**
  - the document list and conversation queries are small;
  - reading a document's chunks costs ~0.5 units per 4 KB, e.g. 84 units for an 80-page PDF;
  - so the API caches decoded chunks per instance.

## Code layout ([`backend/src/documind/`](../backend/src/documind/))
| Package | Responsibility |
|---|---|
| `api/` | FastAPI app, routes, request/response schemas, error envelope, request middleware (request id, metrics, tracing) |
| `services/` | Use cases: document upload, ingestion, retrieval + answering (`query.py`), chat turns (`chat.py`), context management, reranking, titles, usage/quotas |
| `repositories/` | Storage behind small protocols (`base.py`): DynamoDB, S3, SQS, plus in-memory versions for tests |
| `providers/` | OpenAI and fake providers behind `EmbeddingProvider` / `LLMProvider` |
| `ingestion/` | PDF parsing, structure detection, chunking |
| `core/` | Settings, auth (Cognito/local JWT), the dependency container, logging, metrics, tracing, errors |

**Entry points:**
- `api/main.py`: the API;
- `lambda_worker.py`: the SQS-triggered worker;
- `worker.py`: a long-polling worker for docker-compose.
