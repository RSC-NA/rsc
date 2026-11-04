from unittest.mock import AsyncMock, MagicMock, patch

import discord
import pytest
from discord import ui
from rscapi.models.franchise_gm import FranchiseGM
from rscapi.models.league_player import LeaguePlayer
from rscapi.models.league_player_member import LeaguePlayerMember
from rscapi.models.player_franchise import PlayerFranchise
from rscapi.models.player_team import PlayerTeam
from rscapi.models.tier import Tier

from rsc.enums import Status, SubStatus
from rsc.teams.teams import TeamMixIn
from rsc.teams.views import RosterCard, RosterGroup, RosterRow
from rsc.views import ResultView

from .utils import command_callback

GUILD_ID = 395806681994493964
LEAGUE_ID = 3
GM_ID = 111
SITE = "https://www.rscna.com"
LOGO = "https://cdn.example/hex.png"
MONTY = FranchiseGM.model_construct(rsc_name="Monty", discord_id=GM_ID)


def _player(
    name: str,
    discord_id: int,
    mmr: int | None,
    *,
    rsc_id: str | None = "RSC001187",
    status: Status = Status.ROSTERED,
    sub_status: SubStatus = SubStatus.NOT,
    captain: bool = False,
    gm: FranchiseGM | None = MONTY,
    team: str = "Voltage",
) -> LeaguePlayer:
    franchise = PlayerFranchise.model_construct(id=7, name="Hex Systems", gm=gm)
    return LeaguePlayer.model_construct(
        player=LeaguePlayerMember.model_construct(name=name, rsc_id=rsc_id, discord_id=discord_id),
        team=PlayerTeam.model_construct(id=42, name=team, franchise=franchise),
        tier=Tier.model_construct(name="Premier", position=1),
        status=status,
        sub_status=sub_status,
        captain=captain,
        current_mmr=mmr,
    )


def _mixin(*, configured: bool = True, logo: str | None = LOGO, players: list[LeaguePlayer] | None = None) -> TeamMixIn:
    saved = TeamMixIn.__abstractmethods__
    TeamMixIn.__abstractmethods__ = frozenset()
    try:
        m = object.__new__(TeamMixIn)
    finally:
        TeamMixIn.__abstractmethods__ = saved
    attrs = {
        "_api_conf": {GUILD_ID: MagicMock(host=f"{SITE}/api/v1")} if configured else {},
        "_league": {GUILD_ID: LEAGUE_ID} if configured else {},
        "franchise_logo": AsyncMock(return_value=logo),
        "players": AsyncMock(return_value=players or []),
    }
    for k, v in attrs.items():
        setattr(m, k, v)
    return m


@pytest.fixture(autouse=True)
def _tier_colour():
    with patch("rsc.teams.teams.utils.tier_color_by_name", AsyncMock(return_value=discord.Colour.orange())):
        yield


async def _build(players: list[LeaguePlayer], guild, **mixin) -> ui.LayoutView:
    return await _mixin(**mixin).build_roster_card(guild, players)


def _container(view: ui.LayoutView) -> ui.Container:
    (container,) = view.children
    assert isinstance(container, ui.Container)
    return container


def _texts(view: ui.LayoutView) -> list[str]:
    out = []
    for child in _container(view).children:
        if isinstance(child, ui.TextDisplay):
            out.append(child.content)
        elif isinstance(child, ui.Section):
            out.extend(t.content for t in child.children if isinstance(t, ui.TextDisplay))
    return out


def _profile_buttons(view: ui.LayoutView) -> list[ui.Button]:
    sections = [c for c in _container(view).children if isinstance(c, ui.Section)]
    return [s.accessory for s in sections if isinstance(s.accessory, ui.Button)]


def _link_row(view: ui.LayoutView) -> list[tuple[str | None, str | None]]:
    rows = [c for c in _container(view).children if isinstance(c, ui.ActionRow)]
    return [(b.label, b.url) for row in rows for b in row.children if isinstance(b, ui.Button)]


def _component_count(view: ui.LayoutView) -> int:
    # Every nested item counts toward Discord's 40, the container included
    return 1 + len(list(_container(view).walk_children()))


VOLTAGE = [
    _player("Abe", 201, 1500),
    _player("Monty", GM_ID, 1610, captain=True),
    _player("Sid", 202, 1450, sub_status=SubStatus.IN),
    _player("Otto", 203, 1490, sub_status=SubStatus.OUT),
    _player("Agnes", 204, 1530, status=Status.AGMIR),
    _player("Ira", 205, 1410, status=Status.IR),
]


class TestRosterContent:
    async def test_groups_and_small_lines(self, mock_guild):
        view = await _build(VOLTAGE, mock_guild)
        assert _container(view).accent_colour == discord.Colour.orange()
        assert _texts(view) == [
            "-# Premier · Hex Systems",
            "## Voltage",
            "General Manager **Monty**",
            "-# ACTIVE ROSTER",
            # The GM and captain lead, the rest keep the API's order
            "**Monty**\n-# 1610 MMR · GM · Captain",
            "**Abe**\n-# 1500 MMR",
            "**Sid**\n-# 1450 MMR · Sub",
            "-# SUBBED OUT",
            "**Otto**\n-# 1490 MMR",
            "-# INACTIVE RESERVE",
            "**Agnes**\n-# 1530 MMR · AGM",
            "**Ira**\n-# 1410 MMR",
        ]

    async def test_only_non_empty_groups_get_a_label(self, mock_guild):
        view = await _build([VOLTAGE[0], VOLTAGE[5]], mock_guild)
        labels = [t for t in _texts(view) if t.startswith("-# ") and t.isupper()]
        assert labels == ["-# ACTIVE ROSTER", "-# INACTIVE RESERVE"]

    async def test_player_without_mmr_or_tags_is_just_the_name(self, mock_guild):
        view = await _build([_player("Nemo", 206, None)], mock_guild)
        assert _texts(view)[-1] == "**Nemo**"

    async def test_server_nickname_is_used_and_markdown_escaped(self, mock_guild):
        member = MagicMock(spec=discord.Member)
        member.display_name = "Under_score*"
        mock_guild.get_member.side_effect = lambda i: member if i == 201 else None
        view = await _build([VOLTAGE[0], _player("Not_here", 202, 1400)], mock_guild)
        assert "**Under\\_score\\***\n-# 1500 MMR" in _texts(view)
        assert "**Not\\_here**\n-# 1400 MMR" in _texts(view)


class TestRosterHeader:
    async def test_logo_sits_beside_the_header(self, mock_guild):
        view = await _build(VOLTAGE, mock_guild)
        header = _container(view).children[0]
        assert isinstance(header, ui.Section)
        assert isinstance(header.accessory, ui.Thumbnail) and header.accessory.media.url == LOGO

    async def test_falls_back_to_the_server_icon(self, mock_guild):
        view = await _build(VOLTAGE, mock_guild, logo=None)
        header = _container(view).children[0]
        assert isinstance(header, ui.Section) and isinstance(header.accessory, ui.Thumbnail)
        assert header.accessory.media.url == mock_guild.icon.url

    async def test_no_logo_and_no_gm(self, mock_guild):
        mock_guild.icon = None
        view = await _build([_player("Abe", 201, 1500, gm=None)], mock_guild, logo=None)
        first, second = _container(view).children[:2]
        assert isinstance(first, ui.TextDisplay) and first.content == "-# Premier · Hex Systems"
        assert isinstance(second, ui.TextDisplay) and second.content == "## Voltage"
        assert not any(t.startswith("General Manager") for t in _texts(view))


class TestRosterLinks:
    async def test_profile_and_page_links(self, mock_guild):
        view = await _build([VOLTAGE[0], _player("Ghost", 207, 1300, rsc_id=None)], mock_guild)
        linked, missing = _profile_buttons(view)
        assert (linked.label, linked.url, linked.disabled) == ("Profile", f"{SITE}/player/1187/?league={LEAGUE_ID}", False)
        assert (missing.label, missing.url, missing.disabled) == ("Profile", f"{SITE}/team/42/?league={LEAGUE_ID}", True)
        assert view.is_dispatchable() is False
        assert _link_row(view) == [
            ("Team page", f"{SITE}/team/42/?league={LEAGUE_ID}"),
            ("Franchise page", f"{SITE}/franchise/7/?league={LEAGUE_ID}"),
        ]

    async def test_no_site_leaves_off_every_button(self, mock_guild):
        view = await _build(VOLTAGE, mock_guild, configured=False)
        assert _profile_buttons(view) == []
        assert "**Monty**\n-# 1610 MMR · GM · Captain" in _texts(view)
        assert _link_row(view) == []
        assert not isinstance(_container(view).children[-1], ui.Separator)


def _card(rows: dict[RosterGroup, tuple[RosterRow, ...]], *, team_url: str | None = f"{SITE}/team/42/") -> RosterCard:
    return RosterCard(
        team="Voltage",
        franchise="Hex Systems",
        tier="Premier",
        colour=discord.Colour.orange(),
        gm="Monty",
        logo_url=LOGO,
        groups=rows,
        team_url=team_url,
        franchise_url=f"{SITE}/franchise/7/",
    )


def _rows(prefix: str, n: int) -> tuple[RosterRow, ...]:
    return tuple(RosterRow(name=f"{prefix}{i}", mmr=1500, profile_url=f"{SITE}/player/{i}/") for i in range(n))


class TestRosterSize:
    def test_full_team_with_every_group_fits_whole(self):
        rows = {RosterGroup.ACTIVE: _rows("A", 5), RosterGroup.SUBBED_OUT: _rows("S", 1), RosterGroup.INACTIVE_RESERVE: _rows("I", 2)}
        view = _card(rows).render()
        assert _component_count(view) <= 40
        assert sum(t.startswith("**") for t in _texts(view)) == 8
        assert not any("more" in t for t in _texts(view))

    def test_one_component_over_the_limit_is_capped(self):
        # 1 container + 5 header + 4 foot + 2 labels of 2 + 9 rows of 3 = 41
        rows = {RosterGroup.ACTIVE: _rows("A", 8), RosterGroup.SUBBED_OUT: _rows("S", 1)}
        view = _card(rows).render()
        assert _component_count(view) <= 40
        assert "-# SUBBED OUT" not in _texts(view)
        assert _texts(view)[-1] == "-# And 1 more on the team page"

    def test_large_roster_is_capped_with_a_more_line(self):
        view = _card({RosterGroup.ACTIVE: _rows("A", 20)}).render()
        assert _component_count(view) <= 40
        # 40, less the container, the 5 header items, the 4 foot items, the label's 2 and the "more" line,
        # leaves room for 9 rows of 3
        names = [t for t in _texts(view) if t.startswith("**")]
        assert names == [f"**A{i}**\n-# 1500 MMR" for i in range(9)]
        assert _texts(view)[-1] == "-# And 11 more on the team page"

    def test_later_groups_are_dropped_first(self):
        # 8 rows over three groups fill all 40, so making room for the "more" line pushes out the IR group
        rows = {RosterGroup.ACTIVE: _rows("A", 6), RosterGroup.SUBBED_OUT: _rows("S", 1), RosterGroup.INACTIVE_RESERVE: _rows("I", 3)}
        view = _card(rows).render()
        assert _component_count(view) <= 40
        names = [t.split("**")[1] for t in _texts(view) if t.startswith("**")]
        assert names == ["A0", "A1", "A2", "A3", "A4", "A5", "S0"]
        assert "-# INACTIVE RESERVE" not in _texts(view)
        assert _texts(view)[-1] == "-# And 3 more on the team page"

    def test_more_line_without_a_team_page(self):
        view = _card({RosterGroup.ACTIVE: _rows("A", 20)}, team_url=None).render()
        assert _component_count(view) <= 40
        assert _texts(view)[-1].startswith("-# And ") and _texts(view)[-1].endswith(" more")


def _interaction(guild) -> MagicMock:
    interaction = MagicMock()
    interaction.guild = guild
    interaction.response.defer = AsyncMock()
    interaction.followup.send = AsyncMock()
    return interaction


class TestRosterCommand:
    async def test_sends_the_card_publicly_without_pings(self, mock_guild):
        mixin = _mixin(players=[*VOLTAGE, _player("Elsewhere", 300, 1200, team="Other")])
        interaction = _interaction(mock_guild)

        await command_callback(TeamMixIn._roster_cmd)(mixin, interaction, "voltage")

        send = interaction.followup.send.await_args
        assert send is not None
        assert send.kwargs.get("ephemeral", False) is False
        assert send.kwargs["allowed_mentions"].users is False
        texts = _texts(send.kwargs["view"])
        assert texts[1] == "## Voltage"
        assert not any("Elsewhere" in t for t in texts)

    async def test_unknown_team_is_a_private_red_card(self, mock_guild):
        mixin = _mixin(players=[])
        interaction = _interaction(mock_guild)

        await command_callback(TeamMixIn._roster_cmd)(mixin, interaction, "No_Such")

        send = interaction.followup.send.await_args
        assert send is not None
        assert send.kwargs["ephemeral"] is True
        view = send.kwargs["view"]
        assert isinstance(view, ResultView)
        assert _container(view).accent_colour == discord.Colour.red()
        assert _texts(view)[0] == "## Team not found"
        assert _texts(view)[1].startswith("No team called **No\\_Such** has rostered players.")
