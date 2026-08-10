"""Tests for the agent's spend controls.

None of this existed under the RAG pipeline: the mention listener answered every
mention with no rate limit, no cap, and no record of what it cost.
"""

from datetime import UTC, datetime, timedelta
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock

import discord
import pytest

from rsc.llm.agent.budget import CooldownTracker, UsageAccumulator, usage_day
from rsc.llm.agent.cache import ToolCache, cache_key
from rsc.llm.agent.service import check_budget

NOW = datetime(2026, 8, 10, 12, 0, tzinfo=UTC)


class FakeRecord:
    """Stands in for a Red Config custom group."""

    def __init__(self, store: dict, key: tuple):
        self._store = store
        self._key = key

    def _get(self, field: str):
        return self._store.get(self._key, {}).get(field)

    def __getattr__(self, field: str):
        async def getter():
            return self._get(field)

        async def setter(value):
            self._store.setdefault(self._key, {})[field] = value

        getter.set = setter  # type: ignore[attr-defined]
        return getter


class FakeConfig:
    def __init__(self):
        self.store: dict = {}

    def custom(self, _scope: str, *identifiers: str) -> FakeRecord:
        return FakeRecord(self.store, tuple(identifiers))


@pytest.fixture
def guild():
    mock = MagicMock()
    mock.id = 1
    return mock


@pytest.fixture
def member():
    # spec= matters: the elevated-role bypass is guarded by
    # isinstance(member, discord.Member), which a bare MagicMock fails.
    mock = MagicMock(spec=discord.Member)
    mock.id = 100
    return mock


@pytest.fixture
def cog():
    mock = MagicMock()
    mock.config = FakeConfig()
    mock.elevated_positions = AsyncMock(return_value=frozenset())
    return mock


def seed_usage(cog, guild_id: int, user_id: int, *, day: str, count: int) -> None:
    cog.config.store[(str(guild_id), str(user_id))] = {"day": day, "count": count, "tokens": 0}


# Cooldown


def test_cooldown_blocks_then_expires(monkeypatch):
    clock = {"now": 1000.0}
    monkeypatch.setattr("rsc.llm.agent.budget.time.monotonic", lambda: clock["now"])
    tracker = CooldownTracker(seconds=20)

    assert tracker.retry_after(1, 100) == 0
    tracker.start(1, 100)
    assert tracker.retry_after(1, 100) == pytest.approx(20)

    clock["now"] += 21
    assert tracker.retry_after(1, 100) == 0


def test_cooldown_is_per_user(monkeypatch):
    monkeypatch.setattr("rsc.llm.agent.budget.time.monotonic", lambda: 1000.0)
    tracker = CooldownTracker(seconds=20)

    tracker.start(1, 100)

    assert tracker.retry_after(1, 200) == 0


def test_cooldown_can_be_cleared(monkeypatch):
    """A failed question should not burn the asker's cooldown."""
    monkeypatch.setattr("rsc.llm.agent.budget.time.monotonic", lambda: 1000.0)
    tracker = CooldownTracker(seconds=20)

    tracker.start(1, 100)
    tracker.clear(1, 100)

    assert tracker.retry_after(1, 100) == 0


async def test_check_budget_reports_cooldown(cog, guild, member, monkeypatch):
    monkeypatch.setattr("rsc.llm.agent.budget.time.monotonic", lambda: 1000.0)
    tracker = CooldownTracker(seconds=20)
    tracker.start(guild.id, member.id)

    verdict = await check_budget(cog, guild, member, cooldown=tracker, user_cap=15, guild_cap=400, now=NOW)

    assert not verdict.allowed
    assert verdict.reason == "cooldown"
    assert verdict.rate_limited


# Daily caps


async def test_user_cap_blocks_at_the_limit(cog, guild, member):
    seed_usage(cog, guild.id, member.id, day=usage_day(NOW), count=15)

    verdict = await check_budget(
        cog, guild, member, cooldown=CooldownTracker(seconds=0), user_cap=15, guild_cap=400, now=NOW
    )

    assert not verdict.allowed
    assert verdict.reason == "user_cap"


async def test_usage_resets_on_a_new_day(cog, guild, member):
    """Counters key off the day, so yesterday's total must not carry over."""
    yesterday = usage_day(NOW - timedelta(days=1))
    seed_usage(cog, guild.id, member.id, day=yesterday, count=15)

    verdict = await check_budget(
        cog, guild, member, cooldown=CooldownTracker(seconds=0), user_cap=15, guild_cap=400, now=NOW
    )

    assert verdict.allowed


async def test_guild_cap_blocks_everyone(cog, guild, member):
    seed_usage(cog, guild.id, 0, day=usage_day(NOW), count=400)

    verdict = await check_budget(
        cog, guild, member, cooldown=CooldownTracker(seconds=0), user_cap=15, guild_cap=400, now=NOW
    )

    assert not verdict.allowed
    assert verdict.reason == "guild_cap"


async def test_elevated_members_bypass_the_user_cap(cog, guild, member):
    seed_usage(cog, guild.id, member.id, day=usage_day(NOW), count=999)
    cog.elevated_positions.return_value = frozenset({"ADM"})

    verdict = await check_budget(
        cog, guild, member, cooldown=CooldownTracker(seconds=0), user_cap=15, guild_cap=400, now=NOW
    )

    assert verdict.allowed


async def test_elevated_members_do_not_bypass_the_guild_cap(cog, guild, member):
    """Staff should not be able to exhaust the whole budget alone."""
    seed_usage(cog, guild.id, 0, day=usage_day(NOW), count=400)
    cog.elevated_positions.return_value = frozenset({"ADM"})

    verdict = await check_budget(
        cog, guild, member, cooldown=CooldownTracker(seconds=0), user_cap=15, guild_cap=400, now=NOW
    )

    assert not verdict.allowed


async def test_zero_cap_disables_the_limit(cog, guild, member):
    seed_usage(cog, guild.id, member.id, day=usage_day(NOW), count=9999)

    verdict = await check_budget(
        cog, guild, member, cooldown=CooldownTracker(seconds=0), user_cap=0, guild_cap=0, now=NOW
    )

    assert verdict.allowed


async def test_role_lookup_failure_does_not_block_the_question(cog, guild, member):
    """An elevated-role lookup is an optimisation, not a gate."""
    cog.elevated_positions.side_effect = RuntimeError("api down")

    verdict = await check_budget(
        cog, guild, member, cooldown=CooldownTracker(seconds=0), user_cap=15, guild_cap=400, now=NOW
    )

    assert verdict.allowed


# Usage accounting


def test_usage_accumulator_sums_across_calls():
    usage = UsageAccumulator()

    usage.record(
        SimpleNamespace(
            input_tokens=100,
            output_tokens=10,
            input_tokens_details=SimpleNamespace(cached_tokens=90),
            output_tokens_details=SimpleNamespace(reasoning_tokens=5),
        )
    )
    usage.record(
        SimpleNamespace(
            input_tokens=200,
            output_tokens=20,
            input_tokens_details=SimpleNamespace(cached_tokens=180),
            output_tokens_details=SimpleNamespace(reasoning_tokens=0),
        )
    )

    assert usage.total == 330
    assert usage.cached_tokens == 270
    assert usage.reasoning_tokens == 5
    assert usage.calls == 2


def test_usage_accumulator_tolerates_missing_usage():
    usage = UsageAccumulator()

    usage.record(None)

    assert usage.total == 0
    assert usage.calls == 0


# Tool cache


async def test_cache_serves_repeats_without_refetching():
    cache = ToolCache(ttl=60, maxsize=8)
    fetch = AsyncMock(return_value="value")
    key = cache_key(1, "list_franchises", {})

    assert await cache.get_or_fetch(key, fetch) == "value"
    assert await cache.get_or_fetch(key, fetch) == "value"
    assert fetch.await_count == 1


async def test_cache_expires_entries(monkeypatch):
    clock = {"now": 0.0}
    monkeypatch.setattr("rsc.llm.agent.cache.time.monotonic", lambda: clock["now"])
    cache = ToolCache(ttl=60, maxsize=8)
    fetch = AsyncMock(side_effect=["first", "second"])
    key = cache_key(1, "list_franchises", {})

    assert await cache.get_or_fetch(key, fetch) == "first"
    clock["now"] = 61
    assert await cache.get_or_fetch(key, fetch) == "second"


async def test_cache_separates_guilds_and_arguments():
    cache = ToolCache(ttl=60, maxsize=8)
    fetch = AsyncMock(side_effect=["a", "b", "c"])

    assert await cache.get_or_fetch(cache_key(1, "t", {}), fetch) == "a"
    assert await cache.get_or_fetch(cache_key(2, "t", {}), fetch) == "b"
    assert await cache.get_or_fetch(cache_key(1, "t", {"tier": "Master"}), fetch) == "c"


async def test_cache_evicts_beyond_maxsize():
    cache = ToolCache(ttl=60, maxsize=2)
    fetch = AsyncMock(return_value="v")

    for i in range(3):
        await cache.get_or_fetch(cache_key(1, "t", {"i": i}), fetch)

    assert len(cache._entries) == 2
