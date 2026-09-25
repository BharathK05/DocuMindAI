# 4. Structure-aware chunking, hybrid retrieval and an LLM reranker

- **Status:** accepted (2026-09-25). Every step was measured with the eval harness.

## Context
The prototype split text into 500-character chunks and used embedding search only. On a 55-question golden set over 3 NIST PDFs (160 pages), measured in [evaluation.md](../evaluation.md):
- answer correctness was **0.78**;
- the model **wrongly said "I don't know" 14%** of the time;
- questions about exact identifiers such as `GV.SC-04` missed.

The failures were half-lists split across chunks, running headers polluting chunks, and weak keyword matching.

## Decision
Each step is a setting, so the eval harness can switch it off and measure it:

| Step | Setting (default) | Measured effect |
|---|---|---|
| Structured chunks: strip page headers, footers and table-of-contents lines; ~350-token chunks with 50 overlap; prefix "Title > Section" before embedding | `chunking_strategy=structured` | Correctness **0.78 → 0.96** |
| Hybrid retrieval: BM25 + embeddings, merged with reciprocal rank fusion (k = 60) | `retrieval_mode=hybrid` | Recall@5 restored to 0.92; fixes identifier questions |
| Prompt v2: answer the supported part; decline only if nothing is relevant | `prompt_version=2` | Wrong "I don't know" **14% → 0%** |
| LLM reranker: one extra call (reasoning effort "none") orders the top 20 | `reranker=llm` | Recall@1 **0.62 → 0.80**, MRR 0.74 → 0.88 |

The best 5 chunks, trimmed to a 3,000-token budget, go to the model inside `<source>` tags. The answer cites them as `[n]`.

## Consequences
**Good:**
- **Measured quality, not assumed:**
  - Recall@5 0.98;
  - correctness 0.96;
  - faithfulness 1.00;
  - 100% of unanswerable questions declined.

**Bad:**
- **The reranker costs time and money.** It triples cost per question (still about $0.0006) and adds about 1.4 s. In production traces it's the largest single wait before the first word: **~2.1 s** ([performance.md](../performance.md)).
- **Tuned to one corpus.** The heuristics (header/footer detection, "Title Case" headings) suit reports and standards. Scanned PDFs (no text layer) aren't supported.

## Alternatives considered
| Option | Why not (now) |
|---|---|
| Cross-encoder reranker (e.g. MiniLM ms-marco) | Needs PyTorch or ONNX Runtime plus model weights, which break the Lambda package budget and add cold-start time |
| Semantic chunking by embedding similarity | Costs an embedding per sentence at ingest; structure-based splitting already fixed the list problem |
| Larger chunks without the reranker | Lowers precision and raises prompt cost |

## Revisit when
The reranker's latency matters more than its recall. Each of these candidates must keep correctness within noise on the eval:
- rerank 10 candidates instead of 20;
- send shorter passages (400 characters);
- rerank only when the top fused scores are close.
