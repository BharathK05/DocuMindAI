"""Run the evaluation harness end to end and save the results.

    cd backend
    python -m evals.run --label baseline
    python -m evals.run --label hybrid --set retrieval_mode=hybrid

``--set`` overrides any Settings field for this run (same names as the DOCUMIND_* env vars), so
every pipeline variant is reproducible from the command line and recorded in the results file.
Costs real OpenAI tokens (about US$0.05-0.10 per full run); use ``--limit`` while iterating.
"""

import argparse
import asyncio
import json
import math
import os
import subprocess
import time
from dataclasses import asdict, dataclass, field
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from openai import AsyncOpenAI

from documind.core.config import Backend, Settings
from documind.core.container import build_container
from documind.services.query import Retrieval
from evals import metrics
from evals.judge import Judge

EVALS_DIR = Path(__file__).parent
CORPUS_DIR = EVALS_DIR / "corpus"
RESULTS_DIR = EVALS_DIR / "results"
USER = "eval-user"
K_VALUES = (1, 3, 5, 10)


@dataclass
class Row:
    id: str
    type: str
    answerable: bool
    question: str
    reference: str
    document: str | None
    pages: list[int]
    retrieved: list[tuple[str, int]] = field(default_factory=list)
    first_relevant_rank: int | None = None
    answer: str = ""
    abstained: bool = False
    declined: bool | None = None  # judged honest refusal (unanswerable questions only)
    correctness: float | None = None
    correctness_reason: str = ""
    faithfulness: float | None = None
    unsupported: str = ""
    retrieval_ms: float = 0.0
    total_ms: float = 0.0
    input_tokens: int = 0
    output_tokens: int = 0


def load_golden(limit: int | None) -> list[dict[str, Any]]:
    lines = (EVALS_DIR / "golden.jsonl").read_text(encoding="utf-8").splitlines()
    items = [json.loads(line) for line in lines if line.strip()]
    return items[:limit] if limit else items


def settings_for(overrides: list[str]) -> Settings:
    # Env vars give pydantic's normal type coercion (ints, enums, bools) for free.
    os.environ["DOCUMIND_BACKEND"] = Backend.MEMORY.value
    for item in overrides:
        key, _, value = item.partition("=")
        os.environ[f"DOCUMIND_{key.strip().upper()}"] = value.strip()
    return Settings()


def git_sha() -> str:
    try:
        return subprocess.run(
            ["git", "rev-parse", "--short", "HEAD"], capture_output=True, text=True, check=True
        ).stdout.strip()
    except (OSError, subprocess.CalledProcessError):
        return "unknown"


async def run(label: str, overrides: list[str], limit: int | None, judge_enabled: bool) -> Path:
    settings = settings_for(overrides)
    container = build_container(settings)
    golden = load_golden(limit)

    # 1. Ingest the corpus through the real ingestion pipeline.
    ingest_started = time.perf_counter()
    corpus: dict[str, dict[str, int]] = {}
    for pdf in sorted(CORPUS_DIR.glob("*.pdf")):
        doc = await container.ingestion_service.ingest_bytes(USER, pdf.name, pdf.read_bytes())
        corpus[pdf.name] = {"pages": doc.page_count or 0, "chunks": doc.chunk_count or 0}
    ingest_s = time.perf_counter() - ingest_started
    print(f"Ingested {len(corpus)} PDFs in {ingest_s:.1f}s: {corpus}")

    # 2. Retrieval + generation, sequentially so latency numbers aren't skewed by contention.
    rows: list[Row] = []
    sources: dict[str, list[str]] = {}  # judge input per question; not persisted
    for item in golden:
        row = Row(
            id=item["id"],
            type=item["type"],
            answerable=item["answerable"],
            question=item["question"],
            reference=item["reference"],
            document=item["document"],
            pages=item["pages"],
        )
        started = time.perf_counter()
        retrieval = await container.query_service.retrieve(USER, row.question, top_k=max(K_VALUES))
        row.retrieval_ms = (time.perf_counter() - started) * 1000
        row.retrieved = [
            (retrieval.filenames[s.chunk.document_id], s.chunk.page) for s in retrieval.chunks
        ]
        if row.document:
            row.first_relevant_rank = metrics.first_relevant_rank(
                row.retrieved, row.document, row.pages
            )

        # Generation sees exactly what the product would: the top retrieval_top_k chunks.
        context = Retrieval(
            retrieval.chunks[: settings.retrieval_top_k], retrieval.filenames, retrieval.usage
        )
        answer = await container.query_service.generate(row.question, [], context)
        row.total_ms = (time.perf_counter() - started) * 1000
        row.answer = answer.text
        row.abstained = metrics.is_abstention(answer.text)
        row.input_tokens, row.output_tokens = answer.usage.input_tokens, answer.usage.output_tokens
        rows.append(row)
        print(
            f"  {row.id:8} rank={row.first_relevant_rank} "
            f"abstain={row.abstained} {row.total_ms:6.0f}ms"
        )
        sources[row.id] = [s.chunk.text for s in context.chunks]

    # 3. Judge answers (concurrently; judging latency isn't part of the product's latency).
    judge_tokens = [0, 0]
    if judge_enabled:
        assert settings.openai_api_key, "Judging needs OPENAI_API_KEY"
        judge = Judge(
            AsyncOpenAI(api_key=settings.openai_api_key.get_secret_value(), max_retries=5),
            model=settings.chat_model,
            reasoning_effort="medium",
        )
        semaphore = asyncio.Semaphore(4)

        async def grade(row: Row) -> None:
            if not row.answerable:
                async with semaphore:
                    d = await judge.declines(row.question, row.answer)
                row.declined, row.correctness_reason = d.score == 1.0, d.detail
                judge_tokens[0] += d.input_tokens
                judge_tokens[1] += d.output_tokens
                return
            if row.abstained:
                row.correctness, row.correctness_reason = 0.0, "abstained"
                return
            async with semaphore:
                c, f = await asyncio.gather(
                    judge.correctness(row.question, row.reference, row.answer),
                    judge.faithfulness(row.answer, sources[row.id]),
                )
            row.correctness, row.correctness_reason = c.score, c.detail
            row.faithfulness, row.unsupported = f.score, f.detail
            judge_tokens[0] += c.input_tokens + f.input_tokens
            judge_tokens[1] += c.output_tokens + f.output_tokens

        await asyncio.gather(*(grade(r) for r in rows))

    summary = summarize(rows, settings, ingest_s, corpus, judge_tokens)
    RESULTS_DIR.mkdir(exist_ok=True)
    out = RESULTS_DIR / f"{label}.json"
    payload = {
        "label": label,
        "created_at": datetime.now(UTC).isoformat(timespec="seconds"),
        "git_sha": git_sha(),
        "overrides": overrides,
        "config": config_snapshot(settings),
        "summary": summary,
        "rows": [asdict(r) for r in rows],
    }
    out.write_text(json.dumps(payload, indent=2), encoding="utf-8")
    print(json.dumps(summary, indent=2))
    print(f"Saved {out}")
    return out


def config_snapshot(s: Settings) -> dict[str, Any]:
    keys = (
        "chat_model",
        "chat_reasoning_effort",
        "chat_max_output_tokens",
        "embedding_model",
        "embedding_dimensions",
        "chunk_size",
        "chunk_overlap",
        "retrieval_top_k",
    )
    extra = ("chunking_strategy", "retrieval_mode", "reranker", "context_token_budget")
    return {k: getattr(s, k) for k in (*keys, *extra) if hasattr(s, k)}


def summarize(
    rows: list[Row],
    settings: Settings,
    ingest_s: float,
    corpus: dict[str, dict[str, int]],
    judge_tokens: list[int],
) -> dict[str, Any]:
    answerable = [r for r in rows if r.answerable]
    unanswerable = [r for r in rows if not r.answerable]
    ranks = [r.first_relevant_rank for r in answerable]
    graded = [r.correctness for r in answerable if r.correctness is not None]
    faithful = [r.faithfulness for r in answerable if r.faithfulness is not None]
    cost = [
        (
            r.input_tokens * settings.chat_input_usd_per_mtok
            + r.output_tokens * settings.chat_output_usd_per_mtok
        )
        / 1e6
        for r in rows
    ]
    by_type: dict[str, list[float]] = {}
    for r in answerable:
        by_type.setdefault(r.type, []).append(metrics.hit_at_k(r.first_relevant_rank, 5))

    def rnd(x: float, n: int = 3) -> float | None:
        return None if math.isnan(x) else round(x, n)  # NaN is not valid JSON

    return {
        "questions": {"answerable": len(answerable), "unanswerable": len(unanswerable)},
        "corpus": {
            "documents": len(corpus),
            "chunks": sum(c["chunks"] for c in corpus.values()),
            "ingest_seconds": rnd(ingest_s, 1),
        },
        "retrieval": {
            **{
                f"recall@{k}": rnd(metrics.mean([metrics.hit_at_k(x, k) for x in ranks]))
                for k in K_VALUES
            },
            "mrr@10": rnd(metrics.mean([metrics.reciprocal_rank(x) for x in ranks])),
            "recall@5_by_type": {t: rnd(metrics.mean(v)) for t, v in sorted(by_type.items())},
        },
        "answers": {
            "correctness": rnd(metrics.mean(graded)) if graded else None,
            "faithfulness": rnd(metrics.mean(faithful)) if faithful else None,
            "declines_unanswerable": rnd(
                metrics.mean(
                    [1.0 if r.declined else 0.0 for r in unanswerable if r.declined is not None]
                )
            ),
            "abstention_on_unanswerable": rnd(
                metrics.mean([1.0 if r.abstained else 0.0 for r in unanswerable])
            ),
            "false_abstention_on_answerable": rnd(
                metrics.mean([1.0 if r.abstained else 0.0 for r in answerable])
            ),
        },
        "latency_ms": {
            "retrieval_p50": round(metrics.percentile([r.retrieval_ms for r in rows], 50)),
            "retrieval_p95": round(metrics.percentile([r.retrieval_ms for r in rows], 95)),
            "end_to_end_p50": round(metrics.percentile([r.total_ms for r in rows], 50)),
            "end_to_end_p95": round(metrics.percentile([r.total_ms for r in rows], 95)),
        },
        "tokens_per_query": {
            "input": round(metrics.mean([r.input_tokens for r in rows])),
            "output": round(metrics.mean([r.output_tokens for r in rows])),
            "usd": rnd(metrics.mean(cost), 6),
        },
        "judge_usd": rnd(
            (
                judge_tokens[0] * settings.chat_input_usd_per_mtok
                + judge_tokens[1] * settings.chat_output_usd_per_mtok
            )
            / 1e6,
            4,
        ),
    }


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--label", required=True, help="name of the results file")
    parser.add_argument(
        "--set",
        dest="overrides",
        action="append",
        default=[],
        help="Settings override, e.g. --set retrieval_mode=hybrid",
    )
    parser.add_argument("--limit", type=int, help="only the first N questions")
    parser.add_argument("--no-judge", action="store_true", help="skip LLM grading")
    args = parser.parse_args()
    asyncio.run(run(args.label, args.overrides, args.limit, not args.no_judge))


if __name__ == "__main__":
    main()
