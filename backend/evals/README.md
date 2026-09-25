# Evaluation harness

It measures retrieval quality and answer quality on a fixed dataset, so each pipeline change can be judged by numbers rather than impressions.

## Dataset
- **Corpus:** three public-domain NIST publications in `corpus/`, 160 pages in total.
  - `NIST.CSWP.29.pdf`: Cybersecurity Framework 2.0. Mostly tables and identifier lists.
  - `NIST.SP.800-61r3.pdf`: Incident Response. A long table with recommendations.
  - `NIST.SP.800-63b.pdf`: Digital Identity Guidelines. Dense numbered requirements.
- **`golden.jsonl`:** 50 answerable questions, each with a reference answer, the source document and the page or pages it comes from. There are also 5 unanswerable questions, for measuring "I don't know".
  - Question types: `fact`, `list`, `definition`, `table`, `identifier` (for example "GV.SC-04") and `reasoning`.
  - Page numbers are physical PDF pages (1-based), not the printed page labels.

## Metrics
| Metric | Meaning |
|---|---|
| Recall@k | Share of answerable questions with at least one chunk from a gold page in the top k (the hit rate) |
| MRR@10 | Mean reciprocal rank of the first gold-page chunk |
| Answer correctness | An LLM judge compares the answer with the reference and scores 1, 0.5 or 0 |
| Faithfulness | An LLM judge counts the answer's claims supported by the retrieved passages, divided by all its claims |
| Abstention | The share of unanswerable questions answered "I don't know" (higher is better), and the share of answerable questions answered that way (lower is better) |
| Latency | p50 and p95 for retrieval and end to end, run sequentially in-process with the in-memory store |
| Cost | Chat tokens per query priced from `Settings`, including reranking calls |

**Caveats:**
- The judge is the same model family as the generator, so treat the scores as *relative*.
- Answer metrics vary by a few points between identical runs; see the `baseline` and `baseline-rerun` results. Retrieval metrics are deterministic.
- Differences smaller than that noise are not real improvements.

## Running it
```bash
cd backend
python -m evals.run --label my-run --set retrieval_mode=hybrid   # any Settings field
python -m evals.report baseline my-run                            # Markdown comparison
```
Each full run costs about US$0.01–0.05 in OpenAI tokens. Use `--limit 5 --no-judge` while iterating.

## Reproducing the Phase 2 table
The defaults are now the improved pipeline, so the baseline needs its original settings spelled out:
```bash
python -m evals.run --label baseline --set chunking_strategy=recursive --set retrieval_mode=dense --set reranker=none --set prompt_version=1
python -m evals.run --label structured --set chunking_strategy=structured --set retrieval_mode=dense --set reranker=none --set prompt_version=1
python -m evals.run --label structured-hybrid --set chunking_strategy=structured --set retrieval_mode=hybrid --set reranker=none --set prompt_version=1
python -m evals.run --label structured-hybrid-prompt2 --set reranker=none
python -m evals.run --label structured-hybrid-prompt2-rerank          # = current defaults
python -m evals.report baseline structured structured-hybrid structured-hybrid-prompt2 structured-hybrid-prompt2-rerank
```
Every results file records its full `config`, so you can check exactly what each run used.
