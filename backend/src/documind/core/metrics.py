"""Per-request measurements and CloudWatch metrics.

Two pieces:

* ``RequestStats``: counters for the current request, e.g. how many DynamoDB read capacity units
  it consumed. The API middleware and the worker start a fresh one per request/job; code deep
  in the repositories adds to it without having it passed around.
* ``emit``: writes a log line in CloudWatch's Embedded Metric Format (EMF). CloudWatch turns the
  "_aws" block into metrics as it ingests the log, so publishing costs no API calls and adds no
  latency. Without metrics enabled the same fields are still logged (plain JSON).
"""

import logging
import time
from collections.abc import Iterator, Mapping
from contextlib import contextmanager
from contextvars import ContextVar
from dataclasses import dataclass
from typing import Literal

NAMESPACE = "DocuMind"

Unit = Literal["Milliseconds", "Seconds", "Count", "None"]


@dataclass
class RequestStats:
    dynamo_read_units: float = 0.0
    dynamo_calls: int = 0
    cache_hits: int = 0
    cache_misses: int = 0


# Holds a mutable object on purpose: asyncio.to_thread runs repository code in a *copy* of the
# context, so rebinding the variable there would be lost, but mutating the shared object is not.
_stats: ContextVar[RequestStats | None] = ContextVar("request_stats", default=None)


@contextmanager
def track_request() -> Iterator[RequestStats]:
    stats = RequestStats()
    token = _stats.set(stats)
    try:
        yield stats
    finally:
        _stats.reset(token)


def current() -> RequestStats | None:
    return _stats.get()


def add_read_units(units: float) -> None:
    if (stats := _stats.get()) is not None:
        stats.dynamo_read_units += units
        stats.dynamo_calls += 1


def add_cache_result(*, hit: bool) -> None:
    if (stats := _stats.get()) is not None:
        if hit:
            stats.cache_hits += 1
        else:
            stats.cache_misses += 1


def emit(
    logger: logging.Logger,
    message: str,
    *,
    env: str,
    enabled: bool,
    metrics: Mapping[str, tuple[float, Unit]],
    **fields: object,
) -> None:
    """Log ``fields`` plus ``metrics``; when ``enabled``, also as CloudWatch metrics.

    Every metric uses the single dimension ``Env``: each extra dimension combination would be a
    separately billed custom metric.
    """
    extra: dict[str, object] = {**fields, **{name: value for name, (value, _) in metrics.items()}}
    if enabled:
        extra["Env"] = env
        extra["_aws"] = {
            "Timestamp": int(time.time() * 1000),
            "CloudWatchMetrics": [
                {
                    "Namespace": NAMESPACE,
                    "Dimensions": [["Env"]],
                    "Metrics": [
                        {"Name": name, "Unit": unit} for name, (_, unit) in metrics.items()
                    ],
                }
            ],
        }
    logger.info(message, extra=extra)
