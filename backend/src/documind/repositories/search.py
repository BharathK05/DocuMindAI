"""In-process ranking: dense cosine, BM25 keyword scoring, and reciprocal rank fusion (RRF).

Why hybrid: embeddings capture meaning ("how often must users log in again?") but blur exact
tokens, so identifier questions ("what does GV.SC-04 state?") rank poorly. BM25 is the opposite.
RRF merges the two rankings using only rank positions, so the two score scales (cosine in
[-1, 1] vs unbounded BM25) never need calibrating against each other.
"""

import math
import re
from collections import Counter
from collections.abc import Sequence
from functools import lru_cache

import numpy as np
from numpy.typing import NDArray

from documind.core.config import RetrievalMode
from documind.repositories.vector_math import top_k_cosine

RRF_K = 60  # standard constant from Cormack et al. (2009); dampens the weight of top ranks
BM25_K1 = 1.2
BM25_B = 0.75

# Keeps identifiers such as "gv.sc-04" or "800-63b" whole, and also indexes their parts.
_TOKEN = re.compile(r"[a-z0-9]+(?:[.\-][a-z0-9]+)*")
_PARTS = re.compile(r"[.\-]")
_STOPWORD_TEXT = (
    "a an and are as at be by does for from has have how in is it its of on or that the "
    "this to was were what when where which who why with"
)
_STOPWORDS = frozenset(_STOPWORD_TEXT.split())


def tokenize(text: str) -> list[str]:
    tokens: list[str] = []
    for token in _TOKEN.findall(text.lower()):
        if token in _STOPWORDS:
            continue
        tokens.append(token)
        if "." in token or "-" in token:
            tokens.extend(p for p in _PARTS.split(token) if p and p not in _STOPWORDS)
    return tokens


@lru_cache(maxsize=50_000)
def term_counts(text: str) -> Counter[str]:
    """Cached per chunk text: a warm Lambda re-scores the same chunks on every query."""
    return Counter(tokenize(text))


def bm25_scores(query: str, documents: Sequence[Counter[str]]) -> NDArray[np.float64]:
    n = len(documents)
    scores = np.zeros(n)
    if n == 0:
        return scores
    lengths = np.array([sum(d.values()) for d in documents], dtype=np.float64)
    avg_length = lengths.mean() or 1.0
    norm = BM25_K1 * (1 - BM25_B + BM25_B * lengths / avg_length)
    for term in set(tokenize(query)):
        tf = np.array([d.get(term, 0) for d in documents], dtype=np.float64)
        df = int(np.count_nonzero(tf))
        if df == 0:
            continue
        idf = math.log(1 + (n - df + 0.5) / (df + 0.5))
        scores += idf * tf * (BM25_K1 + 1) / (tf + norm)
    return scores


def reciprocal_rank_fusion(rankings: Sequence[Sequence[int]]) -> list[tuple[int, float]]:
    fused: dict[int, float] = {}
    for ranking in rankings:
        for rank, item in enumerate(ranking, start=1):
            fused[item] = fused.get(item, 0.0) + 1.0 / (RRF_K + rank)
    return sorted(fused.items(), key=lambda kv: kv[1], reverse=True)


def rank(
    texts: Sequence[str],
    matrix: NDArray[np.float32],
    query_vector: NDArray[np.float32],
    query_text: str,
    *,
    top_k: int,
    mode: RetrievalMode,
    candidates: int,
) -> list[tuple[int, float]]:
    """Return (row index, score) pairs, best first."""
    if mode is RetrievalMode.DENSE:
        return top_k_cosine(matrix, query_vector, top_k)
    pool = max(candidates, top_k)
    dense = [i for i, _ in top_k_cosine(matrix, query_vector, pool)]
    keyword = bm25_scores(query_text, [term_counts(t) for t in texts])
    positive = np.flatnonzero(keyword > 0)
    lexical = positive[np.argsort(-keyword[positive])][:pool].tolist()
    return reciprocal_rank_fusion([dense, lexical])[:top_k]
