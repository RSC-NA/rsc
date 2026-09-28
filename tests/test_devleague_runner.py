import asyncio
import copy
import json
from unittest.mock import AsyncMock, MagicMock, patch

import discord
import pytest

from rsc.devleague import runner
from rsc.devleague.models import DevLeagueLobby
from rsc.devleague.runner import DevLeagueRunnerMixIn

GUILD_ID = 991044575567179856


def _player(discord_id: int, team: str, match_id: int = 101) -> dict:
    return {
        "discord_id": str(discord_id),
        "rsc_id": f"RSC{discord_id}",
        "match_id": match_id,
        "team": team,
        "name": f"player{discord_id}",
    }


def _lobby_payload(match_id: int = 101, tier: str = "S+") -> dict:
    return {
        "id": match_id,
        "lobby_user": "dl",
        "lobby_pass": "rsc",
        "home_wins": 0,
        "away_wins": 0,
        "reported_rsc_id": None,
        "confirmed_rsc_id": None,
        "completed": 0,
        "cancelled": 0,
        "tier": tier,
        "guild_id": str(GUILD_ID),
        "home": [_player(i, "home", match_id) for i in (1, 2, 3)],
        "away": [_player(i, "away", match_id) for i in (4, 5, 6)],
    }


def _event_payload(message_type: str = "Finished Game", match_id: int | None = 101) -> dict:
    return {
        "actor": {"nickname": "nickm", "discord_id": 1},
        "status": "success",
        "message_type": message_type,
        "message": "done",
        "match_id": match_id,
        "guild_id": str(GUILD_ID),
    }


def _request(data=None, *, bad_json: bool = False):
    request = MagicMock()
    if bad_json:
        request.json = AsyncMock(side_effect=json.JSONDecodeError("bad", "", 0))
    else:
        request.json = AsyncMock(return_value=copy.deepcopy(data))
    return request


def _channel(name: str, channel_id: int, position: int = 0):
    channel = MagicMock(spec=discord.VoiceChannel)
    channel.name = name
    channel.id = channel_id
    channel.position = position
    channel.delete = AsyncMock()
    return channel


def _member(member_id: int):
    member = MagicMock(spec=discord.Member)
    member.id = member_id
    member.mention = f"<@{member_id}>"
    return member


def _guild(channels=None):
    guild = MagicMock(spec=discord.Guild)
    guild.id = GUILD_ID
    guild.icon = None
    guild.channels = channels or []
    guild.categories = []
    guild.default_role = MagicMock(spec=discord.Role)
    guild.get_member.return_value = None
    return guild


def _category(guild, voice_channels=None):
    category = MagicMock(spec=discord.CategoryChannel)
    category.name = "Dev League"
    category.guild = guild
    category.channels = list(voice_channels or [])
    category.voice_channels = list(voice_channels or [])
    created = iter(range(9000, 9100))

    async def create_voice_channel(name, **kwargs):
        channel = _channel(name, next(created))
        channel.overwrites = kwargs["overwrites"]
        return channel

    category.create_voice_channel = AsyncMock(side_effect=create_voice_channel)
    return category


def _mixin(guild=None, category=None, *, active=True, announce_channel=None, players=None):
    saved = DevLeagueRunnerMixIn.__abstractmethods__
    DevLeagueRunnerMixIn.__abstractmethods__ = frozenset()
    try:
        m = object.__new__(DevLeagueRunnerMixIn)
    finally:
        DevLeagueRunnerMixIn.__abstractmethods__ = saved
    m.bot = MagicMock()
    m.bot.get_guild.return_value = guild
    m._get_devleague_active = AsyncMock(return_value=active)
    m._get_devleague_category = AsyncMock(return_value=category)
    m._get_devleague_announce_channel = AsyncMock(return_value=announce_channel)
    m.combine_players_from_lobby = AsyncMock(return_value=players if players is not None else [_member(i) for i in range(1, 7)])
    return m


class TestStartDevLeagueGame:
    async def test_bad_json_is_400(self):
        resp = await _mixin().start_devleague_game(_request(bad_json=True))
        assert resp.status == 400

    async def test_invalid_lobby_is_400(self):
        payload = _lobby_payload()
        del payload["tier"]
        resp = await _mixin().start_devleague_game(_request({"101": payload}))
        assert resp.status == 400

    @pytest.mark.parametrize("data", [{}, []])
    async def test_empty_or_non_object_body_is_400(self, data):
        resp = await _mixin().start_devleague_game(_request(data))
        assert resp.status == 400

    async def test_not_in_guild_is_503(self):
        resp = await _mixin(guild=None).start_devleague_game(_request({"101": _lobby_payload()}))
        assert resp.status == 503

    async def test_disabled_is_503_and_creates_nothing(self):
        guild = _guild()
        category = _category(guild)
        m = _mixin(guild, category, active=False)

        resp = await m.start_devleague_game(_request({"101": _lobby_payload()}))

        assert resp.status == 503
        category.create_voice_channel.assert_not_called()

    async def test_creates_every_lobby(self):
        m = _mixin(_guild())
        m.create_devleague_lobby_channels = AsyncMock(return_value=[])

        resp = await m.start_devleague_game(_request({"101": _lobby_payload(101, "S+"), "102": _lobby_payload(102, "B")}))

        assert resp.status == 200
        tiers = [c.args[0].tier for c in m.create_devleague_lobby_channels.await_args_list]
        assert tiers == ["S+", "B"]


class TestCreateDevLeagueLobbyChannels:
    async def test_creates_slugged_channels_for_players_only(self):
        guild = _guild()
        category = _category(guild)
        players = [_member(i) for i in range(1, 7)]
        m = _mixin(guild, category, players=players)
        m._sort_devleague_lobby = AsyncMock()

        home, away = await m.create_devleague_lobby_channels(DevLeagueLobby(**_lobby_payload()))

        assert (home.name, away.name) == ("splus-101-home", "splus-101-away")
        for channel in (home, away):
            assert set(channel.overwrites) == {guild.default_role, *players}
            assert channel.overwrites[guild.default_role].connect is False
            assert all(channel.overwrites[p].connect for p in players)
        m._sort_devleague_lobby.assert_awaited_once_with(category, home, away)

    async def test_announces_when_channel_configured(self):
        guild = _guild()
        announce = MagicMock(spec=discord.TextChannel)
        m = _mixin(guild, _category(guild), announce_channel=announce)
        m._sort_devleague_lobby = AsyncMock()
        m.announce_devleague_lobby = AsyncMock()

        channels = await m.create_devleague_lobby_channels(DevLeagueLobby(**_lobby_payload()))

        m.announce_devleague_lobby.assert_awaited_once()
        assert m.announce_devleague_lobby.await_args.kwargs["channels"] == channels
        assert m.announce_devleague_lobby.await_args.kwargs["announce_channel"] is announce

    async def test_no_announcement_channel_skips_announce(self):
        guild = _guild()
        m = _mixin(guild, _category(guild))
        m._sort_devleague_lobby = AsyncMock()
        m.announce_devleague_lobby = AsyncMock()

        channels = await m.create_devleague_lobby_channels(DevLeagueLobby(**_lobby_payload()))

        assert len(channels) == 2
        m.announce_devleague_lobby.assert_not_called()

    async def test_sort_failure_still_returns_channels(self):
        guild = _guild()
        m = _mixin(guild, _category(guild))
        m._sort_devleague_lobby = AsyncMock(side_effect=discord.HTTPException(MagicMock(status=500), "boom"))

        channels = await m.create_devleague_lobby_channels(DevLeagueLobby(**_lobby_payload()))

        assert len(channels) == 2

    async def test_existing_lobby_is_skipped(self):
        guild = _guild(channels=[_channel("splus-101-home", 1)])
        category = _category(guild)
        m = _mixin(guild, category)

        assert await m.create_devleague_lobby_channels(DevLeagueLobby(**_lobby_payload())) == []
        category.create_voice_channel.assert_not_called()

    async def test_no_players_in_guild_is_skipped(self):
        guild = _guild()
        category = _category(guild)
        m = _mixin(guild, category, players=[])

        assert await m.create_devleague_lobby_channels(DevLeagueLobby(**_lobby_payload())) == []
        category.create_voice_channel.assert_not_called()

    async def test_no_category_is_skipped(self):
        m = _mixin(_guild(), None)
        assert await m.create_devleague_lobby_channels(DevLeagueLobby(**_lobby_payload())) == []


class TestSortDevLeagueLobby:
    async def test_inserts_new_lobby_in_tier_order(self):
        guild = _guild()
        guild._state = MagicMock()
        guild._state.http.bulk_channel_update = AsyncMock()
        existing = [
            _channel("waiting-room", 1, position=0),
            _channel("splus-1-home", 2, position=1),
            _channel("splus-1-away", 3, position=2),
            _channel("c-2-home", 4, position=3),
            _channel("c-2-away", 5, position=4),
        ]
        home, away = _channel("a-3-home", 10, position=5), _channel("a-3-away", 11, position=6)
        # The cache may or may not already hold the new channels.
        category = _category(guild, [*existing, home])

        await DevLeagueRunnerMixIn._sort_devleague_lobby(MagicMock(), category, home, away)

        payload = guild._state.http.bulk_channel_update.await_args.args[1]
        assert [p["id"] for p in payload] == [1, 2, 3, 10, 11, 4, 5]
        assert [p["position"] for p in payload] == list(range(7))

    async def test_lowest_tier_goes_last(self):
        guild = _guild()
        guild._state = MagicMock()
        guild._state.http.bulk_channel_update = AsyncMock()
        existing = [_channel("s-1-home", 1, 0), _channel("s-1-away", 2, 1)]
        home, away = _channel("f-3-home", 10), _channel("f-3-away", 11)

        await DevLeagueRunnerMixIn._sort_devleague_lobby(MagicMock(), _category(guild, existing), home, away)

        payload = guild._state.http.bulk_channel_update.await_args.args[1]
        assert [p["id"] for p in payload] == [1, 2, 10, 11]


class TestDevLeagueEventHandler:
    async def test_finished_schedules_teardown(self):
        guild = _guild()
        m = _mixin(guild)
        m.teardown_devleague_lobby = AsyncMock()

        resp = await m.devleague_event_handler(_request(_event_payload()))
        await asyncio.gather(*runner.background_tasks)

        assert resp.status == 200
        m.teardown_devleague_lobby.assert_awaited_once_with(guild, lobby_id=101)

    async def test_finished_without_match_id_is_400(self):
        resp = await _mixin(_guild()).devleague_event_handler(_request(_event_payload(match_id=None)))
        assert resp.status == 400

    async def test_other_event_is_501(self):
        resp = await _mixin(_guild()).devleague_event_handler(_request(_event_payload("Checked In")))
        assert resp.status == 501

    async def test_unknown_guild_is_503(self):
        resp = await _mixin(None).devleague_event_handler(_request(_event_payload()))
        assert resp.status == 503

    @pytest.mark.parametrize("data", [None, {"match_id": 1}])
    async def test_bad_payload_is_400(self, data):
        request = _request(bad_json=True) if data is None else _request(data)
        resp = await _mixin(_guild()).devleague_event_handler(request)
        assert resp.status == 400


class TestTeardownDevLeagueLobby:
    async def test_deletes_only_matching_lobby_across_overflow(self):
        guild = _guild()
        keep = [_channel("splus-1010-home", 1), _channel("a-7-away", 2), _channel("101-home", 3)]
        target_main = _channel("splus-101-home", 4)
        target_overflow = _channel("splus-101-away", 5)
        category = _category(guild, [*keep, target_main])
        overflow = _category(guild, [target_overflow])
        overflow.name = "Dev League-2"
        guild.categories = [category, overflow]
        m = _mixin(guild, category)

        with patch("rsc.devleague.runner.asyncio.sleep", AsyncMock()):
            await m.teardown_devleague_lobby(guild, lobby_id=101)

        target_main.delete.assert_awaited_once()
        target_overflow.delete.assert_awaited_once()
        for channel in keep:
            channel.delete.assert_not_called()
