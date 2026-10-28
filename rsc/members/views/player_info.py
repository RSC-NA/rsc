import logging
import re
from dataclasses import dataclass
from enum import StrEnum
from typing import Any

import discord
from redbot.core.bot import Red

from rsc.abc import RSCMixIn
from rsc.const import RSC_COG_NAME
from rsc.embeds import ApiExceptionErrorEmbed, ErrorEmbed, ExceptionErrorEmbed
from rsc.exceptions import RscException
from rsc.trackers.views import tracker_accounts_card

log = logging.getLogger("red.rsc.members.views.player_info")


class PlayerInfoKind(StrEnum):
    ROSTER = "roster"
    FRANCHISE = "franchise"


PLAYER_INFO_TEMPLATE = r"player_info:(?P<kind>roster|franchise):(?P<name>.+)"
_PLAYER_INFO_PREFIX = "player_info:{kind}:"
# Discord rejects a custom_id longer than this
_CUSTOM_ID_MAX = 100


class PlayerInfoButton(discord.ui.DynamicItem[discord.ui.Button], template=PLAYER_INFO_TEMPLATE):
    """Team Roster or Franchise Info button on a public `/playerinfo` card.

    Registered once globally with `bot.add_dynamic_items()`. The team or
    franchise name rides inside the custom_id, so the buttons keep working
    after the original view would have timed out, and after a restart.
    """

    def __init__(self, kind: PlayerInfoKind, name: str):
        self.kind = kind
        self.name = name
        super().__init__(
            discord.ui.Button(
                # Short, so Team, Franchise and Trackers fit one row on a phone
                label="Team" if kind is PlayerInfoKind.ROSTER else "Franchise",
                style=discord.ButtonStyle.primary,
                custom_id=_PLAYER_INFO_PREFIX.format(kind=kind) + name,
            )
        )

    @staticmethod
    def fits(kind: PlayerInfoKind, name: str) -> bool:
        """Whether `name` fits in a custom_id for this button."""
        return len(_PLAYER_INFO_PREFIX.format(kind=kind) + name) <= _CUSTOM_ID_MAX

    @classmethod
    async def from_custom_id(
        cls,
        interaction: discord.Interaction,
        item: discord.ui.Item[Any],
        match: re.Match[str],
        /,
    ) -> "PlayerInfoButton":
        return cls(kind=PlayerInfoKind(match["kind"]), name=match["name"])

    async def callback(self, interaction: discord.Interaction):
        # Acknowledge first. The API calls below can exceed the 3 second deadline.
        await interaction.response.defer(ephemeral=True)

        guild = interaction.guild
        if not guild:
            return

        cog = await _ready_cog(interaction, guild)
        if not cog:
            return

        if self.kind is PlayerInfoKind.ROSTER:
            await self._team_roster(interaction, guild, cog)
        else:
            await self._franchise_teams(interaction, guild, cog)

    async def _team_roster(self, interaction: discord.Interaction, guild: discord.Guild, cog: RSCMixIn):
        try:
            plist = await cog.players(guild, team_name=self.name, limit=10)
            embed = await cog.build_roster_embed(guild, plist)
        except RscException as exc:
            return await interaction.followup.send(embed=ApiExceptionErrorEmbed(exc), ephemeral=True)
        except (ValueError, AttributeError) as exc:
            return await interaction.followup.send(embed=ExceptionErrorEmbed(exc_message=str(exc)), ephemeral=True)

        await interaction.followup.send(embed=embed, ephemeral=True)

    async def _franchise_teams(self, interaction: discord.Interaction, guild: discord.Guild, cog: RSCMixIn):
        log.debug(f"Fetching teams for {self.name}")
        try:
            teams = await cog.teams(guild, franchise=self.name)
        except RscException as exc:
            return await interaction.followup.send(embed=ApiExceptionErrorEmbed(exc), ephemeral=True)

        if not teams:
            await interaction.followup.send(content="No results found.", ephemeral=True)
            return

        try:
            embed = await cog.build_franchise_teams_embed(guild, teams)
        except (ValueError, AttributeError) as exc:
            return await interaction.followup.send(embed=ExceptionErrorEmbed(exc_message=str(exc)), ephemeral=True)

        await interaction.followup.send(embed=embed, ephemeral=True)


PLAYER_TRACKERS_TEMPLATE = r"player_info:trackers:(?P<discord_id>\d{15,20})"


class PlayerTrackersButton(discord.ui.DynamicItem[discord.ui.Button], template=PLAYER_TRACKERS_TEMPLATE):
    """Trackers button on a `/playerinfo` card: the player's tracker accounts, privately.

    A DynamicItem rather than a link button, because link buttons can only be grey.
    """

    def __init__(self, discord_id: int):
        self.discord_id = discord_id
        super().__init__(
            discord.ui.Button(label="Trackers", style=discord.ButtonStyle.success, custom_id=f"player_info:trackers:{discord_id}")
        )

    @classmethod
    async def from_custom_id(
        cls,
        interaction: discord.Interaction,
        item: discord.ui.Item[Any],
        match: re.Match[str],
        /,
    ) -> "PlayerTrackersButton":
        return cls(discord_id=int(match["discord_id"]))

    async def callback(self, interaction: discord.Interaction):
        await interaction.response.defer(ephemeral=True)

        guild = interaction.guild
        if not guild:
            return
        cog = await _ready_cog(interaction, guild)
        if not cog:
            return

        try:
            trackers = await cog.trackers(guild, player=self.discord_id)
        except RscException as exc:
            return await interaction.followup.send(embed=ApiExceptionErrorEmbed(exc), ephemeral=True)

        member = guild.get_member(self.discord_id)
        view = await tracker_accounts_card(
            mention=f"<@{self.discord_id}>",
            trackers=trackers,
            avatar_url=member.display_avatar.url if member else None,
        )
        await interaction.followup.send(view=view, ephemeral=True, allowed_mentions=discord.AllowedMentions.none())


@dataclass(frozen=True)
class PlayerCard:
    """The `/playerinfo` card. Sent with `AllowedMentions.none()`: the old embed never pinged anyone."""

    name: str
    discord_id: int
    status: str
    colour: discord.Colour
    tier: str | None = None
    team: str | None = None
    franchise: str | None = None
    # Franchise logo, or the player's avatar
    logo_url: str | None = None
    current_mmr: int | None = None
    base_mmr: int | None = None

    def render(self) -> discord.ui.LayoutView:
        esc = discord.utils.escape_markdown
        title = discord.ui.TextDisplay(f"## {esc(self.name)}")
        # The mention leads, so the card doubles as a quick way to grab it
        who = discord.ui.TextDisplay(f"**Player** <@{self.discord_id}>\n**Status** {esc(self.status)}")
        container = discord.ui.Container(accent_colour=self.colour)
        if self.logo_url:
            # Player and status sit beside the logo too: a Section is as tall as its thumbnail, so the
            # name alone would leave a blank band under it
            container.add_item(discord.ui.Section(title, who, accessory=discord.ui.Thumbnail(self.logo_url)))
        else:
            container.add_item(title)
            container.add_item(who)

        placement = (("Tier", self.tier), ("Team", self.team), ("Franchise", self.franchise))
        team = [(label, esc(value)) for label, value in placement if value]
        mmr = (("Current MMR", self.current_mmr), ("Base MMR", self.base_mmr))
        rating = [(label, str(value)) for label, value in mmr if value]
        for heading, rows in (("TEAM", team), ("RATING", rating)):
            if rows:
                container.add_item(discord.ui.Separator())
                container.add_item(discord.ui.TextDisplay("\n".join([f"-# {heading}", *(f"**{label}** {value}" for label, value in rows)])))

        buttons = discord.ui.ActionRow()
        targets = ((PlayerInfoKind.ROSTER, self.team), (PlayerInfoKind.FRANCHISE, self.franchise))
        for kind, name in targets:
            if name and PlayerInfoButton.fits(kind, name):
                buttons.add_item(PlayerInfoButton(kind, name))
        buttons.add_item(PlayerTrackersButton(self.discord_id))
        container.add_item(buttons)
        # The plain Discord ID is there to copy
        container.add_item(discord.ui.TextDisplay(f"-# Discord ID {self.discord_id}"))

        view = discord.ui.LayoutView(timeout=None)
        view.add_item(container)
        return view


async def _ready_cog(interaction: discord.Interaction, guild: discord.Guild) -> RSCMixIn | None:
    """The RSC cog, or None after telling the clicker the bot is still starting.

    The API wrappers index `_api_conf`/`_league` directly, so a click before
    setup() finishes after a restart would raise KeyError, not RscException.
    """
    bot = interaction.client
    cog = bot.get_cog(RSC_COG_NAME) if isinstance(bot, Red) else None
    if isinstance(cog, RSCMixIn) and cog._api_conf.get(guild.id) and cog._league.get(guild.id):
        return cog
    log.warning(f"[{guild.name}] Player info button clicked before {RSC_COG_NAME} was ready")
    await interaction.followup.send(
        embed=ErrorEmbed(description="The bot is still starting up. Please try again in a minute."),
        ephemeral=True,
    )
    return None
