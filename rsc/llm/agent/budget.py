"""Spend controls: token accounting, cooldowns, and daily caps.

None of this existed under the RAG pipeline -- the mention listener answered
every mention with no ceiling, no rate limit, and no record of what it cost.
"""

import logging
import time
from dataclasses import dataclass, field
from datetime import datetime

from openai.types.responses import ResponseUsage

log = logging.getLogger("red.rsc.llm.budget")
# Separate logger so spend can be routed to its own sink or grepped on its own.
usage_log = logging.getLogger("red.rsc.llm.usage")


@dataclass(slots=True)
class UsageAccumulator:
    """Token usage across every model call made answering one question.

    Shared with sub-agents so their spend counts against the same ceiling; a
    sub-agent that billed separately would defeat the circuit breaker.
    """

    input_tokens: int = 0
    cached_tokens: int = 0
    output_tokens: int = 0
    reasoning_tokens: int = 0
    calls: int = 0

    @property
    def total(self) -> int:
        return self.input_tokens + self.output_tokens

    def record(self, usage: ResponseUsage | None) -> None:
        if usage is None:
            return
        self.calls += 1
        self.input_tokens += getattr(usage, "input_tokens", 0) or 0
        self.output_tokens += getattr(usage, "output_tokens", 0) or 0
        input_details = getattr(usage, "input_tokens_details", None)
        if input_details is not None:
            self.cached_tokens += getattr(input_details, "cached_tokens", 0) or 0
        output_details = getattr(usage, "output_tokens_details", None)
        if output_details is not None:
            self.reasoning_tokens += getattr(output_details, "reasoning_tokens", 0) or 0


def log_usage(
    *,
    guild_id: int,
    user_id: int,
    surface: str,
    model: str,
    usage: UsageAccumulator,
    tools: list[str],
    iterations: int,
    elapsed: float,
) -> None:
    usage_log.info(
        "llm.usage guild=%s user=%s surface=%s iters=%s calls=%s tools=%s in=%s cached=%s out=%s reasoning=%s model=%s elapsed=%.1fs",
        guild_id,
        user_id,
        surface,
        iterations,
        usage.calls,
        ",".join(tools) or "-",
        usage.input_tokens,
        usage.cached_tokens,
        usage.output_tokens,
        usage.reasoning_tokens,
        model,
        elapsed,
    )


@dataclass(slots=True)
class CooldownTracker:
    """Per-user cooldown, held in memory.

    Intentionally not persisted: the value is only meaningful for seconds, and
    Red's Config writes go to disk. Losing it on reload is harmless -- unlike
    the daily cap, which must survive.
    """

    seconds: float
    _last: dict[tuple[int, int], float] = field(default_factory=dict)

    def retry_after(self, guild_id: int, user_id: int) -> float:
        expires = self._last.get((guild_id, user_id))
        if expires is None:
            return 0.0
        remaining = expires - time.monotonic()
        return max(remaining, 0.0)

    def start(self, guild_id: int, user_id: int) -> None:
        self._last[(guild_id, user_id)] = time.monotonic() + self.seconds

    def clear(self, guild_id: int, user_id: int) -> None:
        self._last.pop((guild_id, user_id), None)


def usage_day(now: datetime) -> str:
    """Calendar day key in the guild's timezone."""
    return now.strftime("%Y-%m-%d")
