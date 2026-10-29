"""A whole lobby's life, from the start webhook to teardown, for combines and Dev League.

Runs against Red's real Config, the real DM queue, the real settings getters and
the real player lookup. Only Discord is faked, so locking, saving and DM
recording behave as they do in the bot. Every wait is bounded, so a hang fails
the test instead of stalling the suite.
"""

import asyncio
import copy
import itertools
import uuid
import weakref
from types import MethodType
from unittest.mock import AsyncMock, MagicMock, PropertyMock

import discord
import pytest
from discord import ui
from redbot.core import _drivers, data_manager
from redbot.core import config as config_module
from redbot.core.config import Config

from rsc import const
from rsc.combines import manager as combines_manager
from rsc.combines.combines import CombineMixIn
from rsc.combines.manager import CombineManagerMixIn
from rsc.combines.models import CombinesLobby
from rsc.combines.runner import ANNOUNCE_CHANNEL, CombinesLeague
from rsc.combines.views import FINAL_COLOUR, LIVE_COLOUR
from rsc.devleague import devleague as devleague_cog
from rsc.devleague.manager import DevLeagueManagerMixIn
from rsc.devleague.runner import DevLeague
from rsc.lobbies.runner import LobbyRunner
from rsc.utils.dm import DMHelper

GUILD_ID = 395806681994493964
LOBBY_IDS = (101, 102, 103)
# Long enough for a slow CI box, short enough that a hang is obvious
WAIT = 5


@pytest.fixture
def config(tmp_path, monkeypatch) -> Config:
    """The bot's Config on a throwaway JSON store, registered as the cog registers it."""
    monkeypatch.setattr(data_manager, "basic_config", {**data_manager.basic_config_default, "DATA_PATH": str(tmp_path)})
    monkeypatch.setattr(config_module, "_config_cache", weakref.WeakValueDictionary())
    # Red's JSON driver shares its data across the process by cog name, so each test
    # gets its own name, as Red's own test fixtures do, or settings leak between tests
    cog_name = f"RSC{uuid.uuid4().hex}"
    driver = _drivers.get_driver(cog_name, "6349109713", data_path_override=tmp_path)
    conf = Config(cog_name=cog_name, unique_identifier="6349109713", driver=driver, force_registration=True)
    conf.init_custom("Combines", 1)
    conf.register_custom("Combines", **combines_manager.defaults_guild)
    conf.init_custom("DevLeague", 1)
    conf.register_custom("DevLeague", **devleague_cog.defaults_guild)
    return conf


@pytest.fixture
async def dm_helper():
    helper = DMHelper(rate=0)
    helper.start()
    yield helper
    await helper.stop(drain=False)


class FakeDiscord:
    """A guild whose channels, messages and DMs are recorded as the runners touch them."""

    def __init__(self):
        self.ids = itertools.count(10_000)
        self._channels: list = []
        self.edits: dict[tuple[int, int], ui.LayoutView] = {}
        self.dms: list[discord.Message] = []

        self.guild = MagicMock(spec=discord.Guild)
        self.guild.id = GUILD_ID
        self.guild.name = "RSC"
        self.guild.icon = None
        # discord.py hands back a fresh list each time, so teardown can delete while it loops
        type(self.guild).channels = PropertyMock(side_effect=lambda: list(self._channels))
        type(self.guild).categories = PropertyMock(
            side_effect=lambda: [c for c in self._channels if isinstance(c, discord.CategoryChannel)]
        )
        self.guild.default_role = MagicMock(spec=discord.Role)
        self.guild.roles = [self._role(const.LEAGUE_ROLE), self._role(const.MUTED_ROLE)]
        self.guild._state.http.bulk_channel_update = AsyncMock()
        self.members = {}
        self.guild.get_member.side_effect = self.members.get
        self.guild.get_channel.side_effect = lambda cid: next((c for c in self._channels if c.id == cid), None)

        self.announce = MagicMock(spec=discord.TextChannel)
        self.announce.id = next(self.ids)
        self.announce.category = None
        self.announce.send = AsyncMock(side_effect=self._post)
        self.posts: list[discord.Message] = []

        self.bot = MagicMock()
        self.bot.guilds = [self.guild]
        self.bot.get_guild.side_effect = lambda gid: self.guild if gid == GUILD_ID else None
        self.bot.get_partial_messageable.side_effect = self._messageable

    @staticmethod
    def _role(name: str) -> MagicMock:
        role = MagicMock(spec=discord.Role)
        role.name = name
        return role

    def category(self, name: str) -> MagicMock:
        cat = MagicMock(spec=discord.CategoryChannel)
        cat.name = name
        cat.id = next(self.ids)
        cat.category = None
        cat.position = 0
        cat.guild = self.guild
        mine = lambda: [c for c in self._channels if getattr(c, "category", None) is cat]  # noqa: E731
        type(cat).channels = PropertyMock(side_effect=mine)
        type(cat).voice_channels = PropertyMock(side_effect=mine)

        async def create_voice_channel(name: str, **_kwargs):
            vc = MagicMock(spec=discord.VoiceChannel)
            vc.name = name
            vc.id = next(self.ids)
            vc.category = cat
            vc.position = len(mine())
            vc.jump_url = f"https://discord.com/channels/{GUILD_ID}/{vc.id}"
            vc.delete = AsyncMock(side_effect=lambda **_: self._channels.remove(vc))
            self._channels.append(vc)
            return vc

        cat.create_voice_channel = AsyncMock(side_effect=create_voice_channel)
        self._channels.append(cat)
        return cat

    def add_announce_channel(self, name: str):
        self.announce.name = name
        self._channels.append(self.announce)

    def member(self, member_id: int) -> MagicMock:
        member = MagicMock(spec=discord.Member)
        member.id = member_id
        member.mention = f"<@{member_id}>"
        member.send = AsyncMock(side_effect=self._dm)
        self.members[member_id] = member
        return member

    def voice_channels(self) -> list[str]:
        return [c.name for c in self._channels if isinstance(c, discord.VoiceChannel)]

    def _message(self, channel_id: int) -> MagicMock:
        msg = MagicMock(spec=discord.Message)
        msg.id = next(self.ids)
        msg.channel = MagicMock(id=channel_id)
        return msg

    async def _post(self, **_kwargs):
        msg = self._message(self.announce.id)
        self.posts.append(msg)
        return msg

    async def _dm(self, **_kwargs):
        msg = self._message(next(self.ids))
        self.dms.append(msg)
        return msg

    def _messageable(self, channel_id: int, **_kwargs):
        channel = MagicMock()

        def partial(message_id: int):
            message = MagicMock()

            async def edit(*, view):
                self.edits[(channel_id, message_id)] = view

            message.edit = AsyncMock(side_effect=edit)
            return message

        channel.get_partial_message.side_effect = partial
        return channel


def _player(discord_id: int, team: str, match_id: int) -> dict:
    return {"discord_id": str(discord_id), "rsc_id": f"RSC{discord_id}", "match_id": match_id, "team": team, "name": f"p{discord_id}"}


def _lobby_payload(match_id: int, tier: str) -> dict:
    # Players are unique per lobby, like a real night: ids 1011..1016 for lobby 101
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
        "tier": tier,
        "guild_id": str(GUILD_ID),
        "home": [_player(match_id * 10 + i, "home", match_id) for i in (1, 2, 3)],
        "away": [_player(match_id * 10 + i, "away", match_id) for i in (4, 5, 6)],
    }


def _finished(match_id: int) -> dict:
    return {
        "actor": {"nickname": "nickm", "discord_id": 1},
        "status": "success",
        "message_type": "Finished Game",
        "message": "done",
        "match_id": match_id,
        "guild_id": str(GUILD_ID),
    }


def _request(data) -> MagicMock:
    request = MagicMock()
    request.json = AsyncMock(return_value=copy.deepcopy(data))
    return request


async def _settle(runner: LobbyRunner) -> None:
    """Wait for every background task the runner started, or fail on a hang."""
    while runner.background_tasks:
        await asyncio.wait_for(asyncio.gather(*runner.background_tasks), timeout=WAIT)


async def _drain(helper: DMHelper, sent: int) -> None:
    async def until_sent():
        # The helper only exposes counters, so poll them
        while helper.success < sent:  # noqa: ASYNC110
            await asyncio.sleep(0.01)

    await asyncio.wait_for(until_sent(), timeout=WAIT)


def _colour(view: ui.LayoutView) -> discord.Colour | int | None:
    (container,) = view.children
    assert isinstance(container, ui.Container)
    return container.accent_colour


def _cog(fake: FakeDiscord, config: Config, helper: DMHelper) -> MagicMock:
    """The cog as the runners see it, with the real settings getters and player lookup."""
    cog = MagicMock()
    cog.bot = fake.bot
    cog.config = config
    cog._dm_helper = helper
    cog.live_emoji = lambda: ""
    for mixin, names in (
        (CombineManagerMixIn, ("_get_combines_active", "_get_combines_category", "_get_combines_api")),
        (CombineManagerMixIn, ("_set_combines_active", "_set_combines_category", "_set_combines_api")),
        (DevLeagueManagerMixIn, ("_get_devleague_active", "_get_devleague_category", "_get_devleague_announce_channel")),
        (DevLeagueManagerMixIn, ("_set_devleague_active", "_set_devleague_category", "_set_devleague_announce_channel")),
        (CombineMixIn, ("combine_players_from_lobby",)),
    ):
        for name in names:
            setattr(cog, name, MethodType(getattr(mixin, name), cog))
    return cog


async def _combines(fake: FakeDiscord, config: Config, helper: DMHelper) -> LobbyRunner:
    """Combines switched on, with its category set and its announcement channel in the guild."""
    category = fake.category("Combines")
    fake.add_announce_channel(ANNOUNCE_CHANNEL)
    settings = config.custom("Combines", str(GUILD_ID))
    await settings.Active.set(True)
    await settings.CombinesCategory.set(category.id)
    cog = _cog(fake, config, helper)
    runner = LobbyRunner(cog, CombinesLeague(cog))
    runner.TEARDOWN_DELAY = 0
    return runner


async def _devleague(fake: FakeDiscord, config: Config, helper: DMHelper) -> LobbyRunner:
    """Dev League switched on, with its category and announcement channel set."""
    category = fake.category("Dev League")
    fake.add_announce_channel("dev-league-announcements")
    settings = config.custom("DevLeague", str(GUILD_ID))
    await settings.Active.set(True)
    await settings.DevLeagueCategory.set(category.id)
    await settings.DevLeagueAnnounceChannel.set(fake.announce.id)
    cog = _cog(fake, config, helper)
    runner = LobbyRunner(cog, DevLeague(cog))
    runner.TEARDOWN_DELAY = 0
    return runner


async def _run_lifecycle(fake: FakeDiscord, store, runner: LobbyRunner, helper: DMHelper, tiers: list[str]):
    for match_id in LOBBY_IDS:
        for i in range(1, 7):
            fake.member(match_id * 10 + i)
    payload = {str(match_id): _lobby_payload(match_id, tier) for match_id, tier in zip(LOBBY_IDS, tiers, strict=True)}

    # Start: every lobby in the batch gets two VCs, a card and a saved record
    resp = await runner.start_game(_request(payload))
    assert resp.status == 200
    await _settle(runner)

    assert len(fake.voice_channels()) == 2 * len(LOBBY_IDS)
    assert len(fake.posts) == len(LOBBY_IDS)
    saved = await store.LobbyMessages()
    assert sorted(map(int, saved)) == list(LOBBY_IDS)

    # Every player is DMed their copy, and each DM is recorded for teardown
    await _drain(helper, 6 * len(LOBBY_IDS))
    saved = await store.LobbyMessages()
    assert all(len(record["dms"]) == 6 for record in saved.values())

    # Teardown: the card and every DM turn Final, the VCs go, and the record is forgotten
    for match_id in LOBBY_IDS:
        resp = await runner.handle_event(_request(_finished(match_id)))
        assert resp.status == 200
    await _settle(runner)

    assert fake.voice_channels() == []
    assert await store.LobbyMessages() == {}
    expected = {(fake.announce.id, p.id) for p in fake.posts} | {(d.channel.id, d.id) for d in fake.dms}
    assert set(fake.edits) == expected
    assert all(_colour(view) == FINAL_COLOUR for view in fake.edits.values())
    assert not store.LobbyMessages.get_lock().locked()


class TestCombinesLifecycle:
    async def test_start_to_teardown(self, config, dm_helper):
        fake = FakeDiscord()
        runner = await _combines(fake, config, dm_helper)

        await _run_lifecycle(fake, config.custom("Combines", str(GUILD_ID)), runner, dm_helper, ["Premier", "Elite", "Elite"])

    async def test_cards_post_live_even_when_some_players_left(self, config, dm_helper):
        fake = FakeDiscord()
        runner = await _combines(fake, config, dm_helper)
        fake.member(1011)

        await runner.start_game(_request({"101": _lobby_payload(101, "Premier")}))
        await _settle(runner)

        assert fake.announce.send.await_args is not None
        assert _colour(fake.announce.send.await_args.kwargs["view"]) == LIVE_COLOUR

    async def test_back_to_back_batches_all_start(self, config, dm_helper):
        # The night of the deadlock: a second webhook while the first batch was still running
        fake = FakeDiscord()
        runner = await _combines(fake, config, dm_helper)
        for match_id in (101, 102, 103, 104):
            fake.member(match_id * 10 + 1)

        await runner.start_game(_request({"101": _lobby_payload(101, "Elite"), "102": _lobby_payload(102, "Elite")}))
        await runner.start_game(_request({"103": _lobby_payload(103, "Elite"), "104": _lobby_payload(104, "Elite")}))
        await _settle(runner)

        assert sorted(map(int, await config.custom("Combines", str(GUILD_ID)).LobbyMessages())) == [101, 102, 103, 104]


class TestDevLeagueLifecycle:
    async def test_start_to_teardown(self, config, dm_helper):
        fake = FakeDiscord()
        runner = await _devleague(fake, config, dm_helper)

        await _run_lifecycle(fake, config.custom("DevLeague", str(GUILD_ID)), runner, dm_helper, ["S+", "A", "F"])

    async def test_tier_outside_the_letter_scheme_still_tears_down(self, config, dm_helper):
        fake = FakeDiscord()
        runner = await _devleague(fake, config, dm_helper)

        await _run_lifecycle(fake, config.custom("DevLeague", str(GUILD_ID)), runner, dm_helper, ["Tier 2", "A-", "S++"])

    async def test_back_to_back_batches_all_start(self, config, dm_helper):
        fake = FakeDiscord()
        runner = await _devleague(fake, config, dm_helper)
        for match_id in (101, 102, 103, 104):
            fake.member(match_id * 10 + 1)

        await runner.start_game(_request({"101": _lobby_payload(101, "A"), "102": _lobby_payload(102, "B")}))
        await runner.start_game(_request({"103": _lobby_payload(103, "C"), "104": _lobby_payload(104, "D")}))
        await _settle(runner)

        assert sorted(map(int, await config.custom("DevLeague", str(GUILD_ID)).LobbyMessages())) == [101, 102, 103, 104]


class TestSettingsLookups:
    """The getters each system reads its settings through, against real Config."""

    async def test_unset_settings_read_as_off_or_missing(self, config):
        cog = _cog(FakeDiscord(), config, MagicMock())
        guild = cog.bot.get_guild(GUILD_ID)

        assert await cog._get_combines_active(guild) is False
        assert await cog._get_combines_category(guild) is None
        assert await cog._get_combines_api(guild) is None
        assert await cog._get_devleague_active(guild) is False
        assert await cog._get_devleague_category(guild) is None
        assert await cog._get_devleague_announce_channel(guild) is None

    async def test_ids_pointing_at_the_wrong_kind_of_channel_read_as_missing(self, config):
        fake = FakeDiscord()
        fake.add_announce_channel("announcements")
        category = fake.category("Lobbies")
        cog = _cog(fake, config, MagicMock())
        # A text channel saved as a category, and a category saved as the announcement channel
        await config.custom("Combines", str(GUILD_ID)).CombinesCategory.set(fake.announce.id)
        await config.custom("DevLeague", str(GUILD_ID)).DevLeagueCategory.set(fake.announce.id)
        await config.custom("DevLeague", str(GUILD_ID)).DevLeagueAnnounceChannel.set(category.id)

        assert await cog._get_combines_category(fake.guild) is None
        assert await cog._get_devleague_category(fake.guild) is None
        assert await cog._get_devleague_announce_channel(fake.guild) is None

    async def test_what_the_setters_save_the_getters_read_back(self, config):
        fake = FakeDiscord()
        fake.add_announce_channel("announcements")
        category = fake.category("Lobbies")
        cog = _cog(fake, config, MagicMock())

        await cog._set_combines_active(fake.guild, True)
        await cog._set_combines_category(fake.guild, category)
        await cog._set_combines_api(fake.guild, "https://combines.example/api/")
        await cog._set_devleague_active(fake.guild, True)
        await cog._set_devleague_category(fake.guild, category)
        await cog._set_devleague_announce_channel(fake.guild, fake.announce)

        assert await cog._get_combines_active(fake.guild) is True
        assert await cog._get_combines_category(fake.guild) is category
        assert await cog._get_combines_api(fake.guild) == "https://combines.example/api/"
        assert await cog._get_devleague_active(fake.guild) is True
        assert await cog._get_devleague_category(fake.guild) is category
        assert await cog._get_devleague_announce_channel(fake.guild) is fake.announce

    async def test_ids_that_no_longer_exist_read_as_missing(self, config):
        fake = FakeDiscord()
        cog = _cog(fake, config, MagicMock())
        await config.custom("Combines", str(GUILD_ID)).CombinesCategory.set(424242)

        assert await cog._get_combines_category(fake.guild) is None


class TestCombinePlayersFromLobby:
    async def test_home_then_away_skipping_players_not_in_the_guild(self, config):
        fake = FakeDiscord()
        present = [fake.member(i) for i in (1012, 1013, 1014, 1016)]
        cog = _cog(fake, config, MagicMock())

        players = await cog.combine_players_from_lobby(fake.guild, CombinesLobby(**_lobby_payload(101, "Elite")))

        assert players == present
