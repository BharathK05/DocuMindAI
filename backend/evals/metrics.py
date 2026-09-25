"""Pure metric functions, kept separate from I/O so they are easy to unit test."""

import math
from collections.abc import Sequence

# A retrieved chunk is identified by (document filename, page number).
Hit = tuple[str, int]

IDK_MARKERS = ("i don't know", "i do not know", "i dont know")


def is_relevant(hit: Hit, document: str, pages: Sequence[int]) -> bool:
    return hit[0] == document and hit[1] in pages


def first_relevant_rank(ranked: Sequence[Hit], document: str, pages: Sequence[int]) -> int | None:
    """1-based rank of the first chunk from a gold page, or None if none was retrieved."""
    for rank, hit in enumerate(ranked, start=1):
        if is_relevant(hit, document, pages):
            return rank
    return None


def hit_at_k(rank: int | None, k: int) -> float:
    """Recall@k in the single-gold-location sense (a.k.a. hit rate): did any gold page appear?"""
    return 1.0 if rank is not None and rank <= k else 0.0


def reciprocal_rank(rank: int | None) -> float:
    return 0.0 if rank is None else 1.0 / rank


def is_abstention(answer: str) -> bool:
    text = answer.strip().lower().replace(chr(0x2019), "'")  # curly apostrophe
    return any(marker in text[:120] for marker in IDK_MARKERS)


def percentile(values: Sequence[float], pct: float) -> float:
    """Nearest-rank percentile (no interpolation), which is what latency SLOs usually mean."""
    if not values:
        return math.nan
    ordered = sorted(values)
    index = max(0, math.ceil(pct / 100 * len(ordered)) - 1)
    return ordered[index]


def mean(values: Sequence[float]) -> float:
    return sum(values) / len(values) if values else math.nan
