import discord
import logging

from redbot.core import app_commands, checks

from rscapi import ApiClient, TeamsApi
from rscapi.models.team import Team
from rscapi.models.team_list import TeamList

from rsc.abc import RSCMeta
from rsc.embeds import ErrorEmbed
from rsc.franchises import FranchiseMixIn
from rsc.tiers import TierMixIn
from rsc.utils import get_franchise_role_from_name, get_gm, is_gm

from typing import Optional, List, Dict, Tuple

log = logging.getLogger("red.rsc.teams")


class TeamMixIn(metaclass=RSCMeta):
    def __init__(self):
        log.debug("Initializing TeamMixIn")
        self._team_cache: Dict[int, List[str]] = {}
        super().__init__()

    # Autocomplete

    async def teams_autocomplete(
        self, interaction: discord.Interaction, current: str
    ) -> List[app_commands.Choice[str]]:
        if not interaction.guild_id:
            return []

        # Return nothing if cache does not exist.
        if not self._team_cache.get(interaction.guild_id):
            return []

        choices = []
        for t in self._team_cache[interaction.guild_id]:
            if current.lower() in t.lower():
                choices.append(app_commands.Choice(name=t, value=t))
        return choices

    # Commands

    @app_commands.command(
        name="teams", description="Get a list of teams for a franchise"
    )
    @app_commands.autocomplete(franchise=FranchiseMixIn.franchise_autocomplete)
    @app_commands.autocomplete(tier=TierMixIn.tiers_autocomplete)
    @app_commands.describe(franchise="Teams in a franchise")
    @app_commands.describe(tier="Teams in a league tier")
    @app_commands.guild_only()
    async def _teams(
        self,
        interaction: discord.Interaction,
        franchise: Optional[str] = None,
        tier: Optional[str] = None,
    ):
        """Get a list of teams for a franchise"""
        if not (franchise or tier):
            await interaction.response.send_message(
                content="You must specify one of the search options.", ephemeral=True
            )
            return

        if franchise and tier:
            await interaction.response.send_message(
                content="Please specify only one option for search.", ephemeral=True
            )
            return

        log.debug(f"Fetching teams for {franchise}")
        teams = await self.teams(interaction.guild, tier=tier, franchise=franchise)

        if not teams:
            await interaction.response.send_message(
                content="No results found.", ephemeral=True
            )
            return

        embed = discord.Embed(color=discord.Color.blue())
        if interaction.guild.icon:
            embed.set_thumbnail(url=interaction.guild.icon.url)

        if franchise:
            # Include tier data when API is fixed
            embed.title = f"{franchise} Teams"
            embed.add_field(
                name="Team", value="\n".join([t.name for t in teams]), inline=True
            )
            embed.add_field(
                name="Tier", value="\n".join(["Fix Me" for t in teams]), inline=True
            )
            await interaction.response.send_message(embed=embed)
        elif tier:
            # Sort by Team Name
            teams.sort(key=lambda x: x.name)
            embed.title = f"{tier} Teams"
            embed.add_field(
                name="Team", value="\n".join([t.name for t in teams]), inline=True
            )
            embed.add_field(
                name="Franchise",
                value="\n".join([t.franchise for t in teams]),
                inline=True,
            )
            await interaction.response.send_message(embed=embed)

    @app_commands.command(name="roster", description="Get roster for a team")
    @app_commands.autocomplete(team=teams_autocomplete)
    @app_commands.describe(team="Team name to search")
    @app_commands.guild_only()
    async def _roster(
        self,
        interaction: discord.Interaction,
        team: str,
    ):
        """Get a roster for a team"""
        # Verify team exists and get data
        teams = await self.teams(interaction.guild, name=team)
        if not teams:
            await interaction.response.send_message(
                content=f"No results found for **{team}**.", ephemeral=True
            )
            return
        elif len(teams) > 1:
            names = ", ".join(t.name for t in teams)
            await interaction.response.send_message(
                content=f"Found multiple results for team name: **{names}**",
                ephemeral=True,
            )
            return

        # Fetch roster information
        roster = await self.team_by_id(interaction.guild, str(teams[0].id))
        log.debug(roster)

        tier_role = discord.utils.get(interaction.guild.roles, name=roster.tier)
        # franchise_role = await get_franchise_role_from_name(interaction.guild, roster.franchise)
        log.debug(f"Tier Role: {tier_role}")
        # log.debug(f"Franchise Role: {franchise_role}")

        if tier_role:
            tier_color = tier_role.color
        else:
            tier_color = discord.Color.blue()

        # Get GM
        franchise_info = await self.franchises(interaction.guild, name=roster.franchise)
        gm_id = franchise_info[0].gm.discord_id
        gm = interaction.guild.get_member(gm_id)
        log.debug(f"GM: {gm}")

        player_str = ""
        for p in roster.players:
            player_str += f"{p.name}"
            if p.captain:
                player_str += " (C)"
            # Add GM in here. Waiting on discord IDs to be returned
            player_str += "\n"

        # Team API endpoint is currently missing IR status. Need to add eventually.

        embed = discord.Embed(
            title=f"{team} - {roster.franchise} - {roster.tier}",
            description=player_str,
            color=tier_color,
        )
        await interaction.response.send_message(embed=embed)

    # Functions

    async def teams(
        self,
        guild: discord.Guild,
        seasons: Optional[str] = None,
        franchise: Optional[str] = None,
        name: Optional[str] = None,
        tier: Optional[str] = None,
    ) -> List[TeamList]:
        """Fetch teams from API"""
        async with ApiClient(self._api_conf[guild]) as client:
            api = TeamsApi(client)
            teams = await api.teams_list(
                seasons=seasons, franchise=franchise, name=name, tier=tier, league="1"
            )

            # Populate cache
            if teams:
                if self._team_cache.get(guild.id):
                    cached = set(self._team_cache[guild.id])
                    different = set([t.name for t in teams]) - cached
                    self._team_cache[guild.id] += list(different)
                else:
                    self._team_cache[guild.id] = [t.name for t in teams]
            return teams

    async def team_by_id(
        self,
        guild: discord.Guild,
        id: str,
    ) -> Team:
        """Fetch team data by id"""
        async with ApiClient(self._api_conf[guild]) as client:
            api = TeamsApi(client)
            return await api.teams_read(id)
