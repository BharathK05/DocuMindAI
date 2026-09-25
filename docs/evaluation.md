# Retrieval and answer quality (Phase 2)

- **Setup:** 50 answerable plus 5 unanswerable questions over 3 public-domain NIST PDFs (160 pages). Harness, dataset and raw results are in [`backend/evals/`](../backend/evals/).
- **Models:** `gpt-6-luna` answers (reasoning effort `low`) and `text-embedding-3-small` embeds.
- **Method:** each column adds one change to the column before it. Results were measured on 2026-09-25.

| Metric | Baseline | + Structured chunks | + Hybrid search | + Prompt v2 | + LLM rerank (default) |
|---|---|---|---|---|---|
| Recall@1 | 0.54 | 0.58 | 0.62 | 0.62 | **0.80** |
| Recall@5 | 0.92 | 0.88 | 0.92 | 0.92 | **0.98** |
| Recall@10 | 0.98 | 0.90 | 0.98 | 0.98 | **1.00** |
| MRR@10 | 0.703 | 0.710 | 0.743 | 0.743 | **0.877** |
| Answer correctness (LLM judge) | 0.78 | 0.96 | 0.91 | 0.91 | **0.96** |
| Faithfulness (LLM judge) | 0.984 | 0.980 | 0.998 | 0.963 | **1.000** |
| Declines unanswerable questions | 1.00 | 1.00 | 1.00 | 1.00 | 1.00 |
| Wrongly says "I don't know" | 14% | 2% | 4% | **0%** | **0%** |
| End-to-end latency p50 / p95 | 1.7 / 2.6 s | 1.6 / 2.4 s | 1.7 / 3.0 s | 1.6 / 2.2 s | 3.0 / 4.4 s |
| Cost per query | $0.0001 | $0.0002 | $0.0002 | $0.0002 | $0.0006 |

## What each change does
- **Structured chunks**
  - Strips running headers, footers and table-of-contents lines.
  - Uses ~350-token chunks instead of 500 characters, so lists and table rows stay together.
  - Prefixes each chunk with "Title > Section" before embedding.
  - Result: the biggest gain in answer quality (+18 pts correctness), because the model stops seeing half a list. Recall@5 dipped because there are 3× fewer, larger chunks.
- **Hybrid search**
  - Adds BM25 keyword scoring and merges it with the embedding results using reciprocal rank fusion.
  - Result: restores recall, and fixes questions about exact identifiers such as `GV.SC-04`.
- **Prompt v2**
  - Says: answer the supported part of a question, and decline only when nothing relevant is found.
  - Result: wrong "I don't know" answers go to zero, and every unanswerable question is still declined, only in the model's own words.
- **LLM reranker**
  - One extra call with reasoning effort `none` reorders the top 20 candidates.
  - Result: the largest retrieval gain (Recall@1 +18 pts), at the cost of about 1.4 s latency and 3× the per-query cost.
  - Turn it off with `DOCUMIND_RERANKER=none`.

## Caveats
- **Judge bias.** The judge is the same model family as the generator, so compare runs with each other rather than reading the scores as absolute.
- **Run-to-run noise.** Answer metrics move by about ±0.02–0.05 between identical runs; compare the `baseline` and `baseline-rerun` results. Retrieval metrics are deterministic.
- **Latency is measured in-process with in-memory storage.** DynamoDB reads, Lambda cold starts and the network are measured in Phase 6.
- **Small sample.** 50 questions over 3 documents is enough to rank these changes, but too few to claim precise absolute numbers.
