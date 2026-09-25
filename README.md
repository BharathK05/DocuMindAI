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
| Method | Path | Purpose |
|---|---|---|
| `POST` | `/v1/documents` | Register a PDF and get a presigned S3 upload form |
| `POST` | `/v1/documents/{id}/complete` | Confirm the upload and queue ingestion |
| `GET` | `/v1/documents` / `/v1/documents/{id}` | List documents / check ingestion status |
| `DELETE` | `/v1/documents/{id}` | Delete a document and all its chunks |
| `POST` | `/v1/query` | Answer with citations and token usage |
| `POST` | `/v1/query/stream` | Same, streamed as SSE: `sources` → `token`… → `done` |

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
