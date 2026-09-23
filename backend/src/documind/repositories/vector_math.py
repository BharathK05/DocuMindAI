"""Brute-force cosine search and compact embedding encoding.

Vectors are L2-normalised on the way in, so cosine similarity is a single matrix-vector product.
Exact search over a few thousand chunks per user takes about a millisecond in NumPy, so an ANN
index would add complexity without a measurable gain at this scale.
"""

import numpy as np
from numpy.typing import NDArray


def encode_vector(vector: NDArray[np.float32]) -> bytes:
    # float16 halves storage (1536 dims → 3 KB) with negligible effect on ranking.
    return vector.astype(np.float16).tobytes()


def decode_vector(data: bytes) -> NDArray[np.float32]:
    return np.frombuffer(data, dtype=np.float16).astype(np.float32)


def top_k_cosine(
    matrix: NDArray[np.float32], query: NDArray[np.float32], k: int
) -> list[tuple[int, float]]:
    """Return (row index, score) for the ``k`` rows most similar to ``query``, best first."""
    if matrix.shape[0] == 0 or k <= 0:
        return []
    scores = matrix @ query
    k = min(k, scores.shape[0])
    # argpartition is O(n); only the k winners get fully sorted.
    idx = np.argpartition(-scores, k - 1)[:k]
    idx = idx[np.argsort(-scores[idx])]
    return [(int(i), float(scores[i])) for i in idx]
