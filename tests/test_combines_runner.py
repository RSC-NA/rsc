import asyncio
import copy
import json
from unittest.mock import AsyncMock, MagicMock, patch

import discord
import pytest

from rsc import const
from rsc.combines import models, runner
from rsc.combines.lobby import LobbyMessages
from rsc.combines.runner import CombineRunnerMixIn
from rsc.combines.views import LobbyCard, LobbyKind, LobbyScore
from rsc.exceptions import BadGateway, CombinesNotActive, NotInGuild

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


def _event_payload(message_type: str = "Finished Game", match_id: int | None = 101) -> dict:
    return {
        "actor": {"nickname": "nickm", "discord_id": 1},
        "status": "success",
        "message_type": message_type,
        "message": "done",
        "match_id": match_id,
        "guild_id": str(GUILD_ID),
    }


def _role(name: str) -> MagicMock:
    role = MagicMock(spec=discord.Role)
    role.name = name
    return role


def _named(spec, name: str, category=None) -> MagicMock:
    channel = MagicMock(spec=spec)
    channel.name = name
    channel.category = category
    channel.delete = AsyncMock()
    return channel


def _category(name: str = "Combines", channels=None) -> MagicMock:
    category = _named(discord.CategoryChannel, name)
    category.id = 1
    category.channels = list(channels or [])

    async def create_voice_channel(name, **kwargs):
        channel = _named(discord.VoiceChannel, name, category)
        channel.overwrites = kwargs["overwrites"]
        channel.user_limit = kwargs["user_limit"]
        return channel

    category.create_voice_channel = AsyncMock(side_effect=create_voice_channel)
    return category


def _combines_guild(channels=None, *, roles=(const.LEAGUE_ROLE, const.MUTED_ROLE)) -> MagicMock:
    guild = MagicMock(spec=discord.Guild)
    guild.id = GUILD_ID
    guild.name = "RSC"
    guild.channels = list(channels or [])
    guild.default_role = _role("@everyone")
    guild.roles = [_role(r) for r in roles]
    return guild


def _creator(guild, category) -> tuple[CombineRunnerMixIn, AsyncMock]:
    """A runner that really creates channels, and the stub its announcement goes to."""
    m = _mixin(guild)
    del m.create_combine_lobby_channel
    m.bot.guilds = [guild]
    m._get_combines_category = AsyncMock(return_value=category)
    m.combine_players_from_lobby = AsyncMock(return_value=[MagicMock(spec=discord.Member)])
    announce = AsyncMock()
    m.announce_combines_lobby = announce
    return m, announce


class TestCreateCombineLobbyChannel:
    async def test_creates_home_and_away_and_announces(self):
        guild = _combines_guild()
        category = _category()
        m, announce = _creator(guild, category)

        home, away = await m.create_combine_lobby_channel(models.CombinesLobby(**_lobby_payload()))

        assert (home.name, away.name) == ("Premier-101-home", "Premier-101-away")
        league, muted = guild.roles
        for channel in (home, away):
            assert channel.user_limit == 5
            assert channel.overwrites[guild.default_role].connect is False
            assert channel.overwrites[league].connect is True
            assert channel.overwrites[muted].connect is False
        assert announce.await_args is not None
        assert announce.await_args.kwargs["channels"] == [home, away]

    async def test_not_in_guild_raises(self):
        m, _announce = _creator(_combines_guild(), _category())
        m.bot.guilds = []
        with pytest.raises(NotInGuild):
            await m.create_combine_lobby_channel(models.CombinesLobby(**_lobby_payload()))

    async def test_inactive_raises(self):
        m, _announce = _creator(_combines_guild(), _category())
        m._get_combines_active = AsyncMock(return_value=False)
        with pytest.raises(CombinesNotActive):
            await m.create_combine_lobby_channel(models.CombinesLobby(**_lobby_payload()))

    async def test_no_category_creates_nothing(self):
        m, announce = _creator(_combines_guild(), None)
        assert await m.create_combine_lobby_channel(models.CombinesLobby(**_lobby_payload())) == []
        announce.assert_not_called()

    @pytest.mark.parametrize("side", ["home", "away"])
    async def test_existing_lobby_creates_nothing(self, side):
        category = _category()
        m, _announce = _creator(_combines_guild([_named(discord.VoiceChannel, f"Premier-101-{side}", category)]), category)

        assert await m.create_combine_lobby_channel(models.CombinesLobby(**_lobby_payload())) == []
        category.create_voice_channel.assert_not_called()

    async def test_no_players_in_guild_creates_nothing(self):
        category = _category()
        m, _announce = _creator(_combines_guild(), category)
        m.combine_players_from_lobby = AsyncMock(return_value=[])

        assert await m.create_combine_lobby_channel(models.CombinesLobby(**_lobby_payload())) == []
        category.create_voice_channel.assert_not_called()

    async def test_no_muted_role_still_creates_the_lobby(self):
        guild = _combines_guild(roles=(const.LEAGUE_ROLE,))
        m, _announce = _creator(guild, _category())

        home, _away = await m.create_combine_lobby_channel(models.CombinesLobby(**_lobby_payload()))

        assert set(home.overwrites) == {guild.default_role, guild.roles[0]}

    async def test_no_league_role_creates_nothing(self):
        category = _category()
        m, announce = _creator(_combines_guild(roles=(const.MUTED_ROLE,)), category)

        assert await m.create_combine_lobby_channel(models.CombinesLobby(**_lobby_payload())) == []
        category.create_voice_channel.assert_not_called()
        announce.assert_not_called()

    async def test_full_category_overflows_into_a_new_one(self):
        guild = _combines_guild()
        full = _category(channels=[MagicMock()] * 41)
        overflow = _category("Combines-2")
        guild.create_category = AsyncMock(return_value=overflow)
        m, _announce = _creator(guild, full)

        home, _away = await m.create_combine_lobby_channel(models.CombinesLobby(**_lobby_payload()))

        assert guild.create_category.await_args is not None
        assert guild.create_category.await_args.kwargs["name"] == "Combines-2"
        assert home.category is overflow
        full.create_voice_channel.assert_not_called()

    async def test_full_category_uses_the_next_one_with_room(self):
        # "-2" is taken by a text channel and "-3" is full, so "-4" is used
        full = _category(channels=[MagicMock()] * 41)
        taken = _named(discord.TextChannel, "Combines-2")
        also_full = _category("Combines-3", channels=[MagicMock()] * 41)
        roomy = _category("Combines-4")
        guild = _combines_guild([taken, also_full, roomy])
        guild.create_category = AsyncMock()
        m, _announce = _creator(guild, full)

        home, _away = await m.create_combine_lobby_channel(models.CombinesLobby(**_lobby_payload()))

        assert home.category is roomy
        guild.create_category.assert_not_called()

    async def test_unavailable_lobby_can_be_retried(self):
        m = _mixin(MagicMock())
        m.create_combine_lobby_channel.side_effect = NotInGuild

        await m._create_combine_lobbies([models.CombinesLobby(**_lobby_payload())])

        assert runner.active_lobbies == set()


class TestAnnounceCombinesLobby:
    async def test_posts_the_card_to_the_announcement_channel(self):
        announce = _named(discord.TextChannel, "combines-announcements")
        guild = _combines_guild([announce])
        guild.get_member.return_value = None
        m = _mixin(guild)
        m.config.custom.return_value = MagicMock()
        home, away = _named(discord.VoiceChannel, "Premier-101-home"), _named(discord.VoiceChannel, "Premier-101-away")
        home.jump_url, away.jump_url = "https://discord.com/channels/1/10", "https://discord.com/channels/1/11"

        with patch("rsc.combines.runner.post_lobby", AsyncMock()) as post:
            await m.announce_combines_lobby(guild, models.CombinesLobby(**_lobby_payload()), [home, away])

        assert post.await_args is not None
        _cog, _guild, _lobby, card, channel, _store, active = post.await_args.args
        assert channel is announce
        assert card.match_url == "https://devleague.rscna.com/combine/101"
        assert active is runner.active_lobbies

    async def test_needs_two_channels(self):
        with pytest.raises(ValueError):
            await _mixin().announce_combines_lobby(_combines_guild(), models.CombinesLobby(**_lobby_payload()), [MagicMock()])

    @pytest.mark.parametrize("channels", [[], [_named(discord.VoiceChannel, "combines-announcements")]])
    async def test_missing_or_wrong_announcement_channel_raises(self, channels):
        with pytest.raises(RuntimeError):
            await _mixin().announce_combines_lobby(
                _combines_guild(channels), models.CombinesLobby(**_lobby_payload()), [MagicMock(), MagicMock()]
            )


class TestTeardownCombineLobby:
    async def test_deletes_only_this_lobbys_combines_channels(self):
        combines = _category()
        other = _category("General")
        targets = [_named(discord.VoiceChannel, f"Premier-101-{side}", combines) for side in ("home", "away")]
        keep = [
            _named(discord.VoiceChannel, "Premier-102-home", combines),
            _named(discord.VoiceChannel, "Premier-101-home", other),
            _named(discord.TextChannel, "Premier-101-home"),
        ]
        guild = _combines_guild([*targets, *keep])
        m = _mixin(guild)

        with patch("rsc.combines.runner.asyncio.sleep", AsyncMock()):
            await m.teardown_combine_lobby(guild, lobby_id=101)

        for channel in targets:
            channel.delete.assert_awaited_once()
        for channel in keep:
            channel.delete.assert_not_called()

    async def test_lobby_id_that_ends_another_does_not_take_its_channels(self):
        combines = _category()
        mine = [_named(discord.VoiceChannel, f"Elite-1-{side}", combines) for side in ("home", "away")]
        others = [_named(discord.VoiceChannel, f"Elite-{n}-{side}", combines) for n in (11, 101, 4801) for side in ("home", "away")]
        guild = _combines_guild([*mine, *others])
        m = _mixin(guild)

        with patch("rsc.combines.runner.asyncio.sleep", AsyncMock()):
            await m.teardown_combine_lobby(guild, lobby_id=1)

        for channel in mine:
            channel.delete.assert_awaited_once()
        for channel in others:
            channel.delete.assert_not_called()

    async def test_saved_card_is_marked_final_with_the_score(self):
        guild = _combines_guild()
        m = _mixin(guild)
        m._combine_final_score = AsyncMock(return_value=LobbyScore(home_wins=3, away_wins=2))
        entry = _entry()

        with (
            patch("rsc.combines.runner.asyncio.sleep", AsyncMock()),
            patch("rsc.combines.runner.lobby_messages", AsyncMock(return_value=entry)),
            patch("rsc.combines.runner.finish_lobby", AsyncMock()) as finish,
        ):
            await m.teardown_combine_lobby(guild, lobby_id=101)

        assert finish.await_args is not None
        assert finish.await_args.args[1] is entry
        assert finish.await_args.args[3] == LobbyScore(home_wins=3, away_wins=2)


class TestCombinesEventHandler:
    def _mixin(self, guild):
        m = _mixin(guild)
        m.bot.guilds = [guild] if guild else []
        m.teardown_combine_lobby = AsyncMock()
        return m

    async def test_finished_schedules_teardown(self):
        guild = _combines_guild()
        m = self._mixin(guild)

        resp = await m.combines_event_handler(_request(_event_payload()))
        await asyncio.gather(*runner.background_tasks)

        assert resp.status == 200
        m.teardown_combine_lobby.assert_awaited_once_with(guild, lobby_id=101)

    async def test_finished_without_match_id_is_400(self):
        resp = await self._mixin(_combines_guild()).combines_event_handler(_request(_event_payload(match_id=None)))
        assert resp.status == 400

    async def test_other_event_is_501(self):
        resp = await self._mixin(_combines_guild()).combines_event_handler(_request(_event_payload("Checked In")))
        assert resp.status == 501

    async def test_unknown_guild_is_503(self):
        resp = await self._mixin(None).combines_event_handler(_request(_event_payload()))
        assert resp.status == 503

    @pytest.mark.parametrize("data", [None, {"match_id": 1}])
    async def test_bad_payload_is_400(self, data):
        request = _request(bad_json=True) if data is None else _request(data)
        resp = await self._mixin(_combines_guild()).combines_event_handler(request)
        assert resp.status == 400
