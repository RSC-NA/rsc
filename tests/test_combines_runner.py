import asyncio
import copy
import json
from unittest.mock import AsyncMock, MagicMock, patch

import discord
import pytest

from rsc.combines import models, runner
from rsc.combines.lobby import LobbyMessages
from rsc.combines.runner import CombineRunnerMixIn
from rsc.combines.views import LobbyCard, LobbyKind, LobbyScore
from rsc.exceptions import BadGateway

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


@pytest.fixture(autouse=True)
def _clear_active_lobbies():
    runner.active_lobbies.clear()
    yield
    runner.active_lobbies.clear()


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
    # No stored lobby card, so teardown has nothing to mark Final
    m.config = MagicMock()
    m.config.custom.return_value.LobbyMessages = AsyncMock(return_value={})
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


class TestDuplicateLobbies:
    async def test_concurrent_duplicate_is_created_once(self):
        guild = MagicMock()
        guild.id = GUILD_ID
        m = _mixin(guild)
        m.create_combine_lobby_channel.return_value = [MagicMock(), MagicMock()]

        first = await m.start_combines_game(_request({"101": _lobby_payload()}))
        second = await m.start_combines_game(_request({"101": _lobby_payload()}))
        await asyncio.gather(*runner.background_tasks)

        assert (first.status, second.status) == (200, 200)
        m.create_combine_lobby_channel.assert_awaited_once()

    async def test_lobby_that_created_nothing_can_be_retried(self):
        m = _mixin(MagicMock())

        for _ in range(2):
            await m.start_combines_game(_request({"101": _lobby_payload()}))
            await asyncio.gather(*runner.background_tasks)

        assert m.create_combine_lobby_channel.await_count == 2

    async def test_teardown_allows_lobby_again(self):
        guild = MagicMock()
        guild.id = GUILD_ID
        guild.channels = []
        m = _mixin(guild)
        m.create_combine_lobby_channel.return_value = [MagicMock(), MagicMock()]

        await m.start_combines_game(_request({"101": _lobby_payload()}))
        await asyncio.gather(*runner.background_tasks)
        with patch("rsc.combines.runner.asyncio.sleep", AsyncMock()):
            await m.teardown_combine_lobby(guild, lobby_id=101)
        await m.start_combines_game(_request({"101": _lobby_payload()}))
        await asyncio.gather(*runner.background_tasks)

        assert m.create_combine_lobby_channel.await_count == 2


def _entry(executor_id: int | None = 1) -> LobbyMessages:
    card = LobbyCard(
        kind=LobbyKind.COMBINE,
        lobby_id=101,
        tier="Premier",
        lobby_name="rsc",
        lobby_pass="rsc",
        home=("<@1>",),
        away=("<@4>",),
        lobby_maker="P1",
        home_vc_url=None,
        away_vc_url=None,
        match_url="https://devleague.rscna.com/combine/101",
        started_at=discord.utils.utcnow(),
    )
    return LobbyMessages(card=card, channel_id=1, message_id=2, executor_id=executor_id)


class TestCombineFinalScore:
    def _mixin(self) -> CombineRunnerMixIn:
        m = _mixin()
        m._get_combines_api = AsyncMock(return_value="https://combines.example/api/")
        return m

    def _guild(self) -> MagicMock:
        guild = MagicMock()
        guild.get_member.return_value = MagicMock(spec=discord.Member)
        return guild

    async def test_reads_the_score_from_the_api(self):
        finished = models.CombinesLobby.model_validate({**_lobby_payload(), "home_wins": 3, "away_wins": 1, "completed": True})
        with patch("rsc.combines.runner.api.combines_lobby", AsyncMock(return_value=finished)) as lookup:
            score = await self._mixin()._combine_final_score(self._guild(), _entry())
        assert score == LobbyScore(home_wins=3, away_wins=1)
        assert lookup.await_args is not None and lookup.await_args.kwargs["lobby_id"] == 101

    async def test_cancelled_lobby_has_no_score(self):
        cancelled = models.CombinesLobby.model_validate({**_lobby_payload(), "cancelled": True})
        with patch("rsc.combines.runner.api.combines_lobby", AsyncMock(return_value=cancelled)):
            assert await self._mixin()._combine_final_score(self._guild(), _entry()) is None

    async def test_api_status_reply_or_error_has_no_score(self):
        status = models.CombinesStatus(status="error", message="nope")
        with patch("rsc.combines.runner.api.combines_lobby", AsyncMock(return_value=status)):
            assert await self._mixin()._combine_final_score(self._guild(), _entry()) is None
        with patch("rsc.combines.runner.api.combines_lobby", AsyncMock(side_effect=BadGateway("down"))):
            assert await self._mixin()._combine_final_score(self._guild(), _entry()) is None

    async def test_no_executor_skips_the_lookup(self):
        with patch("rsc.combines.runner.api.combines_lobby", AsyncMock()) as lookup:
            assert await self._mixin()._combine_final_score(self._guild(), _entry(executor_id=None)) is None
        lookup.assert_not_awaited()
