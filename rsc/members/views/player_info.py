import logging
import re
from enum import StrEnum
from typing import Any

import discord
from redbot.core.bot import Red

from rsc.abc import RSCMixIn
from rsc.const import RSC_COG_NAME
from rsc.embeds import ApiExceptionErrorEmbed, ErrorEmbed, ExceptionErrorEmbed
from rsc.exceptions import RscException

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
                label="Team Roster" if kind is PlayerInfoKind.ROSTER else "Franchise Info",
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

        bot = interaction.client
        cog = bot.get_cog(RSC_COG_NAME) if isinstance(bot, Red) else None
        # The API wrappers index `_api_conf`/`_league` directly, so a click before
        # setup() finishes after a restart would raise KeyError, not RscException.
        if not isinstance(cog, RSCMixIn) or not (cog._api_conf.get(guild.id) and cog._league.get(guild.id)):
            log.warning(f"[{guild.name}] Player info button clicked before {RSC_COG_NAME} was ready")
            await interaction.followup.send(
                embed=ErrorEmbed(description="The bot is still starting up. Please try again in a minute."),
                ephemeral=True,
            )
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


def player_info_view(team: str, franchise: str) -> discord.ui.View | None:
    """Buttons for a `/playerinfo` card, or None if neither name fits a custom_id.

    Deliberately not registered with `add_view()`. Dispatch happens through the
    `PlayerInfoButton` template registered once via `add_dynamic_items()`.
    """
    targets = ((PlayerInfoKind.ROSTER, team), (PlayerInfoKind.FRANCHISE, franchise))
    buttons = [PlayerInfoButton(kind, name) for kind, name in targets if PlayerInfoButton.fits(kind, name)]
    if not buttons:
        return None

    view = discord.ui.View(timeout=None)
    for button in buttons:
        view.add_item(button)
    return view
