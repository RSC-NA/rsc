import re
from datetime import UTC, datetime
from typing import Any
from unittest.mock import AsyncMock, MagicMock, patch

import discord
import pytest
from discord import ui
from rscapi.models.match import Match
from rscapi.models.team_player import TeamPlayer

from rsc.ballchasing.views import FALLBACK_LOGO
from rsc.embeds import ErrorEmbed
from rsc.enums import MatchTeamEnum
from rsc.matches.matches import MatchMixIn
from rsc.matches.views import MATCH_REFRESH_TEMPLATE, Contact, MatchCard, MatchRefreshButton, TeamBlock, player_line
from rsc.utils.website import bracket_url

GUILD_ID = 1234
STARTS = datetime(2026, 11, 5, 2, 0, tzinfo=UTC)
EPOCH = int(STARTS.timestamp())
MATCH_URL = "https://www.rscna.com/matches/36901/?league=1&season=11&source=matches"
REPORTMATCH = "</reportmatch:42>"


# --- Pure rendering ---


def _team(name: str, **overrides) -> TeamBlock:
    fields: dict[str, Any] = {
        "name": name,
        "franchise": f"{name} Franchise",
        "gm": f"<@{len(name)}>",
        "logo_url": f"https://cdn.example/{name.lower()}.png",
        "players": (f"{name}1 (C)", f"{name}2", f"{name}3", f"{name}4 (Sub)", f"{name}5 (IR)"),
    }
    fields.update(overrides)
    return TeamBlock(**fields)


def _card(**overrides) -> MatchCard:
    fields: dict[str, Any] = {
        "tier": "Elite",
        "label": "Match Day 7",
        "series": "4-game series",
        "starts": STARTS,
        "lobby_name": "RSC 4821",
        "lobby_pass": "vtg92",
        "home": _team("Quantum"),
        "away": _team("Voltage"),
        "side": MatchTeamEnum.HOME,
        "contact": Contact("<@500>", "captain"),
        "check_in_channel": "<#77>",
        "match_url": MATCH_URL,
        "bracket_url": None,
        "reportmatch": REPORTMATCH,
        "colour": discord.Colour.orange(),
    }
    fields.update(overrides)
    return MatchCard(**fields)


def _container(view: ui.LayoutView) -> ui.Container:
    (container,) = view.children
    assert isinstance(container, ui.Container)
    return container


def _top_texts(view: ui.LayoutView) -> list[str]:
    return [c.content for c in _container(view).children if isinstance(c, ui.TextDisplay)]


def _sections(view: ui.LayoutView) -> list[ui.Section]:
    return [c for c in _container(view).children if isinstance(c, ui.Section)]


def _section_texts(section: ui.Section) -> list[str]:
    return [c.content for c in section.children if isinstance(c, ui.TextDisplay)]


def _buttons(view: ui.LayoutView) -> list[ui.Button]:
    return [b for row in _container(view).children if isinstance(row, ui.ActionRow) for b in row.children if isinstance(b, ui.Button)]


class TestRender:
    def test_full_card(self):
        view, files = _card().render()
        assert _top_texts(view) == [
            "-# Elite · Match Day 7 · 4-game series",
            "## Quantum vs Voltage",
            f"<t:{EPOCH}:F> · <t:{EPOCH}:R>",
            "**Lobby** `RSC 4821`\n**Password** `vtg92`",
            "You're **home**. Create the lobby, then ping <@500>, the Voltage captain, in <#77> when your team is ready.",
            f"-# Turn on crossplay. Save every replay and screenshot the scoreboard before you leave. Report with {REPORTMATCH}.",
        ]
        quantum, voltage = _sections(view)
        assert _section_texts(quantum) == [
            "### Quantum",
            "-# Your team · home · Quantum Franchise · GM <@7>",
            "```\nQuantum1 (C)\nQuantum2\nQuantum3\nQuantum4 (Sub)\nQuantum5 (IR)\n```",
        ]
        assert isinstance(quantum.accessory, ui.Thumbnail)
        assert quantum.accessory.media.url == "https://cdn.example/quantum.png"
        assert _section_texts(voltage)[1] == "-# Opponent · away · Voltage Franchise · GM <@7>"
        assert files == []
        assert _container(view).accent_colour == discord.Colour.orange()

    def test_full_rosters_fit_the_component_limit(self):
        view, _ = _card(bracket_url="https://www.rscna.com/playoffs/").render()
        assert view.total_children_count <= 40

    def test_teams_and_buttons_are_split_by_lines(self):
        kinds = [type(c) for c in _container(_card().render()[0]).children]
        assert kinds == [
            ui.TextDisplay,
            ui.TextDisplay,
            ui.TextDisplay,
            ui.Separator,
            ui.TextDisplay,
            ui.TextDisplay,
            ui.Separator,
            ui.Section,
            ui.Separator,
            ui.Section,
            ui.Separator,
            ui.TextDisplay,
            ui.ActionRow,
        ]

    def test_away_viewer_sees_their_team_first(self):
        view, _ = _card(side=MatchTeamEnum.AWAY, contact=Contact("<@501>", "captain")).render()
        voltage, quantum = _sections(view)
        assert _section_texts(voltage)[:2] == ["### Voltage", "-# Your team · away · Voltage Franchise · GM <@7>"]
        assert _section_texts(quantum)[:2] == ["### Quantum", "-# Opponent · home · Quantum Franchise · GM <@7>"]
        # The header keeps home first
        assert _top_texts(view)[1] == "## Quantum vs Voltage"
        assert _top_texts(view)[4] == (
            "You're **away**. <@501>, the Quantum captain, pings you in <#77> when the lobby is up. Join once your whole team is ready."
        )

    def test_staff_outside_the_match_see_home_first_with_no_side(self):
        view, _ = _card(side=None, contact=None).render()
        quantum, voltage = _sections(view)
        assert _section_texts(quantum)[1] == "-# home · Quantum Franchise · GM <@7>"
        assert _section_texts(voltage)[1] == "-# away · Voltage Franchise · GM <@7>"
        assert not any(t.startswith("You're") for t in _top_texts(view))

    @pytest.mark.parametrize(
        ("side", "contact", "channel", "line"),
        [
            (
                MatchTeamEnum.HOME,
                Contact("<@22>", "GM"),
                "<#77>",
                "You're **home**. Create the lobby, then ping <@22>, the Voltage GM, in <#77> when your team is ready.",
            ),
            (
                MatchTeamEnum.HOME,
                Contact("<@500>", "captain"),
                None,
                "You're **home**. Create the lobby, then ping <@500>, the Voltage captain, when your team is ready.",
            ),
            (
                MatchTeamEnum.HOME,
                None,
                None,
                "You're **home**. Create the lobby, then ping the Voltage team when your team is ready.",
            ),
            (
                MatchTeamEnum.AWAY,
                None,
                "<#77>",
                "You're **away**. The Quantum team pings you in <#77> when the lobby is up. Join once your whole team is ready.",
            ),
            (
                MatchTeamEnum.AWAY,
                Contact("<@11>", "GM"),
                None,
                "You're **away**. <@11>, the Quantum GM, pings you when the lobby is up. Join once your whole team is ready.",
            ),
        ],
    )
    def test_check_in_line(self, side, contact, channel, line):
        view, _ = _card(side=side, contact=contact, check_in_channel=channel).render()
        assert _top_texts(view)[4] == line

    def test_markdown_in_names_is_escaped_outside_the_roster_only(self):
        home = _team("Under_score", franchise="*Stars*", gm="Gm_Name", players=("snake_case_guy",))
        view, _ = _card(home=home, side=MatchTeamEnum.AWAY).render()
        assert _top_texts(view)[1] == r"## Under\_score vs Voltage"
        assert "the Under\\_score captain" in _top_texts(view)[4]
        section = _sections(view)[1]
        assert _section_texts(section) == [
            r"### Under\_score",
            r"-# Opponent · home · \*Stars\* · GM Gm_Name",
            "```\nsnake_case_guy\n```",
        ]

    def test_backticks_in_a_name_cannot_close_the_roster_block(self):
        view, _ = _card(home=_team("Quantum", players=("```evil```", "ok"))).render()
        roster = _section_texts(_sections(view)[0])[2]
        assert roster.startswith("```\n") and roster.endswith("\n```")
        inner = roster.removeprefix("```\n").removesuffix("\n```")
        assert "``" not in inner
        assert inner.replace("\N{ZERO WIDTH SPACE}", "") == "```evil```\nok"

    def test_a_backtick_in_the_lobby_uses_a_double_backtick_span(self):
        view, _ = _card(lobby_name="a`b").render()
        assert _top_texts(view)[3] == "**Lobby** `` a`b ``\n**Password** `vtg92`"

    def test_no_players_listed(self):
        view, _ = _card(away=_team("Voltage", players=())).render()
        assert _section_texts(_sections(view)[1])[2] == "No players listed"

    def test_missing_logos_share_one_bundled_file(self):
        view, files = _card(home=_team("Quantum", logo_url=None), away=_team("Voltage", logo_url=None)).render()
        (logo,) = files
        assert logo.filename == FALLBACK_LOGO.name
        for section in _sections(view):
            assert isinstance(section.accessory, ui.Thumbnail)
            assert section.accessory.media.url == f"attachment://{FALLBACK_LOGO.name}"

    def test_link_buttons(self):
        view, _ = _card(bracket_url="https://www.rscna.com/playoffs/?tier=Elite").render()
        assert [(b.label, b.url, b.style) for b in _buttons(view)] == [
            ("Match page", MATCH_URL, discord.ButtonStyle.link),
            ("Bracket", "https://www.rscna.com/playoffs/?tier=Elite", discord.ButtonStyle.link),
        ]

    def test_no_links_no_button_row(self):
        view, _ = _card(match_url=None).render()
        assert not any(isinstance(c, ui.ActionRow) for c in _container(view).children)


class TestPlayerLine:
    @staticmethod
    def _player(status: str | None = "RO", *, captain: bool = False, sub_status: int = 0) -> TeamPlayer:
        player = TeamPlayer.from_dict({"name": "api", "discord_id": 1, "status": status, "captain": captain, "sub_status": sub_status})
        assert player is not None
        return player

    @pytest.mark.parametrize(
        ("status", "sub_status", "line"),
        [
            ("RO", 0, "Kestrel"),
            ("RN", 0, "Kestrel"),
            ("FA", 0, "Kestrel (Sub)"),
            ("FA", 1, "Kestrel (Subbed Out)"),
            ("PF", 2, "Kestrel (Subbed In)"),
            ("IR", 0, "Kestrel (IR)"),
            ("AR", 0, "Kestrel (AGM IR)"),
        ],
    )
    def test_status_tags(self, status, sub_status, line):
        assert player_line("Kestrel", self._player(status, sub_status=sub_status), is_gm=False) == line

    def test_captain_then_status_then_gm(self):
        assert player_line("Kestrel", self._player("FA", captain=True), is_gm=True) == "Kestrel (C) (Sub) (GM)"

    @pytest.mark.parametrize("status", ["DR", "WV", "FR", None])
    def test_statuses_off_the_roster_are_skipped(self, status):
        assert player_line("Kestrel", self._player(status), is_gm=False) is None


class TestBracketUrl:
    def test_full(self):
        url = bracket_url("https://www.rscna.com", "Contender", league_id=1, season_id=11)
        assert url == "https://www.rscna.com/playoffs/?tier=Contender&league=1&season=11"

    def test_no_season(self):
        assert bracket_url("https://www.rscna.com/", "Pro Am", league_id=1) == "https://www.rscna.com/playoffs/?tier=Pro+Am&league=1"


class TestRefreshButton:
    @pytest.mark.parametrize("asked", [True, False])
    async def test_custom_id_round_trips(self, asked):
        button = MatchRefreshButton(1234, asked=asked)
        match = re.fullmatch(MATCH_REFRESH_TEMPLATE, button.custom_id)
        assert match
        rebuilt = await MatchRefreshButton.from_custom_id(MagicMock(), MagicMock(), match)
        assert (rebuilt.team_id, rebuilt.asked) == (1234, asked)
        assert len(button.custom_id) <= 100


# --- Gathering from the API ---


def _player(discord_id: int, name: str, *, status: str = "RO", captain: bool = False) -> dict[str, Any]:
    return {"name": name, "discord_id": discord_id, "status": status, "captain": captain, "sub_status": 0}


def _match(*, match_type: str = "REG", day: int = 7, home_captain: int = 101, away_captain: int = 201) -> Match:
    match = Match.from_dict(
        {
            "id": 36901,
            "day": day,
            "date": STARTS.isoformat(),
            "season_number": 24,
            "game_name": "RSC 4821",
            "game_pass": "vtg92",
            "num_games": 4 if match_type == "REG" else 5,
            "match_format": "GMS" if match_type == "REG" else "BO5",
            "match_type": match_type,
            "results": None,
            "home_team": {
                "id": 1,
                "name": "Quantum",
                "franchise": "Fusion Esports",
                "tier": "Elite",
                "gm": {"rsc_name": "Monty", "discord_id": 11},
                "players": [
                    _player(home_captain, "Kestrel", captain=True),
                    _player(102, "Bramble"),
                    _player(11, "Monty"),
                    _player(103, "Gone", status="DR"),
                ],
            },
            "away_team": {
                "id": 2,
                "name": "Voltage",
                "franchise": "Storm Syndicate",
                "tier": "Elite",
                "gm": {"rsc_name": "Sable_", "discord_id": 22},
                "players": [_player(away_captain, "Ridge", captain=True), _player(202, "Lumen", status="IR")],
            },
        }
    )
    assert match is not None
    return match


def _member(discord_id: int, display_name: str) -> MagicMock:
    member = MagicMock(spec=discord.Member)
    member.id = discord_id
    member.display_name = display_name
    member.mention = f"<@{discord_id}>"
    return member


def _guild(*, members: dict[int, str], check_in: bool = True) -> MagicMock:
    guild = MagicMock(spec=discord.Guild)
    guild.id = GUILD_ID
    guild.name = "RSC"
    guild.icon = MagicMock(url="https://cdn.example/guild.png")
    roster = {i: _member(i, name) for i, name in members.items()}
    guild.get_member.side_effect = roster.get
    channel = MagicMock(spec=discord.TextChannel)
    channel.name = "match-check-in"
    channel.mention = "<#77>"
    guild.text_channels = [channel] if check_in else []
    return guild


def _mixin(**attrs) -> MatchMixIn:
    saved = MatchMixIn.__abstractmethods__
    MatchMixIn.__abstractmethods__ = frozenset()
    try:
        m = object.__new__(MatchMixIn)
    finally:
        MatchMixIn.__abstractmethods__ = saved
    reportmatch = MagicMock()
    reportmatch.name = "reportmatch"
    reportmatch.mention = REPORTMATCH
    defaults: dict[str, Any] = {
        "bot": MagicMock(tree=MagicMock(fetch_commands=AsyncMock(return_value=[reportmatch]))),
        "_api_conf": {GUILD_ID: MagicMock(host="https://www.rscna.com/api/v1")},
        "_league": {GUILD_ID: 1},
        "_reportmatch_mentions": {},
        "season_id_for_number": AsyncMock(return_value=11),
        "franchises": AsyncMock(return_value=[MagicMock(id=5)]),
        "franchise_logo": AsyncMock(return_value="https://cdn.example/logo.png"),
        "match_page_link": AsyncMock(return_value=MATCH_URL),
    }
    defaults.update(attrs)
    for k, v in defaults.items():
        setattr(m, k, v)
    return m


@pytest.fixture(autouse=True)
def _tier_colour():
    with patch("rsc.matches.matches.tier_color_by_name", AsyncMock(return_value=discord.Colour.orange())):
        yield


class TestMatchCardGathering:
    async def test_rosters_strip_accolades_keep_prefixes_and_tag_the_gm(self):
        guild = _guild(members={101: "<0> | Kestrel \N{TROPHY}\N{WHITE MEDIUM STAR}", 11: "FUS | Monty", 201: "Ridge"})
        card = await _mixin().match_card(guild, _match(), MatchTeamEnum.HOME)
        # Bramble isn't in the server, so the API name is used. Gone was dropped from the roster.
        assert card.home.players == ("<0> | Kestrel (C)", "Bramble", "FUS | Monty (GM)")
        assert card.away.players == ("Ridge (C)", "Lumen (IR)")
        assert card.home.gm == "<@11>"
        # Not in the server: the escaped API name
        assert card.away.gm == r"Sable\_"

    async def test_contact_is_the_opposing_captain(self):
        guild = _guild(members={201: "Ridge", 22: "Sable"})
        card = await _mixin().match_card(guild, _match(), MatchTeamEnum.HOME)
        assert card.contact == Contact("<@201>", "captain")
        assert card.check_in_channel == "<#77>"

    async def test_contact_falls_back_to_the_gm_when_the_captain_left(self):
        guild = _guild(members={22: "Sable"})
        card = await _mixin().match_card(guild, _match(), MatchTeamEnum.HOME)
        assert card.contact == Contact("<@22>", "GM")

    async def test_away_viewer_contacts_the_home_side(self):
        guild = _guild(members={101: "Kestrel", 201: "Ridge"})
        card = await _mixin().match_card(guild, _match(), MatchTeamEnum.AWAY)
        assert card.contact == Contact("<@101>", "captain")

    async def test_no_one_to_contact_and_no_check_in_channel(self):
        card = await _mixin().match_card(_guild(members={}, check_in=False), _match(), MatchTeamEnum.HOME)
        assert card.contact is None
        assert card.check_in_channel is None

    async def test_regular_season_has_no_bracket(self):
        card = await _mixin().match_card(_guild(members={}), _match(), MatchTeamEnum.HOME)
        assert card.bracket_url is None
        assert card.series == "4-game series"
        assert card.label == "Match Day 7"

    @pytest.mark.parametrize(("match_type", "day", "label"), [("PST", 2, "Quarterfinals"), ("FNL", 1, "Finals")])
    async def test_playoffs_link_the_bracket(self, match_type, day, label):
        card = await _mixin().match_card(_guild(members={}), _match(match_type=match_type, day=day), MatchTeamEnum.HOME)
        assert card.bracket_url == "https://www.rscna.com/playoffs/?tier=Elite&league=1&season=11"
        assert card.series == "Best of 5"
        assert card.label == label

    async def test_logos_fall_back_to_the_server_icon(self):
        mixin = _mixin(franchise_logo=AsyncMock(return_value=None))
        card = await mixin.match_card(_guild(members={}), _match(), MatchTeamEnum.HOME)
        assert card.home.logo_url == card.away.logo_url == "https://cdn.example/guild.png"

    async def test_reportmatch_mention_is_fetched_once_per_server(self):
        mixin = _mixin()
        guild = _guild(members={})
        first = await mixin.match_card(guild, _match(), MatchTeamEnum.HOME)
        second = await mixin.match_card(guild, _match(), MatchTeamEnum.HOME)
        assert first.reportmatch == second.reportmatch == REPORTMATCH
        mixin.bot.tree.fetch_commands.assert_awaited_once()

    async def test_unsynced_reportmatch_is_plain_code(self):
        mixin = _mixin(bot=MagicMock(tree=MagicMock(fetch_commands=AsyncMock(return_value=[]))))
        card = await mixin.match_card(_guild(members={}), _match(), MatchTeamEnum.HOME)
        assert card.reportmatch == "`/reportmatch`"


class TestMatchReply:
    @staticmethod
    def _viewer(*, manage_guild: bool = False) -> MagicMock:
        member = _member(999, "Viewer")
        member.guild_permissions = discord.Permissions(manage_guild=manage_guild)
        return member

    async def test_a_named_team_needs_a_franchise_manager(self):
        mixin = _mixin(next_match=AsyncMock(return_value=_match()), agm_franchise_of=AsyncMock(return_value=None))
        reply = await mixin.match_reply(_guild(members={}), self._viewer(), 1, asked=True)
        assert isinstance(reply, ErrorEmbed)
        assert reply.description and "Only franchise managers" in reply.description

    async def test_staff_see_a_named_team_without_a_side(self):
        mixin = _mixin(next_match=AsyncMock(return_value=_match()), agm_franchise_of=AsyncMock(return_value=None))
        reply = await mixin.match_reply(_guild(members={}), self._viewer(manage_guild=True), 1, asked=True)
        assert isinstance(reply, MatchCard)
        assert reply.side is None

    async def test_a_player_sees_their_own_side(self):
        mixin = _mixin(next_match=AsyncMock(return_value=_match()), agm_franchise_of=AsyncMock(return_value=None))
        viewer = self._viewer()
        viewer.id = 202
        reply = await mixin.match_reply(_guild(members={}), viewer, 2, asked=False)
        assert isinstance(reply, MatchCard)
        assert reply.side is MatchTeamEnum.AWAY

    async def test_missing_gm_data_is_an_error_card_not_an_exception(self):
        match = _match()
        match.home_team.gm = None
        mixin = _mixin(next_match=AsyncMock(return_value=match), agm_franchise_of=AsyncMock(return_value=None))
        reply = await mixin.match_reply(_guild(members={}), self._viewer(), 1, asked=True)
        assert isinstance(reply, discord.Embed)
        assert reply.description and "GM" in reply.description

    async def test_a_day_with_no_match_skips_the_pending_series(self):
        pending = AsyncMock()
        mixin = _mixin(match_by_day=AsyncMock(return_value=None), pending_series=pending)
        assert await mixin.match_reply(_guild(members={}), self._viewer(), 1, asked=False, day=3) is None
        pending.assert_not_awaited()
