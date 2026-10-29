"""The shared lobby runner, tested once and run for both combines and Dev League.

Every test takes the `rig` fixture, which is parametrized over both systems, so a
behavior fixed in `LobbyRunner` is checked for each of them. What only one
system does lives in test_combines_runner.py and test_devleague_runner.py.
"""

import asyncio
import copy
import json
from unittest.mock import AsyncMock, MagicMock, patch

import discord
import pytest

from rsc import const
from rsc.combines.models import CombinesLobby
from rsc.combines.runner import CombinesLeague
from rsc.combines.views import LobbyScore
from rsc.devleague.runner import DevLeague
from rsc.lobbies.channels import Side
from rsc.lobbies.runner import CATEGORY_CHANNEL_LIMIT, OVERFLOW_CATEGORIES, LobbyRunner

GUILD_ID = 395806681994493964


def _player(discord_id: int, team: str, match_id: int) -> dict:
    return {"discord_id": str(discord_id), "rsc_id": f"RSC{discord_id}", "match_id": match_id, "team": team, "name": f"p{discord_id}"}


def _request(data=None, *, bad_json: bool = False) -> MagicMock:
    request = MagicMock()
    if bad_json:
        request.json = AsyncMock(side_effect=json.JSONDecodeError("bad", "", 0))
    else:
        request.json = AsyncMock(return_value=copy.deepcopy(data))
    return request


def _event(message_type: str = "Finished Game", match_id: int | None = 101) -> dict:
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


def _channel(spec, name: str, channel_id: int = 0) -> MagicMock:
    channel = MagicMock(spec=spec)
    channel.name = name
    channel.id = channel_id
    channel.position = 0
    channel.delete = AsyncMock()
    return channel


def _http_error() -> discord.HTTPException:
    return discord.HTTPException(MagicMock(status=500), "boom")


class Rig:
    """One system's runner on a fake guild, with its settings getters stubbed."""

    def __init__(self, system: str):
        self.system = system
        self.guild = MagicMock(spec=discord.Guild)
        self.guild.id = GUILD_ID
        self.guild.name = "RSC"
        self.guild.default_role = _role("@everyone")
        self.league_role, muted = _role(const.LEAGUE_ROLE), _role(const.MUTED_ROLE)
        self.guild.roles = [self.league_role, muted]
        self.guild.categories = []
        self.guild._state.http.bulk_channel_update = AsyncMock()
        self.announce_channel = _channel(discord.TextChannel, "combines-announcements")
        self.guild.channels = [self.announce_channel]

        self.cog = MagicMock()
        self.cog.bot.get_guild.side_effect = lambda gid: self.guild if gid == GUILD_ID else None
        self.cog.combine_players_from_lobby = AsyncMock(return_value=[MagicMock(spec=discord.Member)])
        # No saved lobby cards, so teardown has nothing to mark Final unless a test adds one
        self.cog.config.custom.return_value.LobbyMessages = AsyncMock(return_value={})
        self.active = AsyncMock(return_value=True)
        self.category = self.make_category("Combines" if system == "combines" else "Dev League")
        self.category_getter = AsyncMock(return_value=self.category)
        if system == "combines":
            self.cog._get_combines_active = self.active
            self.cog._get_combines_category = self.category_getter
            self.league = CombinesLeague(self.cog)
            self.tier = "Premier"
        else:
            self.cog._get_devleague_active = self.active
            self.cog._get_devleague_category = self.category_getter
            self.cog._get_devleague_announce_channel = AsyncMock(return_value=self.announce_channel)
            self.league = DevLeague(self.cog)
            self.tier = "S+"
        self.runner = LobbyRunner(self.cog, self.league)
        self.runner.TEARDOWN_DELAY = 0

    def make_category(self, name: str, *, full: bool = False) -> MagicMock:
        category = _channel(discord.CategoryChannel, name)
        category.channels = [MagicMock()] * (CATEGORY_CHANNEL_LIMIT + 1) if full else []
        category.voice_channels = []
        category.guild = self.guild
        created = iter(range(9000, 9100))

        async def create_voice_channel(name, **kwargs):
            channel = _channel(discord.VoiceChannel, name, next(created))
            channel.category = category
            channel.overwrites = kwargs["overwrites"]
            channel.user_limit = kwargs["user_limit"]
            return channel

        category.create_voice_channel = AsyncMock(side_effect=create_voice_channel)
        return category

    def payload(self, match_id: int = 101) -> dict:
        return {
            "id": match_id,
            "lobby_user": f"rsc{match_id}",
            "lobby_pass": "rsc",
            "home_wins": 0,
            "away_wins": 0,
            "reported_rsc_id": None,
            "confirmed_rsc_id": None,
            "completed": False,
            "cancelled": False,
            "tier": self.tier,
            "guild_id": str(GUILD_ID),
            "home": [_player(match_id * 10 + i, "home", match_id) for i in (1, 2, 3)],
            "away": [_player(match_id * 10 + i, "away", match_id) for i in (4, 5, 6)],
        }

    def lobby(self, match_id: int = 101) -> CombinesLobby:
        return CombinesLobby(**self.payload(match_id))

    def channel_name(self, match_id: int, side: Side) -> str:
        return self.league.channel_name(self.lobby(match_id), side)

    def lobby_channel(self, match_id: int, side: Side, category=None) -> MagicMock:
        channel = _channel(discord.VoiceChannel, self.channel_name(match_id, side))
        channel.category = category or self.category
        return channel

    def remove_announce_channel(self) -> None:
        self.guild.channels = []
        if self.system == "devleague":
            self.cog._get_devleague_announce_channel = AsyncMock(return_value=None)

    async def settle(self) -> None:
        await asyncio.wait_for(asyncio.gather(*self.runner.background_tasks), timeout=5)


@pytest.fixture(params=["combines", "devleague"])
def rig(request) -> Rig:
    return Rig(request.param)


def _stub_create(rig: Rig, result=None) -> AsyncMock:
    create = AsyncMock(return_value=[] if result is None else result)
    rig.runner.create_channels = create
    return create


class TestStartGame:
    async def test_bad_json_is_400(self, rig):
        assert (await rig.runner.start_game(_request(bad_json=True))).status == 400

    @pytest.mark.parametrize("data", [{}, [], "lobby"])
    async def test_empty_or_non_object_body_is_400(self, rig, data):
        assert (await rig.runner.start_game(_request(data))).status == 400

    async def test_invalid_lobby_is_400(self, rig):
        payload = rig.payload()
        del payload["tier"]
        assert (await rig.runner.start_game(_request({"101": payload}))).status == 400

    async def test_not_in_guild_is_503_and_creates_nothing(self, rig):
        create = _stub_create(rig)
        payload = {**rig.payload(), "guild_id": "1"}

        assert (await rig.runner.start_game(_request({"101": payload}))).status == 503
        create.assert_not_called()

    async def test_inactive_is_503_and_creates_nothing(self, rig):
        create = _stub_create(rig)
        rig.active.return_value = False

        assert (await rig.runner.start_game(_request({"101": rig.payload()}))).status == 503
        create.assert_not_called()

    async def test_responds_before_lobbies_are_created(self, rig):
        create = _stub_create(rig)

        resp = await rig.runner.start_game(_request({"101": rig.payload(101), "102": rig.payload(102)}))

        assert resp.status == 200
        create.assert_not_called()
        await rig.settle()
        assert [c.args[0].id for c in create.await_args_list] == [101, 102]

    async def test_failed_lobby_does_not_stop_the_rest(self, rig):
        create = _stub_create(rig)
        create.side_effect = [_http_error(), []]

        await rig.runner.start_game(_request({"101": rig.payload(101), "102": rig.payload(102)}))
        await rig.settle()

        assert create.await_count == 2


class TestDuplicateLobbies:
    async def test_concurrent_duplicate_is_created_once(self, rig):
        create = _stub_create(rig, [MagicMock(), MagicMock()])

        await rig.runner.start_game(_request({"101": rig.payload()}))
        await rig.runner.start_game(_request({"101": rig.payload()}))
        await rig.settle()

        create.assert_awaited_once()

    async def test_lobby_that_created_nothing_can_be_retried(self, rig):
        create = _stub_create(rig)

        for _ in range(2):
            await rig.runner.start_game(_request({"101": rig.payload()}))
            await rig.settle()

        assert create.await_count == 2
        assert rig.runner.active_lobbies == set()

    async def test_teardown_allows_lobby_again(self, rig):
        create = _stub_create(rig, [MagicMock(), MagicMock()])

        await rig.runner.start_game(_request({"101": rig.payload()}))
        await rig.settle()
        await rig.runner.teardown(rig.guild, lobby_id=101)
        await rig.runner.start_game(_request({"101": rig.payload()}))
        await rig.settle()

        assert create.await_count == 2


class TestHandleEvent:
    async def test_finished_schedules_teardown(self, rig):
        teardown = AsyncMock()
        rig.runner.teardown = teardown

        resp = await rig.runner.handle_event(_request(_event()))
        await rig.settle()

        assert resp.status == 200
        teardown.assert_awaited_once_with(rig.guild, lobby_id=101)

    async def test_finished_without_match_id_is_400(self, rig):
        assert (await rig.runner.handle_event(_request(_event(match_id=None)))).status == 400

    async def test_other_event_is_501(self, rig):
        assert (await rig.runner.handle_event(_request(_event("Checked In")))).status == 501

    async def test_unknown_guild_is_503(self, rig):
        assert (await rig.runner.handle_event(_request({**_event(), "guild_id": "1"}))).status == 503

    @pytest.mark.parametrize("data", [None, {"match_id": 1}])
    async def test_bad_payload_is_400(self, rig, data):
        request = _request(bad_json=True) if data is None else _request(data)
        assert (await rig.runner.handle_event(request)).status == 400


class TestCreateChannels:
    def _stub_announce(self, rig: Rig) -> AsyncMock:
        announce = AsyncMock()
        rig.runner.announce = announce
        return announce

    async def test_creates_home_and_away_for_league_members_and_announces(self, rig):
        announce = self._stub_announce(rig)

        home, away = await rig.runner.create_channels(rig.lobby())

        assert (home.name, away.name) == (rig.channel_name(101, "home"), rig.channel_name(101, "away"))
        for channel in (home, away):
            assert channel.user_limit == 5
            assert channel.overwrites[rig.guild.default_role].connect is False
            assert channel.overwrites[rig.league_role].connect is True
            assert channel.overwrites[rig.league_role].send_messages is True
        assert announce.await_args is not None
        assert announce.await_args.args[2] == [home, away]
        assert announce.await_args.args[3] is rig.announce_channel

    async def test_guild_gone_creates_nothing(self, rig):
        rig.cog.bot.get_guild.side_effect = None
        rig.cog.bot.get_guild.return_value = None
        assert await rig.runner.create_channels(rig.lobby()) == []

    async def test_stopped_creates_nothing(self, rig):
        rig.active.return_value = False
        assert await rig.runner.create_channels(rig.lobby()) == []
        rig.category.create_voice_channel.assert_not_called()

    async def test_no_category_creates_nothing(self, rig):
        rig.category_getter.return_value = None
        assert await rig.runner.create_channels(rig.lobby()) == []

    @pytest.mark.parametrize("side", ["home", "away"])
    async def test_existing_lobby_creates_nothing(self, rig, side):
        rig.guild.channels.append(rig.lobby_channel(101, side))

        assert await rig.runner.create_channels(rig.lobby()) == []
        rig.category.create_voice_channel.assert_not_called()

    async def test_no_players_in_guild_creates_nothing(self, rig):
        rig.cog.combine_players_from_lobby.return_value = []

        assert await rig.runner.create_channels(rig.lobby()) == []
        rig.category.create_voice_channel.assert_not_called()

    async def test_no_league_role_creates_nothing(self, rig):
        announce = self._stub_announce(rig)
        rig.guild.roles = [_role(const.MUTED_ROLE)]

        assert await rig.runner.create_channels(rig.lobby()) == []
        rig.category.create_voice_channel.assert_not_called()
        announce.assert_not_called()

    async def test_no_announcement_channel_still_creates_the_lobby(self, rig):
        announce = self._stub_announce(rig)
        rig.remove_announce_channel()

        assert len(await rig.runner.create_channels(rig.lobby())) == 2
        announce.assert_not_called()

    async def test_placement_failure_still_returns_the_channels(self, rig):
        self._stub_announce(rig)
        rig.league.place = AsyncMock(side_effect=_http_error())

        assert len(await rig.runner.create_channels(rig.lobby())) == 2


class TestTargetCategory:
    async def test_category_with_room_is_used(self, rig):
        assert await rig.runner.target_category(rig.guild, rig.category) is rig.category

    async def test_full_category_creates_the_next_beside_it(self, rig):
        full = rig.make_category("Lobbies", full=True)
        full.position = 3
        rig.guild.create_category = AsyncMock(return_value=rig.make_category("Lobbies-2"))

        await rig.runner.target_category(rig.guild, full)

        assert rig.guild.create_category.await_args is not None
        assert rig.guild.create_category.await_args.kwargs["name"] == "Lobbies-2"
        assert rig.guild.create_category.await_args.kwargs["position"] == 4

    async def test_skips_names_taken_by_other_channels_and_full_overflows(self, rig):
        # "-2" is a text channel and "-3" is full, so "-4" is used
        roomy = rig.make_category("Lobbies-4")
        rig.guild.channels = [_channel(discord.TextChannel, "Lobbies-2"), rig.make_category("Lobbies-3", full=True), roomy]
        rig.guild.create_category = AsyncMock()

        assert await rig.runner.target_category(rig.guild, rig.make_category("Lobbies", full=True)) is roomy
        rig.guild.create_category.assert_not_called()

    async def test_every_overflow_full_falls_back_to_the_configured_category(self, rig):
        rig.guild.channels = [rig.make_category(f"Lobbies-{i}", full=True) for i in OVERFLOW_CATEGORIES]
        configured = rig.make_category("Lobbies", full=True)

        assert await rig.runner.target_category(rig.guild, configured) is configured


class TestAnnounce:
    async def test_posts_the_card_for_this_system(self, rig):
        home, away = rig.lobby_channel(101, "home"), rig.lobby_channel(101, "away")
        home.jump_url, away.jump_url = "https://discord.com/channels/1/10", "https://discord.com/channels/1/11"
        rig.guild.get_member.return_value = None

        with patch("rsc.lobbies.runner.post_lobby", AsyncMock()) as post:
            await rig.runner.announce(rig.guild, rig.lobby(), [home, away], rig.announce_channel)

        assert post.await_args is not None
        _cog, _guild, _lobby, card, channel, store, active = post.await_args.args
        assert card.kind is rig.league.kind
        assert card.match_url == rig.league.match_url(rig.lobby())
        assert channel is rig.announce_channel
        assert active is rig.runner.active_lobbies
        rig.cog.config.custom.assert_called_with("Combines" if rig.system == "combines" else "DevLeague", str(GUILD_ID))
        assert store is rig.cog.config.custom.return_value

    async def test_needs_two_channels(self, rig):
        with pytest.raises(ValueError):
            await rig.runner.announce(rig.guild, rig.lobby(), [MagicMock()], rig.announce_channel)


class TestTeardown:
    async def test_deletes_only_this_lobbys_channels_across_overflow(self, rig):
        # Lobby 1 must not take lobby 11's or 101's channels, in either naming style
        overflow = rig.make_category(f"{rig.category.name}-2")
        rig.guild.categories = [rig.category, overflow]
        targets = [rig.lobby_channel(1, "home"), rig.lobby_channel(1, "away", overflow)]
        keep = [rig.lobby_channel(n, side) for n in (11, 101) for side in ("home", "away")]
        keep.append(_channel(discord.VoiceChannel, "waiting-room"))
        rig.category.voice_channels = [targets[0], *keep]
        overflow.voice_channels = [targets[1]]

        await rig.runner.teardown(rig.guild, lobby_id=1)

        # The audit log reason keeps the system's own capitals: "Dev League", not "Dev league"
        reason = {"combines": "Combine lobby 1 has finished.", "devleague": "Dev League match 1 has finished."}[rig.system]
        for channel in targets:
            channel.delete.assert_awaited_once_with(reason=reason)
        for channel in keep:
            channel.delete.assert_not_called()

    async def test_saved_card_is_marked_final_with_the_systems_score(self, rig):
        entry = MagicMock()
        rig.league.final_score = AsyncMock(return_value=LobbyScore(home_wins=3, away_wins=2))

        with (
            patch("rsc.lobbies.runner.lobby_messages", AsyncMock(return_value=entry)),
            patch("rsc.lobbies.runner.finish_lobby", AsyncMock()) as finish,
        ):
            await rig.runner.teardown(rig.guild, lobby_id=101)

        assert finish.await_args is not None
        assert finish.await_args.args[1] is entry
        assert finish.await_args.args[3] == LobbyScore(home_wins=3, away_wins=2)

    async def test_no_saved_card_still_deletes_the_channels(self, rig):
        channel = rig.lobby_channel(101, "home")
        rig.category.voice_channels = [channel]

        with patch("rsc.lobbies.runner.lobby_messages", AsyncMock(return_value=None)), patch("rsc.lobbies.runner.finish_lobby") as finish:
            await rig.runner.teardown(rig.guild, lobby_id=101)

        finish.assert_not_called()
        channel.delete.assert_awaited_once()

    async def test_no_category_still_finishes_the_card(self, rig):
        rig.category_getter.return_value = None
        rig.league.final_score = AsyncMock(return_value=None)

        with (
            patch("rsc.lobbies.runner.lobby_messages", AsyncMock(return_value=MagicMock())),
            patch("rsc.lobbies.runner.finish_lobby", AsyncMock()) as finish,
        ):
            await rig.runner.teardown(rig.guild, lobby_id=101)

        finish.assert_awaited_once()

    async def test_waits_before_tearing_down(self, rig):
        rig.runner.TEARDOWN_DELAY = 30
        with patch("rsc.lobbies.runner.asyncio.sleep", AsyncMock()) as sleep:
            await rig.runner.teardown(rig.guild, lobby_id=101)
        sleep.assert_awaited_once_with(30)
