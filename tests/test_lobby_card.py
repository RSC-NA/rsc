import asyncio
from datetime import UTC, datetime
from typing import Any
from unittest.mock import AsyncMock, MagicMock

import discord
import pytest
from discord import ui

from rsc.combines import lobby
from rsc.combines.lobby import LobbyMessages, finish_lobby, lobby_card, lobby_messages, post_lobby
from rsc.combines.models import CombinesLobby, CombinesPlayer
from rsc.combines.views import FINAL_COLOUR, LIVE_COLOUR, LobbyCard, LobbyKind, LobbyScore, LobbyTeam
from rsc.utils.dm import DMOutcome

STARTED = datetime(2026, 10, 28, 22, 47, tzinfo=UTC)
SCORE_LINE = "### Home 3\N{NO-BREAK SPACE}\N{EN DASH}\N{NO-BREAK SPACE}1 Away"
LIVE = "<a:live:123>"


def _card(**overrides) -> LobbyCard:
    fields: dict[str, Any] = {
        "kind": LobbyKind.COMBINE,
        "lobby_id": 4812,
        "tier": "Elite",
        "lobby_name": "rsc4812",
        "lobby_pass": "nova",
        "home": ("<@1>", "<@2>", "<@3>"),
        "away": ("<@4>", "<@5>", "Off\\_server"),
        "lobby_maker": "Nova",
        "home_vc_url": "https://discord.com/channels/1/10",
        "away_vc_url": "https://discord.com/channels/1/11",
        "match_url": "https://devleague.rscna.com/combine/4812",
        "started_at": STARTED,
    }
    fields.update(overrides)
    return LobbyCard(**fields)


def _container(view: ui.LayoutView) -> ui.Container:
    (container,) = view.children
    assert isinstance(container, ui.Container)
    return container


def _texts(item: ui.Container | ui.Section) -> list[str]:
    out = []
    for child in item.children:
        if isinstance(child, ui.TextDisplay):
            out.append(child.content)
        elif isinstance(child, ui.Section):
            out.extend(_texts(child))
    return out


def _lines(item: ui.Container | ui.Section) -> list[str]:
    return [line for text in _texts(item) for line in text.split("\n")]


def _sections(view: ui.LayoutView) -> list[ui.Section]:
    return [c for c in _container(view).children if isinstance(c, ui.Section)]


class TestRenderLive:
    def test_layout(self):
        view = _card().render(live_emoji=LIVE)
        container = _container(view)
        assert container.accent_colour == LIVE_COLOUR
        header, _, _ = _sections(view)
        # Only the title sits beside the Match button; the lobby details run full width below
        assert _texts(header) == [f"## {LIVE} LIVE · Combine 4812"]
        assert isinstance(header.accessory, ui.Button)
        assert (header.accessory.label, header.accessory.url) == ("Match", "https://devleague.rscna.com/combine/4812")
        texts = _texts(container)
        assert "**Lobby** `rsc4812`\n**Password** `nova`" in texts
        # The start time sits in the footer, above the lobbyinfo hint
        assert texts[-1] == f"-# Started {discord.utils.format_dt(STARTED, 'R')}\n-# Lost these details? Run `/combines lobbyinfo`."

    def test_teams_ping_from_text_and_join_their_voice_channel(self):
        view = _card().render()
        _, home, away = _sections(view)
        assert _texts(home) == ["**Home**", "-# Nova makes the lobby"]
        assert _texts(away) == ["**Away**", "-# Uploads the replays"]
        # Each roster runs full width under its team's header, one player per line
        children = _container(view).children
        for section, roster in ((home, "<@1>\n<@2>\n<@3>"), (away, "<@4>\n<@5>\nOff\\_server")):
            after = children[children.index(section) + 1]
            assert isinstance(after, ui.TextDisplay) and after.content == roster
        for section, label, url in (
            (home, "Join Home VC", "https://discord.com/channels/1/10"),
            (away, "Join Away VC", "https://discord.com/channels/1/11"),
        ):
            assert isinstance(section.accessory, ui.Button)
            assert (section.accessory.label, section.accessory.url, section.accessory.style) == (label, url, discord.ButtonStyle.link)

    def test_missing_emoji_reads_plain_live(self):
        header = _sections(_card().render())[0]
        assert _texts(header)[0] == "## LIVE · Combine 4812"

    def test_backticks_cannot_break_the_code_span(self):
        texts = _texts(_container(_card(lobby_name="a`b").render()))
        assert "**Lobby** `a'b`\n**Password** `nova`" in texts

    @pytest.mark.parametrize(
        ("viewer", "makes_lobby", "line"),
        [
            (LobbyTeam.HOME, True, "You're on **Home** · you make the lobby"),
            (LobbyTeam.HOME, False, "You're on **Home**"),
            (LobbyTeam.AWAY, False, "You're on **Away** · your team uploads the replays"),
        ],
    )
    def test_dm_personal_line(self, viewer, makes_lobby, line):
        view = _card().render(viewer=viewer, viewer_makes_lobby=makes_lobby)
        # The DM line sits under the title, in the same TextDisplay
        assert _lines(_container(view))[1] == line

    def test_within_component_limits(self):
        view = _card().render(live_emoji=LIVE, viewer=LobbyTeam.HOME, viewer_makes_lobby=True)
        assert view.total_children_count <= 40


class TestRenderDevLeague:
    def test_title_tier_and_no_combine_extras(self):
        card = _card(kind=LobbyKind.DEV_LEAGUE, tier="A", lobby_id=2207, match_url="https://devleague.rscna.com/match/2207")
        view = card.render(live_emoji=LIVE, viewer=LobbyTeam.AWAY)
        texts = _texts(_container(view))
        assert _lines(_container(view))[:2] == [f"## {LIVE} LIVE · Dev League A Match 2207", "You're on **Away**"]
        assert "-# Uploads the replays" not in texts
        assert not any("lobbyinfo" in t for t in texts)
        assert texts[-1] == f"-# Started {discord.utils.format_dt(STARTED, 'R')}"


class TestRenderFinal:
    def test_final_with_score(self):
        view = _card().render(final=True, score=LobbyScore(home_wins=3, away_wins=1))
        container = _container(view)
        assert container.accent_colour == FINAL_COLOUR
        texts = _texts(container)
        assert texts[0] == "## Final · Combine 4812"
        assert texts[1] == SCORE_LINE
        # Lobby details, start time, roles and Join buttons are gone; the Match link stays
        assert not any("Password" in t or "Started" in t or "lobbyinfo" in t or "makes the lobby" in t for t in texts)
        (header,) = _sections(view)
        assert isinstance(header.accessory, ui.Button) and header.accessory.label == "Match"
        assert texts[-4:] == ["**Home**", "<@1>\n<@2>\n<@3>", "**Away**", "<@4>\n<@5>\nOff\\_server"]

    def test_final_without_score(self):
        texts = _texts(_container(_card().render(final=True)))
        assert texts[0] == "## Final · Combine 4812"
        assert not any(t.startswith("### Home") for t in texts)

    def test_final_dm_line(self):
        assert _lines(_container(_card().render(viewer=LobbyTeam.AWAY, final=True)))[1] == "You were on **Away**"


class TestStorage:
    def test_round_trips_through_json(self):
        entry = LobbyMessages(card=_card(), channel_id=1, message_id=2, dms=[(3, 4, LobbyTeam.AWAY)], executor_id=1)
        assert LobbyMessages.model_validate(entry.model_dump(mode="json")) == entry


def _player(discord_id: int, name: str, team: str) -> CombinesPlayer:
    return CombinesPlayer(discord_id=discord_id, rsc_id=f"RSC{discord_id}", match_id=4812, team=team, name=name)


def _lobby() -> CombinesLobby:
    return CombinesLobby(
        id=4812,
        lobby_user="rsc4812",
        lobby_pass="nova",
        home_wins=0,
        away_wins=0,
        reported_rsc_id=None,
        confirmed_rsc_id=None,
        completed=False,
        cancelled=False,
        tier="Elite",
        guild_id=1,
        home=[_player(1, "Nova", "home"), _player(2, "Sable", "home")],
        away=[_player(4, "Under_score", "away")],
    )


def _guild(present: set[int]) -> MagicMock:
    guild = MagicMock(spec=discord.Guild)
    guild.id = 1

    def member(i: int):
        if i not in present:
            return None
        m = MagicMock(spec=discord.Member)
        m.id = i
        m.mention = f"<@{i}>"
        return m

    guild.get_member.side_effect = member
    return guild


class _Value:
    """Red Config value: awaitable for a read, async context manager for an edit.

    Like Red, the context manager holds the value's lock, so code that also takes
    `get_lock()` around it deadlocks here just as it does in the bot.
    """

    def __init__(self, data: dict | None = None):
        self.data = data or {}
        self._lock = asyncio.Lock()

    def get_lock(self) -> asyncio.Lock:
        return self._lock

    def __call__(self):
        return _ValueCtx(self)


class _ValueCtx:
    def __init__(self, value: _Value):
        self.value = value

    def __await__(self):
        async def read():
            return self.value.data

        return read().__await__()

    async def __aenter__(self):
        await self.value.get_lock().acquire()
        return self.value.data

    async def __aexit__(self, *exc):
        self.value.get_lock().release()
        return False


def _store(data: dict | None = None) -> MagicMock:
    store = MagicMock()
    store.LobbyMessages = _Value(data)
    return store


def _channel(n: int, guild_id: int = 1) -> MagicMock:
    channel = MagicMock(spec=discord.VoiceChannel)
    channel.jump_url = f"https://discord.com/channels/{guild_id}/{n}"
    return channel


class TestLobbyCardBuilder:
    def test_players_and_channels(self):
        card = lobby_card(
            _guild({1, 4}),
            _lobby(),
            kind=LobbyKind.COMBINE,
            channels=[_channel(10), _channel(11)],
            match_url="https://devleague.rscna.com/combine/4812",
            started_at=STARTED,
        )
        # Players outside the server show their name, escaped, instead of a dead mention
        assert card.home == ("<@1>", "Sable")
        assert card.away == ("<@4>",)
        assert card.lobby_maker == "Nova"
        assert (card.home_vc_url, card.away_vc_url) == ("https://discord.com/channels/1/10", "https://discord.com/channels/1/11")


class TestPostLobby:
    async def test_posts_stores_and_dms_each_player(self):
        guild = _guild({1, 2, 4})
        channel = MagicMock(spec=discord.TextChannel)
        channel.id = 77
        channel.send = AsyncMock(return_value=MagicMock(id=88))
        cog = MagicMock()
        cog.live_emoji.return_value = LIVE
        cog._lobby_dm_helper.enqueue = AsyncMock()
        store = _store()
        active = {(1, 4812)}

        card = _card(home=("<@1>", "<@2>"), away=("<@4>",))
        await post_lobby(cog, guild, _lobby(), card, channel, store, active)

        send = channel.send.await_args
        assert send is not None
        assert send.kwargs["allowed_mentions"] is lobby.LOBBY_MENTIONS
        assert "content" not in send.kwargs and "embed" not in send.kwargs
        saved = LobbyMessages.model_validate(store.LobbyMessages.data["4812"])
        assert (saved.channel_id, saved.message_id, saved.executor_id, saved.dms) == (77, 88, 1, [])

        dms = cog._lobby_dm_helper.enqueue.await_args_list
        assert [c.args[0].id for c in dms] == [1, 2, 4]
        lines = [_lines(_container(c.kwargs["view"]))[1] for c in dms]
        assert lines == [
            "You're on **Home** · you make the lobby",
            "You're on **Home**",
            "You're on **Away** · your team uploads the replays",
        ]

        # Queued DMs are dropped once the match is torn down
        precheck = dms[0].kwargs["precheck"]
        assert await precheck() is True
        active.clear()
        assert await precheck() is False

    async def test_posts_one_lobby_after_another(self):
        # Each post must release the store's lock, or every lobby after the first hangs
        guild = _guild({1, 2, 4})
        channel = MagicMock(spec=discord.TextChannel)
        channel.id = 77
        channel.send = AsyncMock(return_value=MagicMock(id=88))
        cog = MagicMock()
        cog.live_emoji.return_value = LIVE
        cog._lobby_dm_helper.enqueue = AsyncMock()
        store = _store()

        for lobby_id in (4812, 4813):
            card = _card(lobby_id=lobby_id, home=("<@1>", "<@2>"), away=("<@4>",))
            await asyncio.wait_for(post_lobby(cog, guild, _lobby(), card, channel, store, set()), timeout=1)

        assert set(store.LobbyMessages.data) == {"4812", "4813"}

    async def test_sent_dm_is_recorded_for_teardown(self):
        store = _store({"4812": LobbyMessages(card=_card(), channel_id=77, message_id=88).model_dump(mode="json")})
        record = lobby._record_dm(store, _card(), LobbyTeam.AWAY)
        msg = MagicMock(spec=discord.Message)
        msg.id = 9
        msg.channel = MagicMock(id=5)

        await record(DMOutcome.SENT, msg)

        assert store.LobbyMessages.data["4812"]["dms"] == [[5, 9, "Away"]]

    async def test_dm_sent_after_teardown_is_marked_final_at_once(self):
        store = _store()
        record = lobby._record_dm(store, _card(), LobbyTeam.HOME)
        msg = MagicMock(spec=discord.Message)
        msg.edit = AsyncMock()

        await record(DMOutcome.SENT, msg)

        edit = msg.edit.await_args
        assert edit is not None
        assert _lines(_container(edit.kwargs["view"]))[:2] == ["## Final · Combine 4812", "You were on **Home**"]

    async def test_failed_dm_is_ignored(self):
        store = _store({"4812": {}})
        await lobby._record_dm(store, _card(), LobbyTeam.HOME)(DMOutcome.FAILED, None)
        assert store.LobbyMessages.data == {"4812": {}}


class TestFinishLobby:
    async def test_edits_channel_post_and_dms_then_forgets(self):
        entry = LobbyMessages(card=_card(), channel_id=77, message_id=88, dms=[(5, 9, LobbyTeam.AWAY)])
        store = _store({"4812": entry.model_dump(mode="json")})
        partials: dict[int, MagicMock] = {}

        def messageable(channel_id, **_):
            channel = MagicMock()
            message = MagicMock()
            message.edit = AsyncMock()
            channel.get_partial_message.return_value = message
            partials[channel_id] = message
            return channel

        cog = MagicMock()
        cog.bot.get_partial_messageable.side_effect = messageable

        stored = await lobby_messages(store, 4812)
        assert stored == entry
        await finish_lobby(cog, entry, store, LobbyScore(home_wins=3, away_wins=1))

        post = partials[77].edit.await_args
        dm = partials[5].edit.await_args
        assert post is not None and dm is not None
        assert _texts(_container(post.kwargs["view"]))[:2] == ["## Final · Combine 4812", SCORE_LINE]
        assert _lines(_container(dm.kwargs["view"]))[1] == "You were on **Away**"
        assert store.LobbyMessages.data == {}

    async def test_unreadable_record_is_skipped(self):
        assert await lobby_messages(_store({"4812": {"card": "nope"}}), 4812) is None


class TestTeamSeparators:
    @pytest.mark.parametrize("final", [False, True])
    def test_a_line_above_each_team(self, final):
        children = _container(_card().render(final=final)).children
        for label in ("**Home**", "**Away**"):
            index = next(i for i, c in enumerate(children) if label in _texts_of(c))
            assert isinstance(children[index - 1], ui.Separator)


def _texts_of(item: ui.Item) -> str:
    if isinstance(item, ui.TextDisplay):
        return item.content
    if isinstance(item, ui.Section):
        return "\n".join(t.content for t in item.children if isinstance(t, ui.TextDisplay))
    return ""
