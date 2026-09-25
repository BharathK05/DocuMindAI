import math

from evals import metrics


def test_first_relevant_rank_and_hit_rate() -> None:
    ranked = [("a.pdf", 3), ("b.pdf", 7), ("a.pdf", 7)]
    rank = metrics.first_relevant_rank(ranked, "a.pdf", [7, 8])
    assert rank == 3
    assert metrics.hit_at_k(rank, 1) == 0.0
    assert metrics.hit_at_k(rank, 3) == 1.0
    assert metrics.reciprocal_rank(rank) == 1 / 3
    assert metrics.first_relevant_rank(ranked, "c.pdf", [1]) is None
    assert metrics.reciprocal_rank(None) == 0.0


def test_abstention_detection() -> None:
    assert metrics.is_abstention("I don't know. The provided documents don't contain that.")
    assert metrics.is_abstention("I don" + chr(0x2019) + "t know.")  # curly apostrophe
    assert not metrics.is_abstention("The limit is 100 consecutive failed attempts [1].")


def test_percentile_is_nearest_rank() -> None:
    values = [float(v) for v in range(1, 101)]
    assert metrics.percentile(values, 50) == 50
    assert metrics.percentile(values, 95) == 95
    assert math.isnan(metrics.percentile([], 95))
