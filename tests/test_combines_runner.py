import asyncio
import copy
import json
from unittest.mock import AsyncMock, MagicMock

import discord
import pytest

from rsc.combines import runner
from rsc.combines.runner import CombineRunnerMixIn

GUILD_ID = 395806681994493964


def _player(discord_id: int, team: str, match_id: int = 101) -> dict:
    return {
        "discord_id": str(discord_id),
        "rsc_id": f"RSC{discord_id}",
        "match_id": match_id,
        "team": team,
        "name": f"player{discord_id}",
    }


def _lobby_payload(match_id: int = 101, tier: str = "Premier") -> dict:
    return {
        "id": match_id,
        "lobby_user": "rsc",
        "lobby_pass": "rsc",
        "home_wins": 0,
        "away_wins": 0,
        "reported_rsc_id": None,
        "confirmed_rsc_id": None,
        "completed": False,
        "cancelled": False,
        "tier": tier,
        "guild_id": str(GUILD_ID),
        "home": [_player(i, "home", match_id) for i in (1, 2, 3)],
        "away": [_player(i, "away", match_id) for i in (4, 5, 6)],
    }


def _request(data=None, *, bad_json: bool = False):
    request = MagicMock()
    if bad_json:
        request.json = AsyncMock(side_effect=json.JSONDecodeError("bad", "", 0))
    else:
        request.json = AsyncMock(return_value=copy.deepcopy(data))
    return request


def _mixin(guild=None, *, active=True):
    saved = CombineRunnerMixIn.__abstractmethods__
    CombineRunnerMixIn.__abstractmethods__ = frozenset()
    try:
        m = object.__new__(CombineRunnerMixIn)
    finally:
        CombineRunnerMixIn.__abstractmethods__ = saved
    m.bot = MagicMock()
    m.bot.get_guild.return_value = guild
    m._get_combines_active = AsyncMock(return_value=active)
    m.create_combine_lobby_channel = AsyncMock(return_value=[])
    return m


class TestStartCombinesGame:
    async def test_bad_json_is_400(self):
        resp = await _mixin().start_combines_game(_request(bad_json=True))
        assert resp.status == 400

    @pytest.mark.parametrize("data", [{}, [], "lobby"])
    async def test_empty_or_non_object_body_is_400(self, data):
        resp = await _mixin().start_combines_game(_request(data))
        assert resp.status == 400

    async def test_invalid_lobby_is_400(self):
        payload = _lobby_payload()
        del payload["tier"]
        resp = await _mixin(MagicMock()).start_combines_game(_request({"101": payload}))
        assert resp.status == 400

    async def test_not_in_guild_is_503(self):
        m = _mixin(None)

        resp = await m.start_combines_game(_request({"101": _lobby_payload()}))

        assert resp.status == 503
        m.create_combine_lobby_channel.assert_not_called()

    async def test_inactive_is_503(self):
        m = _mixin(MagicMock(), active=False)

        resp = await m.start_combines_game(_request({"101": _lobby_payload()}))

        assert resp.status == 503
        m.create_combine_lobby_channel.assert_not_called()

    async def test_responds_before_lobbies_are_created(self):
        m = _mixin(MagicMock())

        resp = await m.start_combines_game(_request({"101": _lobby_payload(101), "102": _lobby_payload(102)}))

        assert resp.status == 200
        m.create_combine_lobby_channel.assert_not_called()
        await asyncio.gather(*runner.background_tasks)
        assert [c.args[0].id for c in m.create_combine_lobby_channel.await_args_list] == [101, 102]

    async def test_failed_lobby_does_not_stop_the_rest(self):
        m = _mixin(MagicMock())
        m.create_combine_lobby_channel.side_effect = [discord.HTTPException(MagicMock(status=500), "boom"), []]

        resp = await m.start_combines_game(_request({"101": _lobby_payload(101), "102": _lobby_payload(102)}))
        await asyncio.gather(*runner.background_tasks)

        assert resp.status == 200
        assert m.create_combine_lobby_channel.await_count == 2
