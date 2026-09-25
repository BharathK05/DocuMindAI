"""Request stats, the chunk cache's bounds, and the CloudWatch Embedded Metric Format."""

import json
import logging

import numpy as np
import pytest

from documind.core import metrics
from documind.core.logging import JsonFormatter
from documind.domain import Chunk
from documind.repositories.dynamodb import ChunkCache, DocumentChunks


def entry(n: int) -> DocumentChunks:
    return DocumentChunks([Chunk("d", i, 1, "t") for i in range(n)], np.zeros((n, 2), np.float32))


def test_cache_evicts_least_recently_used_by_chunk_count() -> None:
    cache = ChunkCache(max_chunks=10)
    cache.put(("u", "a"), entry(4))
    cache.put(("u", "b"), entry(4))
    assert cache.get(("u", "a")) is not None  # "a" is now the most recently used
    cache.put(("u", "c"), entry(4))  # 12 > 10: evict "b"
    assert cache.get(("u", "b")) is None
    assert cache.get(("u", "a")) is not None and cache.get(("u", "c")) is not None
    assert len(cache) == 8
    cache.put(("u", "huge"), entry(11))  # larger than the whole cache: not stored
    assert cache.get(("u", "huge")) is None
    cache.discard(("u", "a"))
    assert len(cache) == 4


def test_stats_only_count_inside_a_tracked_request() -> None:
    metrics.add_read_units(5)  # no request: ignored, no error
    with metrics.track_request() as stats:
        metrics.add_read_units(2.5)
        metrics.add_read_units(1)
        metrics.add_cache_result(hit=True)
        assert metrics.current() is stats
    assert (stats.dynamo_read_units, stats.dynamo_calls, stats.cache_hits) == (3.5, 2, 1)
    assert metrics.current() is None


def capture(enabled: bool, caplog: pytest.LogCaptureFixture) -> dict[str, object]:
    logger = logging.getLogger("test.metrics")
    with caplog.at_level(logging.INFO, logger="test.metrics"):
        metrics.emit(
            logger,
            "chat turn",
            env="prod",
            enabled=enabled,
            metrics={"LatencyMs": (1234, "Milliseconds"), "CostUSD": (0.0005, "None")},
            streamed=True,
        )
    parsed: dict[str, object] = json.loads(JsonFormatter().format(caplog.records[-1]))
    return parsed


def test_emf_line_is_valid_cloudwatch_metrics(caplog: pytest.LogCaptureFixture) -> None:
    line = capture(True, caplog)
    assert line["LatencyMs"] == 1234 and line["Env"] == "prod" and line["streamed"] is True
    spec = line["_aws"]["CloudWatchMetrics"][0]  # type: ignore[index]
    assert spec["Namespace"] == "DocuMind" and spec["Dimensions"] == [["Env"]]
    assert {m["Name"] for m in spec["Metrics"]} == {"LatencyMs", "CostUSD"}


def test_without_metrics_the_values_are_still_logged(caplog: pytest.LogCaptureFixture) -> None:
    line = capture(False, caplog)
    assert line["LatencyMs"] == 1234 and "_aws" not in line and "Env" not in line
