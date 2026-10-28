import re
from typing import Any
from unittest.mock import AsyncMock, MagicMock, create_autospec, patch

import discord
from discord import ui
from redbot.core.bot import Red
from rscapi.models.tracker_link import TrackerLink

from rsc.core import RSC
from rsc.const import RSC_TRACKER_URL
from rsc.enums import Status
from rsc.members.members import MemberMixIn
from rsc.members.views.player_info import PLAYER_TRACKERS_TEMPLATE, PlayerCard, PlayerInfoButton, PlayerTrackersButton
from rsc.trackers.trackers import TrackerMixIn
from rsc.trackers.views import tracker_accounts_card

from .utils import command_callback

PLAYER_ID = 138778232802508801
GUILD_ID = 395806681994493964
NBSP = "\N{NO-BREAK SPACE}"
# Labels padded to the width of "Franchise", so the values line up
ROWS = f"`Tier{NBSP * 5}` Premier\n`Team{NBSP * 5}` Singularity\n`Franchise` Hex Systems\n`Status{NBSP * 3}` Rostered"


def _card(**overrides) -> PlayerCard:
    fields: dict[str, Any] = {
        "name": "Monty",
        "discord_id": PLAYER_ID,
        "status": "Rostered",
        "colour": discord.Colour.orange(),
        "tier": "Premier",
        "team": "Singularity",
        "franchise": "Hex Systems",
        "logo_url": "https://cdn.example/hex.png",
        "current_mmr": 1655,
        "base_mmr": 1640,
    }
    fields.update(overrides)
    return PlayerCard(**fields)


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


def _buttons(view: ui.LayoutView) -> list[ui.Item]:
    return [b for row in _container(view).children if isinstance(row, ui.ActionRow) for b in row.children]


class TestPlayerCard:
    def test_layout(self):
        view = _card().render()
        container = _container(view)
        assert container.accent_colour == discord.Colour.orange()
        section = container.children[0]
        assert isinstance(section, ui.Section)
        assert isinstance(section.accessory, ui.Thumbnail) and section.accessory.media.url == "https://cdn.example/hex.png"
        assert _texts(view) == [
            f"## Monty\n-# <@{PLAYER_ID}>",
            # Labelled, full width outside the Section, so the logo doesn't squeeze it on phones
            ROWS,
            "-# Current MMR 1655 · Base MMR 1640",
        ]
        assert isinstance(container.children[1], ui.TextDisplay)

    def test_buttons_are_coloured(self):
        team, franchise, trackers = _buttons(_card().render())
        assert isinstance(team, PlayerInfoButton) and isinstance(franchise, PlayerInfoButton)
        assert (team.item.label, team.item.style) == ("Team", discord.ButtonStyle.primary)
        assert (franchise.item.label, franchise.item.style) == ("Franchise", discord.ButtonStyle.primary)
        assert isinstance(trackers, PlayerTrackersButton)
        assert (trackers.item.label, trackers.item.style) == ("Trackers", discord.ButtonStyle.success)

    def test_free_agent_without_team_or_franchise(self):
        view = _card(team=None, franchise=None, status="Free Agent").render()
        assert _texts(view)[1] == f"`Tier{NBSP * 5}` Premier\n`Status{NBSP * 3}` Free Agent"
        (trackers,) = _buttons(view)
        assert isinstance(trackers, PlayerTrackersButton)

    def test_franchise_is_plain_escaped_text(self):
        view = _card(franchise="Under_score").render()
        assert "`Franchise` Under\\_score" in _texts(view)[1].splitlines()

    def test_no_mmr_no_separator(self):
        view = _card(current_mmr=None, base_mmr=None).render()
        assert not any(isinstance(c, ui.Separator) for c in _container(view).children)

    def test_no_logo_no_section(self):
        view = _card(logo_url=None).render()
        assert isinstance(_container(view).children[0], ui.TextDisplay)

    def test_within_component_limits(self):
        assert _card().render().total_children_count <= 40


def _tracker(platform: str, *, name: str = "Monty", platform_id: str = "76561197960409023") -> TrackerLink:
    return TrackerLink.model_construct(
        link=f"https://rocketleague.tracker.network/rocket-league/profile/{platform.lower()}/{name}/overview",
        platform=MagicMock(value=platform),
        name=name,
        platform_id=platform_id,
    )


class TestTrackerAccountsCard:
    async def test_lists_each_account_as_a_link(self):
        view = await tracker_accounts_card(
            name="Monty",
            mention=f"<@{PLAYER_ID}>",
            trackers=[_tracker("STEAM"), _tracker("EPIC", name="Mon_ty")],
            avatar_url="https://cdn.example/avatar.png",
        )
        texts = _texts(view)
        assert texts[0] == "### Monty's accounts"
        assert texts[1].splitlines() == [
            "- [Steam · 76561197960409023](https://rocketleague.tracker.network/rocket-league/profile/steam/Monty/overview)",
            "- [Epic Games · Mon\\_ty](https://rocketleague.tracker.network/rocket-league/profile/epic/Mon_ty/overview)",
        ]
        (link,) = _buttons(view)
        assert isinstance(link, ui.Button) and (link.label, link.url) == ("RSC Tracker Links", RSC_TRACKER_URL)

    async def test_empty_state(self):
        view = await tracker_accounts_card(name="Monty", mention=f"<@{PLAYER_ID}>", trackers=[])
        assert _texts(view) == ["### Monty's accounts", f"<@{PLAYER_ID}> has no registered RL trackers."]


def _interaction(cog) -> MagicMock:
    guild = MagicMock(spec=discord.Guild)
    guild.id = GUILD_ID
    guild.name = "RSC"
    member = MagicMock(spec=discord.Member)
    member.display_name = "Monty"
    member.display_avatar.url = "https://cdn.example/avatar.png"
    guild.get_member.return_value = member
    cog._api_conf = {GUILD_ID: MagicMock()}
    cog._league = {GUILD_ID: 1}
    client = MagicMock(spec=Red)
    client.get_cog.return_value = cog
    interaction = MagicMock(spec=discord.Interaction)
    interaction.client = client
    interaction.guild = guild
    interaction.response = MagicMock()
    interaction.response.defer = AsyncMock()
    interaction.followup = MagicMock()
    interaction.followup.send = AsyncMock()
    return interaction


class TestPlayerTrackersButton:
    def test_custom_id_round_trips(self):
        button = PlayerTrackersButton(PLAYER_ID)
        match = re.fullmatch(PLAYER_TRACKERS_TEMPLATE, button.item.custom_id or "")
        assert match is not None and int(match["discord_id"]) == PLAYER_ID

    async def test_click_replies_privately_without_pings(self):
        cog = create_autospec(RSC, instance=True)
        cog.trackers.return_value = [_tracker("STEAM")]
        interaction = _interaction(cog)

        await PlayerTrackersButton(PLAYER_ID).callback(interaction)

        interaction.response.defer.assert_awaited_once_with(ephemeral=True)
        cog.trackers.assert_awaited_once_with(interaction.guild, player=PLAYER_ID)
        send = interaction.followup.send.await_args
        assert send is not None
        assert send.kwargs["ephemeral"] is True
        assert send.kwargs["allowed_mentions"].users is False
        assert _texts(send.kwargs["view"])[0] == "### Monty's accounts"


def _mixin(cls, **attrs):
    saved = cls.__abstractmethods__
    cls.__abstractmethods__ = frozenset()
    try:
        m = object.__new__(cls)
    finally:
        cls.__abstractmethods__ = saved
    for k, v in attrs.items():
        setattr(m, k, v)
    return m


def _command_interaction(guild) -> MagicMock:
    interaction = MagicMock()
    interaction.guild = guild
    interaction.response.defer = AsyncMock()
    interaction.followup.send = AsyncMock()
    return interaction


class TestPlayerInfoCommand:
    async def test_sends_the_card_without_pings(self, mock_guild, mock_member):
        league_player = MagicMock()
        league_player.status = Status.ROSTERED
        league_player.player.name = "Monty"
        league_player.tier.name = "Premier"
        league_player.team.name = "Singularity"
        league_player.team.franchise.name = "Hex Systems"
        league_player.team.franchise.id = 5
        league_player.current_mmr = 1655
        league_player.base_mmr = 1640
        mixin = _mixin(
            MemberMixIn,
            players=AsyncMock(return_value=[league_player]),
            franchise_logo=AsyncMock(return_value="https://cdn.example/hex.png"),
        )
        interaction = _command_interaction(mock_guild)

        with patch("rsc.members.members.utils.tier_color_by_name", AsyncMock(return_value=discord.Colour.orange())):
            await command_callback(MemberMixIn._playerinfo_cmd)(mixin, interaction, mock_member)

        send = interaction.followup.send.await_args
        assert send is not None
        assert send.kwargs["allowed_mentions"].users is False
        texts = _texts(send.kwargs["view"])
        assert texts[1] == ROWS
        assert texts[2] == "-# Current MMR 1655 · Base MMR 1640"


class TestAccountsCommand:
    async def test_sends_the_card_publicly_without_pings(self, mock_guild, mock_member):
        mixin = _mixin(TrackerMixIn, trackers=AsyncMock(return_value=[_tracker("STEAM")]))
        interaction = _command_interaction(mock_guild)
        mock_member.display_avatar = MagicMock(url="https://cdn.example/avatar.png")

        await command_callback(TrackerMixIn._accounts)(mixin, interaction, mock_member)

        send = interaction.followup.send.await_args
        assert send is not None
        assert send.kwargs["ephemeral"] is False
        assert send.kwargs["allowed_mentions"].users is False
        assert _texts(send.kwargs["view"])[0] == f"### {mock_member.display_name}'s accounts"
