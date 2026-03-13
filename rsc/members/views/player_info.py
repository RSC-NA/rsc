import logging
import discord

from rsc.abc import RSCMixIn
from rsc.embeds import ApiExceptionErrorEmbed, ExceptionErrorEmbed
from rsc.exceptions import RscException

log = logging.getLogger("red.rsc.members.views.player_info")


class PlayerInfoView(discord.ui.View):
    def __init__(
        self,
        mixin: RSCMixIn,
        player: discord.Member,
        team: str,
        franchise: str,
    ):
        super().__init__()
        self.mixin = mixin
        self.player = player
        self.team = team
        self.franchise = franchise

    @discord.ui.button(label="Team Roster", style=discord.ButtonStyle.primary)
    async def display_team_roster(self, interaction: discord.Interaction, button: discord.ui.Button):
        await interaction.response.defer(ephemeral=True)

        guild = interaction.guild
        if not guild:
            return

        try:
            plist = await self.mixin.players(guild, team_name=self.team, limit=10)
            embed = await self.mixin.build_roster_embed(guild, plist)
        except RscException as exc:
            return await interaction.followup.send(embed=ApiExceptionErrorEmbed(exc), ephemeral=True)
        except (ValueError, AttributeError) as exc:
            return await interaction.followup.send(embed=ExceptionErrorEmbed(exc_message=str(exc)))

        await interaction.followup.send(embed=embed, ephemeral=True)

    @discord.ui.button(label="Franchise Info", style=discord.ButtonStyle.primary)
    async def display_franchise_teams(self, interaction: discord.Interaction, button: discord.ui.Button):
        await interaction.response.defer(ephemeral=True)
        guild = interaction.guild
        if not guild:
            return

        log.debug(f"Fetching teams for {self.franchise}")
        try:
            teams = await self.mixin.teams(guild, franchise=self.franchise)
        except RscException as exc:
            return await interaction.followup.send(embed=ApiExceptionErrorEmbed(exc), ephemeral=True)

        if not teams:
            await interaction.followup.send(content="No results found.", ephemeral=True)
            return

        # Build Embed
        try:
            embed = await self.mixin.build_franchise_teams_embed(guild, teams)
        except (ValueError, AttributeError) as exc:
            return await interaction.followup.send(embed=ExceptionErrorEmbed(exc_message=str(exc)))

        await interaction.followup.send(embed=embed, ephemeral=True)
