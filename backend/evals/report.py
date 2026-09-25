"""Compare saved runs as a Markdown table.

python -m evals.report baseline structured hybrid rerank
"""

import json
import sys
from typing import Any

from evals.run import RESULTS_DIR

ROWS: list[tuple[str, str, str]] = [
    # (label, section, key)
    ("Recall@1", "retrieval", "recall@1"),
    ("Recall@5", "retrieval", "recall@5"),
    ("Recall@10", "retrieval", "recall@10"),
    ("MRR@10", "retrieval", "mrr@10"),
    ("Answer correctness", "answers", "correctness"),
    ("Faithfulness", "answers", "faithfulness"),
    ("Declines unanswerable (judged)", "answers", "declines_unanswerable"),
    ("Says exact IDK phrase when it should", "answers", "abstention_on_unanswerable"),
    ("Says IDK when it shouldn't", "answers", "false_abstention_on_answerable"),
    ("Retrieval p95 (ms)", "latency_ms", "retrieval_p95"),
    ("End-to-end p50 (ms)", "latency_ms", "end_to_end_p50"),
    ("End-to-end p95 (ms)", "latency_ms", "end_to_end_p95"),
    ("Input tokens / query", "tokens_per_query", "input"),
    ("Cost / query (USD)", "tokens_per_query", "usd"),
]


def load(label: str) -> dict[str, Any]:
    data: dict[str, Any] = json.loads((RESULTS_DIR / f"{label}.json").read_text(encoding="utf-8"))
    return data


def fmt(value: Any) -> str:
    if value is None:
        return "n/a"
    if isinstance(value, float):
        return f"{value:.4f}" if value < 0.01 else f"{value:.3f}".rstrip("0").rstrip(".")
    return str(value)


def table(labels: list[str]) -> str:
    runs = [load(label) for label in labels]
    lines = [
        "| Metric | " + " | ".join(labels) + " |",
        "|---|" + "---|" * len(labels),
    ]
    for name, section, key in ROWS:
        cells = [fmt(r["summary"][section].get(key)) for r in runs]
        lines.append(f"| {name} | " + " | ".join(cells) + " |")
    return "\n".join(lines)


if __name__ == "__main__":
    print(table(sys.argv[1:]))
