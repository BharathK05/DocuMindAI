"""Daily token quotas: per user, plus an optional cap for all users together.

Check-then-charge: the quota is checked before a request and the real token count is added
after it (only then do we know it). A user can therefore exceed the quota by at most one
request (a few thousand tokens), which is far simpler than reserving an estimate up front.
The service-wide cap works the same way, so it can be overshot by at most the requests in
flight when it's reached.
"""

import asyncio
import logging
import time
from collections.abc import Callable
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta

from documind.core.config import Settings
from documind.core.errors import QuotaExceededError, ServiceQuotaExceededError
from documind.domain import TokenUsage
from documind.repositories.base import UsageRepository

logger = logging.getLogger(__name__)

_KEEP_DAYS = 35  # daily counters stay queryable for a month, then TTL deletes them


@dataclass(frozen=True, slots=True)
class AccountUsage:
    tokens_used_today: int
    daily_quota: int
    reset_at: datetime  # next UTC midnight
    cost_usd_today: float

    @property
    def remaining(self) -> int:
        return max(0, self.daily_quota - self.tokens_used_today)


def cost_usd(usage: TokenUsage, settings: Settings) -> float:
    return (
        usage.input_tokens * settings.chat_input_usd_per_mtok
        + usage.output_tokens * settings.chat_output_usd_per_mtok
    ) / 1_000_000


class UsageService:
    def __init__(
        self, settings: Settings, usage: UsageRepository, clock: Callable[[], float] = time.time
    ) -> None:
        self._settings = settings
        self._usage = usage
        self._clock = clock

    def _now(self) -> datetime:
        return datetime.fromtimestamp(self._clock(), UTC)

    def _day_bounds(self) -> tuple[str, datetime]:
        now = self._now()
        midnight = datetime(now.year, now.month, now.day, tzinfo=UTC) + timedelta(days=1)
        return now.date().isoformat(), midnight

    async def account(self, user_id: str) -> AccountUsage:
        day, reset_at = self._day_bounds()
        used = await self._usage.get(user_id, day)
        spent = TokenUsage(used.input_tokens, used.output_tokens)
        return AccountUsage(
            tokens_used_today=used.total_tokens,
            daily_quota=self._settings.daily_token_quota,
            reset_at=reset_at,
            cost_usd_today=round(cost_usd(spent, self._settings), 6),
        )

    async def ensure_within_quota(self, user_id: str) -> None:
        account = await self.account(user_id)
        retry_after = max(1, int((account.reset_at - self._now()).total_seconds()))
        if account.remaining <= 0:
            raise QuotaExceededError(
                f"Daily limit of {account.daily_quota:,} tokens reached. "
                f"It resets at {account.reset_at:%H:%M} UTC.",
                retry_after,
            )
        cap = self._settings.global_daily_token_quota
        if cap > 0:
            day, _ = self._day_bounds()
            if (await self._usage.get_service(day)).total_tokens >= cap:
                logger.warning("service-wide daily token cap reached", extra={"cap": cap})
                raise ServiceQuotaExceededError(
                    "DocuMind has reached its usage limit for today. "
                    f"It resets at {account.reset_at:%H:%M} UTC.",
                    retry_after,
                )

    async def record(self, user_id: str, usage: TokenUsage) -> None:
        if usage.input_tokens == 0 and usage.output_tokens == 0:
            return
        day, reset_at = self._day_bounds()
        expires_at = int((reset_at + timedelta(days=_KEEP_DAYS)).timestamp())
        writes = [self._usage.add(user_id, day, usage, expires_at=expires_at)]
        if self._settings.global_daily_token_quota > 0:
            writes.append(self._usage.add_service(day, usage, expires_at=expires_at))
        await asyncio.gather(*writes)
