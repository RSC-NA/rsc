from unittest.mock import AsyncMock, MagicMock

import discord
import pytest

from rsc.freeagents.freeagents import FreeAgentMixIn
from rsc.types import CheckIn

GUILD_ID = 395806681994493964


def _create_mixin(**attrs):
    saved = FreeAgentMixIn.__abstractmethods__
    FreeAgentMixIn.__abstractmethods__ = frozenset()
    try:
        m = object.__new__(FreeAgentMixIn)
    finally:
        FreeAgentMixIn.__abstractmethods__ = saved
    for k, v in attrs.items():
        setattr(m, k, v)
    return m


def _make_checkin(player_id=111, tier="Premier", visible=True, date="2025-03-15T12:00:00-05:00") -> CheckIn:
    return CheckIn(date=date, player=player_id, tier=tier, visible=visible)


# --- checkins_by_tier ---


class TestCheckinsByTier:
    async def test_returns_matching_tier(self, mock_guild):
        c1 = _make_checkin(player_id=1, tier="Premier")
        c2 = _make_checkin(player_id=2, tier="Master")
        c3 = _make_checkin(player_id=3, tier="Premier")
        mixin = _create_mixin(_check_ins={mock_guild.id: [c1, c2, c3]})

        result = await mixin.checkins_by_tier(mock_guild, "Premier")
        assert len(result) == 2
        assert all(c["tier"] == "Premier" for c in result)

    async def test_returns_empty_when_no_cache(self, mock_guild):
        mixin = _create_mixin(_check_ins={})

        result = await mixin.checkins_by_tier(mock_guild, "Premier")
        assert result == []

    async def test_returns_empty_when_no_match(self, mock_guild):
        c1 = _make_checkin(tier="Master")
        mixin = _create_mixin(_check_ins={mock_guild.id: [c1]})

        result = await mixin.checkins_by_tier(mock_guild, "Premier")
        assert result == []


# --- checkins ---


class TestCheckins:
    async def test_returns_all_checkins(self, mock_guild):
        c1 = _make_checkin(player_id=1)
        c2 = _make_checkin(player_id=2)
        mixin = _create_mixin(_check_ins={mock_guild.id: [c1, c2]})

        result = await mixin.checkins(mock_guild)
        assert len(result) == 2

    async def test_returns_empty_when_no_guild(self, mock_guild):
        mixin = _create_mixin(_check_ins={})

        result = await mixin.checkins(mock_guild)
        assert result == []


# --- clear_checkins_by_tier ---


class TestClearCheckinsByTier:
    async def test_clears_tier(self, mock_guild):
        c1 = _make_checkin(player_id=1, tier="Premier")
        c2 = _make_checkin(player_id=2, tier="Master")
        mixin = _create_mixin(_check_ins={mock_guild.id: [c1, c2]})
        mixin._get_check_ins = AsyncMock(return_value=[c1, c2])
        mixin._save_check_ins = AsyncMock()

        await mixin.clear_checkins_by_tier(mock_guild, "Premier")
        assert len(mixin._check_ins[mock_guild.id]) == 1
        assert mixin._check_ins[mock_guild.id][0]["tier"] == "Master"

    async def test_noop_when_no_cache(self, mock_guild):
        mixin = _create_mixin(_check_ins={})

        await mixin.clear_checkins_by_tier(mock_guild, "Premier")
        assert mock_guild.id not in mixin._check_ins


# --- clear_all_checkins ---


class TestClearAllCheckins:
    async def test_clears_all(self, mock_guild):
        c1 = _make_checkin(player_id=1)
        mixin = _create_mixin(_check_ins={mock_guild.id: [c1]})
        mixin._save_check_ins = AsyncMock()

        await mixin.clear_all_checkins(mock_guild)
        assert mixin._check_ins[mock_guild.id] == []


# --- add_checkin ---


class TestAddCheckin:
    async def test_adds_checkin(self, mock_guild):
        c1 = _make_checkin(player_id=1)
        mixin = _create_mixin(_check_ins={mock_guild.id: []})
        mixin._get_check_ins = AsyncMock(return_value=[])
        mixin._save_check_ins = AsyncMock()

        await mixin.add_checkin(mock_guild, c1)
        assert len(mixin._check_ins[mock_guild.id]) == 1


# --- remove_checkin ---


class TestRemoveCheckin:
    async def test_removes_checkin(self, mock_guild):
        c1 = _make_checkin(player_id=1)
        c2 = _make_checkin(player_id=2)
        mixin = _create_mixin(_check_ins={mock_guild.id: [c1, c2]})
        mixin._get_check_ins = AsyncMock(return_value=[c1, c2])
        mixin._save_check_ins = AsyncMock()

        await mixin.remove_checkin(mock_guild, c1)
        assert len(mixin._check_ins[mock_guild.id]) == 1
        assert mixin._check_ins[mock_guild.id][0]["player"] == 2


# --- is_checked_in ---


class TestIsCheckedIn:
    async def test_checked_in(self, mock_guild, mock_member):
        c1 = _make_checkin(player_id=mock_member.id)
        mixin = _create_mixin(_check_ins={mock_guild.id: [c1]})

        assert await mixin.is_checked_in(mock_member) is True

    async def test_not_checked_in(self, mock_guild, mock_member):
        c1 = _make_checkin(player_id=999999)
        mixin = _create_mixin(_check_ins={mock_guild.id: [c1]})

        assert await mixin.is_checked_in(mock_member) is False

    async def test_no_cache(self, mock_guild, mock_member):
        mixin = _create_mixin(_check_ins={})

        assert await mixin.is_checked_in(mock_member) is False


# --- get_checkin ---


class TestGetCheckin:
    async def test_returns_checkin(self, mock_guild, mock_member):
        c1 = _make_checkin(player_id=mock_member.id, tier="Premier")
        mixin = _create_mixin(_check_ins={mock_guild.id: [c1]})

        result = await mixin.get_checkin(mock_member)
        assert result is not None
        assert result["tier"] == "Premier"

    async def test_returns_none_when_not_found(self, mock_guild, mock_member):
        c1 = _make_checkin(player_id=999999)
        mixin = _create_mixin(_check_ins={mock_guild.id: [c1]})

        result = await mixin.get_checkin(mock_member)
        assert result is None

    async def test_returns_none_when_no_cache(self, mock_guild, mock_member):
        mixin = _create_mixin(_check_ins={})

        result = await mixin.get_checkin(mock_member)
        assert result is None


# --- update_freeagent_visibility ---


class TestUpdateFreeagentVisibility:
    async def test_sets_visibility(self, mock_guild, mock_member):
        c1 = _make_checkin(player_id=mock_member.id, visible=True)
        mixin = _create_mixin(_check_ins={mock_guild.id: [c1]})
        mixin._get_check_ins = AsyncMock(return_value=[c1])
        mixin._save_check_ins = AsyncMock()

        await mixin.update_freeagent_visibility(mock_guild, mock_member, False)
        assert mixin._check_ins[mock_guild.id][0]["visible"] is False


# --- free_agents / permanent_free_agents ---


class TestFreeAgentsApi:
    async def test_free_agents_calls_players(self, mock_guild):
        mixin = _create_mixin()
        mixin.players = AsyncMock(return_value=[MagicMock()])

        result = await mixin.free_agents(mock_guild, tier_name="Premier")
        assert len(result) == 1
        mixin.players.assert_awaited_once()

    async def test_permanent_free_agents_calls_players(self, mock_guild):
        mixin = _create_mixin()
        mixin.players = AsyncMock(return_value=[MagicMock()])

        result = await mixin.permanent_free_agents(mock_guild, tier_name="Premier")
        assert len(result) == 1
        mixin.players.assert_awaited_once()
