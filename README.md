---
title: DocuMind AI
emoji: 🧠
colorFrom: blue
colorTo: indigo
sdk: gradio
app_file: app.py
pinned: false
---

# 🧠 DocuMind AI
**Retrieval-augmented Q&A over your PDFs, with page-level citations.**

[![Hugging Face Space](https://img.shields.io/badge/🤗%20Hugging%20Face-Live%20Demo-blue)](https://huggingface.co/spaces/Bhrthx/DocuMindAI)

> **Work in progress:** this branch is being upgraded from a Gradio prototype to a serverless,
> production-grade system (FastAPI + OpenAI + DynamoDB/S3/SQS on the AWS free tier). The plan is
> in [docs/SPEC.md](docs/SPEC.md). Full documentation (architecture diagram, ADRs, evaluation
> results) arrives in Phase 7.

## How it works
1. The client asks the API for a presigned URL and uploads the PDF **directly to S3**.
2. An **SQS** message triggers the ingestion worker:
   - parse pages;
   - strip running headers and TOC lines;
   - cut structure-aware chunks of about 350 tokens, each tagged "Title > Section";
   - embed them in batches with OpenAI `text-embedding-3-small`;
   - store chunks and float16 vectors in **DynamoDB**, one partition per user.
3. A question goes through **hybrid retrieval**: BM25 plus embeddings, merged with reciprocal rank fusion. An **LLM reranker** then orders the top 20. The top chunks go to the chat model (`gpt-6-luna` by default, configurable) inside `<source>` tags. The answer streams back over Server-Sent Events with `[n]` citations to document and page.

**Measured quality** (50-question golden set; see [docs/evaluation.md](docs/evaluation.md)):
- Recall@5 went from 0.92 to **0.98**, and MRR@10 from 0.70 to **0.88**.
- Answer correctness went from 0.78 to **0.96**, with faithfulness at **1.00**.
- It declined all unanswerable questions.
- Cost is about $0.0006 per query.

## Run locally

Prerequisites: Python 3.13+, Docker.

```bash
cp backend/.env.example backend/.env   # add OPENAI_API_KEY, or set DOCUMIND_LLM_PROVIDER=fake
docker compose up --build              # API → http://localhost:8000/docs
```

The compose stack runs DynamoDB Local and [moto](https://github.com/getmoto/moto) (S3 + SQS),
so local development costs nothing and needs no AWS account.

**Without Docker** (in-memory storage; data resets on restart):

```bash
python -m venv .venv && .venv/Scripts/activate      # macOS/Linux: source .venv/bin/activate
pip install -e "backend[server,dev,demo]"
cd backend && uvicorn documind.api.main:app --reload # API
python ../demos/gradio_app.py                        # or the Gradio demo UI
```

### API
Every endpoint except `/health` requires `Authorization: Bearer <token>`:
- **On AWS:** a Cognito access token.
- **Locally:** a development token. Mint one with:
  ```bash
  cd backend
  python -m documind.scripts.dev_token --user alice
  ```
  Paste it into **Authorize** at `/docs`. Each `--user` is a separate, isolated account.

| Method | Path | Purpose |
|---|---|---|
| `POST` | `/v1/documents` | Register a PDF and get a presigned S3 upload form |
| `POST` | `/v1/documents/{id}/complete` | Confirm the upload and queue ingestion |
| `GET` | `/v1/documents` / `/v1/documents/{id}` | List documents / check ingestion status |
| `DELETE` | `/v1/documents/{id}` | Delete a document and all its chunks |
| `POST` | `/v1/conversations` | Start a conversation (the server stores and manages its history) |
| `GET` | `/v1/conversations` / `/v1/conversations/{id}` | List conversations / read one, with messages and citations |
| `DELETE` | `/v1/conversations/{id}` | Delete a conversation |
| `POST` | `/v1/query` | Answer with citations, plus token usage, context-window and daily-quota figures |
| `POST` | `/v1/query/stream` | Same, streamed as SSE: `sources` → `token`… → `done` (the `done` event carries the usage figures) |
| `GET` | `/v1/usage?conversation_id=` | Figures for the two usage bars: context window and daily quota |

To walk through the whole flow against the local stack:
```bash
python backend/scripts/try_api.py some.pdf "Your question?"
```

### Security and cost controls
- **Tenant isolation.** The token's `sub` claim is the user id. Every DynamoDB key starts with `USER#<id>`, and no repository method can read without one.
- **Rate limits.** Defaults are 20 questions per minute and 20 uploads per hour per user. The counters live in DynamoDB, so the limits hold across Lambda instances. Over the limit, the API returns `429` with `Retry-After`.
- **Daily token quota.** The default is 200k tokens, about 40 questions. When it's used up, the API returns a clear `429 quota_exceeded` saying when it resets.
- **Context budget.** Each conversation's prompt is kept within 16k tokens. Near the limit, older turns are summarized (or dropped) and the response includes a notice.
- **Prompt-injection defenses.**
  - Document text is fenced as untrusted data.
  - Tag-like text inside documents is neutralized.
  - Clients can't send system messages.
  - Stored history comes from the server, not the client.
- **CI scans.**
  - gitleaks checks the full git history for leaked secrets.
  - pip-audit checks dependencies for known vulnerabilities.
  - Dependabot opens weekly update pull requests.

### Tests and checks
```bash
cd backend
pytest --cov                                  # unit + integration; fails below 90% coverage
ruff check . && ruff format --check . && mypy src evals tests scripts
```
- **Mocked dependencies.** Tests need no OpenAI key or AWS account: LLM calls use a deterministic fake provider, and AWS is emulated in-process by [moto](https://github.com/getmoto/moto).

### Continuous integration
[`.github/workflows/ci.yml`](.github/workflows/ci.yml) runs on every pull request and every push to `main` or `upgrade`, in three jobs:
1. **Lint and type-check.** Ruff checks linting and formatting, and mypy type-checks in strict mode.
2. **Tests.** pytest with a 90% coverage gate.
3. **Build Lambda packages.** Runs only if the first two pass:
   - builds the deployment zips;
   - smoke-tests them inside AWS's official Lambda Python image with the network disabled;
   - uploads the arm64 zips as a build artifact.

To build and check the Lambda packages locally (needs Docker):
```bash
cd backend
python scripts/build_lambda.py --arch x86_64 && bash scripts/lambda_smoke.sh x86_64
```
