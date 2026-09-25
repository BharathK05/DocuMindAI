# DocuMindAI → Production-Grade Upgrade (Claude Code Prompt)

You are a senior software engineer helping me turn **DocuMindAI** from a prototype into a production-grade, scalable system that I can confidently defend in Google SDE interviews (system design + engineering depth). I'm a CS undergrad, so explain important tradeoffs briefly as you go.

## Current project
DocuMindAI is a RAG document intelligence platform for conversational Q&A over complex PDFs.
- Current stack: Python, Google Gemini (LLM + embeddings), which I am replacing with the OpenAI API, LangChain, ChromaDB (local), Gradio UI.
- Current pipeline: PDF upload → chunking → embedding → indexing in ChromaDB → semantic search → answer generation.
- Target hosting: **AWS, using only free services** (see the Free-tier constraint section).

## How I want you to work
1. **Audit first, change nothing yet.** Read the whole codebase and give me a short report: current structure, how data flows, bugs, code smells, missing error handling, security issues, and anything that won't scale.
2. **Propose a phased plan** based on the phases below, adjusted to what you found. Wait for my approval before starting each phase.
3. **Work incrementally.** Small, focused commits with clear messages. Keep the app runnable after every phase. Never delete working functionality without telling me.
4. **Ask before** adding any AWS resource that is not in the free tier, changing the LLM provider, or making large architectural changes not in this plan.
5. At the end of each phase, summarize what changed, why, and how to run/test it.

## Free-tier constraint (hard requirement)
I will only use **free AWS services**. The whole system must run at (or extremely close to) **$0/month** on AWS.
- Before provisioning anything, **verify each service against the current AWS Free Tier page** (the Free Tier changed for accounts created after July 15, 2025 to a credit-based model plus "always free" services). Prefer **always-free** allowances over anything that only runs on credits or a 12-month trial.
- **Never** create these (they cost money even when idle): NAT Gateways, Application/Network Load Balancers, RDS, Aurora (unless its free allowance is confirmed), ElastiCache, ECS Fargate, EKS, OpenSearch, Secrets Manager secrets, Elastic IPs, VPC interface endpoints, or anything running 24/7.
- No VPC needed: Lambda runs outside a VPC so no NAT is required.
- If something unavoidably costs money (e.g. a few MB of S3 storage), tell me the expected cost (it should be cents) and wait for my approval.
- Stay within free-tier limits by design: bounded concurrency, small memory sizes, log retention of 7 days, a small number of custom CloudWatch metrics and alarms.
- In Terraform, create an **AWS Budgets alert at $1** and a **free-tier usage alert** so I'm emailed before anything is billed.
- The OpenAI API is billed separately by OpenAI, not AWS; keep the token quotas in place.

## Target architecture (AWS, free-tier serverless)
- **Backend:** FastAPI (async), clean layered structure (api / services / repositories / core config), Pydantic models, full type hints. Deployed to **AWS Lambda** using **Lambda Function URLs** (free, no API Gateway needed) via the AWS Lambda Web Adapter or Mangum. Enable **response streaming** so chat answers stream. Deploy as zip packages + Lambda layers (not container images, to avoid ECR storage costs); keep dependencies lean (avoid heavy LangChain extras if they blow the package size).
- **Frontend:** Next.js (static export) with a landing page and chat app, following the Design & theme section below, hosted on **AWS Amplify Hosting** within its free allowance (or CloudFront's always-free tier). Keep Gradio only as an optional internal demo.
- **File storage:** Minimise S3: PDFs go to S3 only during ingestion and are deleted after processing (or kept with a short lifecycle rule), so storage stays near zero. Presigned URLs for uploads.
- **Async ingestion:** **SQS** queue (always free up to 1M requests/month) triggering an **ingestion Lambda** for parsing, chunking, and embedding, with job status tracking (pending / processing / done / failed) and a dead-letter queue.
- **Vector + metadata store:** **DynamoDB** (always free: 25 GB storage) for users, documents, chunks, embeddings, jobs, and chat history, with single-table design and per-user partition keys. At this project's scale, do **in-Lambda vector search** (NumPy cosine similarity over the user's chunk embeddings, plus BM25 for hybrid search), with embeddings stored compactly (float16/binary). Put the vector store behind a `VectorStore` interface so it can later swap to pgvector, OpenSearch, or S3 Vectors when scale demands it; document that tradeoff in an ADR.
- **Cache:** DynamoDB with TTL (no Redis) for repeated-query and embedding caching.
- **Auth:** Amazon Cognito user pools within the free MAU allowance (JWT for local dev), with strict per-user document isolation in every query.
- **Secrets/config:** **SSM Parameter Store standard parameters** (free, SecureString) for `OPENAI_API_KEY` and config; `.env` only for local dev, never committed.
- **Observability:** Structured JSON logging to CloudWatch Logs (7-day retention), AWS X-Ray / OpenTelemetry tracing within the free trace allowance, and a few CloudWatch metrics and alarms (p95 latency, error rate, tokens and cost per query) staying under the free limits.
- **Infrastructure as Code:** **Terraform only** (AWS provider) — no CDK, no manual console changes. Use reusable modules (`lambda`, `dynamodb`, `sqs`, `cognito`, `iam`, `frontend`, `monitoring`), separate `dev` and `prod` environments via tfvars or workspaces, and remote state in a tiny S3 bucket using Terraform's native S3 state locking (`use_lockfile = true`, no DynamoDB lock table needed). Pin provider and module versions, tag every resource (project, env, owner), and run `terraform fmt`, `validate`, and `tflint` in CI.
- **LLM layer:** **Migrate from Gemini to the OpenAI API.** Use a cost-efficient, moderate-token-usage chat model (check OpenAI's current model list and recommend the best "mini"-tier option for RAG) and a small OpenAI embedding model. Model names must come from config, not be hardcoded. Put everything behind a provider interface so I could swap in Amazon Bedrock or others later without touching business logic.
- **Token and cost control:** Cap `max_tokens` per response, limit retrieved context size (top-k after reranking, trimmed to a token budget), count tokens with `tiktoken`, cache repeated queries and embeddings, and log input/output tokens and estimated cost per request. Add a per-user daily token quota.
- **Usage UI (two bars in the chat interface):**
  - **Context window bar:** shows how full the current conversation's context is (tokens used by system prompt + chat history + retrieved chunks vs. the selected model's context limit, e.g. "18.4k / 128k"). Colour goes green → amber (70%) → red (90%). Near the limit, automatically summarise or trim older turns and show a small notice when that happens.
  - **Usage limit bar:** shows the user's remaining daily token quota (and estimated cost), with a reset time. When the quota is reached, block new queries with a clear message instead of failing silently.
  - Backend: a `GET /usage` endpoint returning context tokens, context limit, tokens used today, daily quota, and reset time; include updated usage in every query/stream response so the bars update live. Model context limits come from config. Store usage counters in DynamoDB keyed by user and day (atomic `UpdateItem` increments, TTL to expire old days).
  - Add tests for token counting, quota enforcement, and context trimming.

## Design & theme (inspired by MindPalace)
Reference: https://backup.onepagelove.com/2024-08-30-mindpalace.html (an archived one-page site for "MindPalace", an AI personal-memory app). I've also attached a screenshot if available. Use it for **inspiration only**: do not copy its copy, logo, images, or code. Everything must be original and branded as DocuMindAI.

**What to borrow from the reference:**
- Oversized, bold display headlines revealed with a **staggered letter-by-letter (split-text) animation** on scroll.
- A **modular / bento-style layout**: content in distinct rounded cards of varying sizes rather than long text blocks.
- A clear narrative flow: the reference moves from "upload your data" → "see into your past" → "step into your future". Adapt this to documents.
- A simple **numbered 3-step onboarding** strip and a dedicated **"Private by Design"** section.
- Calm, premium, "second brain" mood with plenty of whitespace.

**Landing page structure for DocuMindAI:**
1. **Hero:** big animated headline (e.g. "Your documents, finally remembered."), one-line subtitle, primary CTA ("Start asking") and secondary CTA ("See how it works").
2. **Upload your documents:** card showing drag-and-drop PDFs and ingestion status (pending → processing → ready).
3. **Ask anything:** card showing a sample chat answer with **page-number citations**.
4. **Act on insights:** bento cards for summaries, cross-document search, and exporting answers.
5. **Proof section (instead of team testimonials):** do NOT invent testimonials or fake people. Show real numbers from the Phase 2 evaluation harness (recall@5, faithfulness, p95 latency) as stat cards, updated from the eval results file.
6. **How it works:** 3 numbered steps: Create account → Upload PDFs → Ask questions.
7. **Private by Design:** only claims that are actually true of the implementation: per-user data isolation, encryption at rest in S3/DynamoDB, documents deletable at any time. For any claim about OpenAI's data usage, check OpenAI's current API data policy and state it accurately, or leave it out.
8. **Closing CTA + footer.**

**App (chat) screens:** same visual language: document sidebar, chat area with citation cards that open the source page, and the **context window bar** and **usage limit bar** styled as slim, rounded progress bars in the header that match the theme.

**Implementation rules:**
- Next.js + Tailwind CSS + Framer Motion. Define design tokens (colors, radii, spacing, type scale) in one place; support light and dark mode.
- Pick a distinctive display font for headlines and a clean sans-serif for body text, with fallbacks.
- Split-text animations must be accessible: the full heading text available to screen readers (e.g. `aria-label` on the heading, letters `aria-hidden`), and animations disabled under `prefers-reduced-motion`.
- Fully responsive (mobile first), Lighthouse score 90+ for performance and accessibility.
- Show me a design proposal (palette, fonts, section wireframe) and wait for approval before building it.

## Phases

### Phase 1: Restructure and harden
- Reorganize into a proper package structure with FastAPI endpoints: upload, ingestion status, query (with streaming), list/delete documents.
- Centralized config, error handling, input validation, file type/size limits.
- Retries with exponential backoff and timeouts for all LLM and embedding calls.
- Replace Gemini with OpenAI (chat + embeddings) behind the provider interface. Since embedding dimensions change, re-embed all existing documents. The `OPENAI_API_KEY` is read from env locally and from SSM Parameter Store on AWS.
- `docker-compose` for local dev (API, DynamoDB Local, LocalStack for S3/SQS), so development costs nothing.

### Phase 2: Retrieval quality + evaluation harness (highest priority for impact)
- Build an **evaluation harness** first: a golden dataset of ~50 question/answer/source-page triples from sample PDFs, plus a script that reports recall@k, MRR, answer faithfulness, and latency. Save results so we can compare before/after.
- Record a baseline with the current pipeline.
- Then improve: structure-aware chunking (headings, tables, page boundaries), hybrid search (BM25 + dense vectors), a reranker, and metadata filtering.
- Answers must include **citations with document name and page number**, and the model should say "I don't know" when context is insufficient.
- Report the before/after metrics in a table.

### Phase 3: Testing and CI
- pytest unit tests (chunking, retrieval, services) and integration tests (API + DB), with LLM calls mocked.
- Linting/formatting (ruff), type checking (mypy).
- GitHub Actions: lint, type-check, test, build Lambda packages on every PR.

### Phase 4: Security and multi-tenancy
- Cognito/JWT auth; every DB and vector query scoped by user ID.
- Rate limiting per user.
- Basic prompt-injection defenses (treat document text as untrusted data, system prompt hardening).
- Dependency and secret scanning in CI.

### Phase 5: AWS deployment (free tier only)
- Terraform (modules, remote S3 state with native locking, `dev` and `prod` envs) for: Lambda functions (API + ingestion worker) with Function URLs, SQS + DLQ, DynamoDB tables with TTL, Cognito, SSM parameters, Amplify Hosting, CloudWatch log groups/alarms, IAM roles with least privilege, and the $1 budget alert.
- GitHub Actions deploy pipeline using **OIDC** (no long-lived AWS keys): `terraform plan` posted on PRs, `terraform apply` only on merge to main with manual approval for prod.
- Set Lambda **reserved concurrency** limits and SQS batch sizes so a traffic spike or bug can't exceed free allowances.
- Before `apply`, produce a table of every resource, its free-tier allowance, and expected usage; flag anything that isn't free.

### Phase 6: Observability and load testing
- Tracing across API Lambda → SQS → worker Lambda → DynamoDB → OpenAI (X-Ray/OpenTelemetry, within free limits).
- CloudWatch dashboard and alarms.
- Load test with Locust or k6, mainly against the **local** stack, plus a small, capped run against AWS that stays within free limits (mock the OpenAI calls to avoid token costs). Report throughput, p95 latency, and Lambda cold-start impact, then fix the top bottleneck.

### Phase 7: Documentation (for interviews and recruiters)
- README with an architecture diagram (Mermaid), setup steps, API docs, and the evaluation results table.
- `docs/adr/` with short Architecture Decision Records for key choices (in-Lambda vector search on DynamoDB vs pgvector/OpenSearch, serverless Lambda vs containers, SQS vs alternatives, chunking strategy, designing for a $0 budget).
- A "Design tradeoffs and scaling" section: what breaks at 10x and 100x load (e.g. in-memory vector search, Lambda cold starts, DynamoDB item limits), and what paid service I'd move to at each stage.

## Quality bar
- Readable, idiomatic, typed Python; no giant files or god functions.
- No secrets in code or git history.
- Every non-obvious decision gets a one-line comment or ADR.
- Prefer boring, proven tools over trendy ones.

Start with step 1: audit the codebase and give me the report.
