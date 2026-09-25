import numpy as np

from documind.providers.base import l2_normalize
from documind.repositories.vector_math import decode_vector, encode_vector, top_k_cosine


def test_top_k_returns_best_first() -> None:
    matrix = l2_normalize(np.array([[1, 0], [0, 1], [1, 1]], dtype=np.float32))
    query = l2_normalize(np.array([[1, 0.1]], dtype=np.float32))[0]
    result = top_k_cosine(matrix, query, k=2)
    assert [i for i, _ in result] == [0, 2]
    assert result[0][1] > result[1][1]


def test_top_k_handles_k_larger_than_rows_and_empty() -> None:
    matrix = np.eye(2, dtype=np.float32)
    assert len(top_k_cosine(matrix, matrix[0], k=10)) == 2
    assert top_k_cosine(np.empty((0, 2), dtype=np.float32), matrix[0], k=3) == []


def test_float16_roundtrip_preserves_ranking() -> None:
    rng = np.random.default_rng(0)
    matrix = l2_normalize(rng.normal(size=(200, 64)).astype(np.float32))
    query = matrix[7]
    decoded = np.vstack([decode_vector(encode_vector(v)) for v in matrix])
    assert len(encode_vector(matrix[0])) == 64 * 2  # 2 bytes per dimension
    assert [i for i, _ in top_k_cosine(decoded, query, 5)] == [
        i for i, _ in top_k_cosine(matrix, query, 5)
    ]
