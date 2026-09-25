"""Per-user rate limiting and daily token accounting (in-memory and DynamoDB).

Both live in DynamoDB rather than in process memory because Lambda runs many short-lived
instances: an in-memory counter would reset on every cold start and be split across instances.

Keys (same single table, same per-user partition as everything else):
    PK = USER#<id>   SK = RATE#<bucket>#<window start>   → fixed-window request counter
    PK = USER#<id>   SK = USAGE#<YYYY-MM-DD>             → tokens used that UTC day
Both carry ``expires_at`` so DynamoDB's TTL deletes them for free once they're stale.
"""

import asyncio
import time
from collections.abc import Callable

from botocore.exceptions import ClientError

from documind.core.errors import RateLimitedError
from documind.domain import DailyUsage, TokenUsage
from documind.repositories.dynamodb import DynamoTable

Clock = Callable[[], float]


def _window(now: float, window_seconds: int) -> tuple[int, int]:
    start = int(now // window_seconds * window_seconds)
    return start, start + window_seconds


def _limited(bucket: str, window_end: int, now: float) -> RateLimitedError:
    retry_after = max(1, int(window_end - now))
    return RateLimitedError(
        f"Too many {bucket} requests. Try again in {retry_after} seconds.", retry_after
    )


class InMemoryRateLimiter:
    def __init__(self, clock: Clock = time.time) -> None:
        self._clock = clock
        self._hits: dict[tuple[str, str, int], int] = {}

    async def hit(self, user_id: str, bucket: str, *, limit: int, window_seconds: int) -> None:
        now = self._clock()
        start, end = _window(now, window_seconds)
        key = (user_id, bucket, start)
        if self._hits.get(key, 0) >= limit:
            raise _limited(bucket, end, now)
        self._hits[key] = self._hits.get(key, 0) + 1


class DynamoRateLimiter:
    def __init__(self, table: DynamoTable, clock: Clock = time.time) -> None:
        self._t = table
        self._clock = clock

    async def hit(self, user_id: str, bucket: str, *, limit: int, window_seconds: int) -> None:
        now = self._clock()
        start, end = _window(now, window_seconds)
        try:
            # Check-and-increment in ONE conditional write, so two concurrent requests can't
            # both read "limit - 1" and both get through.
            await asyncio.to_thread(
                self._t.client.update_item,
                TableName=self._t.name,
                Key={"PK": {"S": f"USER#{user_id}"}, "SK": {"S": f"RATE#{bucket}#{start}"}},
                UpdateExpression="ADD hits :one SET expires_at = :expires",
                ConditionExpression="attribute_not_exists(hits) OR hits < :limit",
                ExpressionAttributeValues={
                    ":one": {"N": "1"},
                    ":limit": {"N": str(limit)},
                    ":expires": {"N": str(end + 60)},
                },
            )
        except ClientError as exc:
            if exc.response["Error"]["Code"] == "ConditionalCheckFailedException":
                raise _limited(bucket, end, now) from exc
            raise


class InMemoryUsageRepository:
    def __init__(self) -> None:
        # Keys are ("user", id, day) or ("service", "", day): the two can never collide.
        self._days: dict[tuple[str, str, str], DailyUsage] = {}

    def _add(self, key: tuple[str, str, str], usage: TokenUsage) -> None:
        current = self._days.get(key, DailyUsage(key[2]))
        self._days[key] = DailyUsage(
            key[2],
            current.input_tokens + usage.input_tokens,
            current.output_tokens + usage.output_tokens,
            current.requests + 1,
        )

    async def add(self, user_id: str, day: str, usage: TokenUsage, *, expires_at: int) -> None:
        self._add(("user", user_id, day), usage)

    async def get(self, user_id: str, day: str) -> DailyUsage:
        return self._days.get(("user", user_id, day), DailyUsage(day))

    async def add_service(self, day: str, usage: TokenUsage, *, expires_at: int) -> None:
        self._add(("service", "", day), usage)

    async def get_service(self, day: str) -> DailyUsage:
        return self._days.get(("service", "", day), DailyUsage(day))


class DynamoUsageRepository:
    def __init__(self, table: DynamoTable) -> None:
        self._t = table

    @staticmethod
    def _key(pk: str, day: str) -> dict[str, dict[str, str]]:
        return {"PK": {"S": pk}, "SK": {"S": f"USAGE#{day}"}}

    async def add(self, user_id: str, day: str, usage: TokenUsage, *, expires_at: int) -> None:
        await self._add(self._key(f"USER#{user_id}", day), usage, expires_at)

    async def get(self, user_id: str, day: str) -> DailyUsage:
        return await self._get(self._key(f"USER#{user_id}", day), day)

    # "SERVICE" can't clash with a user partition: those always start with "USER#".
    async def add_service(self, day: str, usage: TokenUsage, *, expires_at: int) -> None:
        await self._add(self._key("SERVICE", day), usage, expires_at)

    async def get_service(self, day: str) -> DailyUsage:
        return await self._get(self._key("SERVICE", day), day)

    async def _add(
        self, key: dict[str, dict[str, str]], usage: TokenUsage, expires_at: int
    ) -> None:
        # ADD is atomic on the server: concurrent requests never lose each other's tokens.
        await asyncio.to_thread(
            self._t.client.update_item,
            TableName=self._t.name,
            Key=key,
            UpdateExpression=(
                "ADD input_tokens :in, output_tokens :out, requests :one SET expires_at = :exp"
            ),
            ExpressionAttributeValues={
                ":in": {"N": str(usage.input_tokens)},
                ":out": {"N": str(usage.output_tokens)},
                ":one": {"N": "1"},
                ":exp": {"N": str(expires_at)},
            },
        )

    async def _get(self, key: dict[str, dict[str, str]], day: str) -> DailyUsage:
        response = await asyncio.to_thread(
            self._t.client.get_item,
            TableName=self._t.name,
            Key=key,
            ConsistentRead=True,
        )
        item = response.get("Item")
        if not item:
            return DailyUsage(day)

        def number(name: str) -> int:
            return int(item[name]["N"]) if name in item else 0

        return DailyUsage(day, number("input_tokens"), number("output_tokens"), number("requests"))
