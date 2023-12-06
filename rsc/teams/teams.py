import discord
import logging

from redbot.core import app_commands, checks

from rscapi import ApiClient, TeamsApi
from rscapi.models.team import Team
from rscapi.models.team_list import TeamList
from rscapi.models.league_player import LeaguePlayer
from rscapi.models.player import Player
from rscapi.models.match import Match

from rsc.abc import RSCMixIn
from rsc.enums import Status
from rsc.embeds import ErrorEmbed, BlueEmbed
from rsc.franchises import FranchiseMixIn
from rsc.tiers import TierMixIn
from rsc.utils.utils import (
    franchise_role_from_name,
    get_gm_by_role,
    has_gm_role,
    tier_color_by_name,
)

from typing import Optional, List, Dict, Tuple

log = logging.getLogger("red.rsc.teams")


class TeamMixIn(RSCMixIn):
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
            if len(choices) == 25:
                return choices
        return choices

    # Commands

    @app_commands.command(
        name="teams", description="Get a list of teams for a franchise"
    )
    @app_commands.autocomplete(
        franchise=FranchiseMixIn.franchise_autocomplete,
        tier=TierMixIn.tier_autocomplete,
    )
    @app_commands.describe(
        franchise="Teams in a franchise", tier="Teams in a league tier"
    )
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
                content="Please specify only one search option.", ephemeral=True
            )
            return

        log.debug(f"Fetching teams for {franchise}")
        teams = await self.teams(interaction.guild, tier=tier, franchise=franchise)

        if not teams:
            await interaction.response.send_message(
                content="No results found.", ephemeral=True
            )
            return

        embed = BlueEmbed()
        if interaction.guild.icon:
            embed.set_thumbnail(url=interaction.guild.icon.url)

        if franchise:
            # Include tier data when API is fixed
            embed.title = f"{franchise} Teams"
            embed.add_field(
                name="Team", value="\n".join([t.name for t in teams]), inline=True
            )
            embed.add_field(
                name="Tier", value="\n".join([t.tier.name for t in teams]), inline=True
            )
            await interaction.response.send_message(embed=embed)
        elif tier:
            # Sort by Team Name
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
        teams: List[TeamList] = await self.teams(interaction.guild, name=team)
        if not teams:
            await interaction.response.send_message(
                content=f"No results found for **{team}**.", ephemeral=True
            )
            return
        elif len(teams) > 1:
            names = ", ".join([t.name for t in teams])
            await interaction.response.send_message(
                content=f"Found multiple results for team name: **{names}**",
                ephemeral=True,
            )
            return

        # Fetch roster information
        roster = await self.team_by_id(interaction.guild, teams[0].id)

        tier_color = await tier_color_by_name(interaction.guild, roster.tier)

        # Fetch franchise info
        franchise_info = await self.franchises(interaction.guild, name=roster.franchise)

        # API has some malformed data
        if not franchise_info:
            log.error(f"Unable to fetch franchise info for **{roster.franchise}**")
            await interaction.response.send_message(
                embed=ErrorEmbed(
                    description="Unable to fetch franchise info for **{roster.franchise}**"
                ),
                ephemeral=True,
            )
            return

        # Get GM discord id
        gm_id = None
        if franchise_info[0].gm:
            gm_id = franchise_info[0].gm.discord_id

        players = []
        for p in roster.players:
            m = interaction.guild.get_member(p.discord_id)
            name = m.display_name if m else p.name
            if p.captain and p.discord_id == gm_id:
                players.append(f"{name} (GM|C)")
            elif p.captain:
                players.append(f"{name} (C)")
            elif p.discord_id == gm_id:
                players.append(f"{name} (GM)")
            else:
                players.append(name)

        player_str = "\n".join(players)

        # Team API endpoint is currently missing IR status. Need to add eventually.

        embed = discord.Embed(
            title=f"{team} ({roster.franchise} - {roster.tier})",
            description=f"```\n{player_str}\n```",
            color=tier_color,
        )
        await interaction.response.send_message(embed=embed)

    # Captains Group

    _captains = app_commands.Group(
        name="captains", description="Get information on team captains", guild_only=True
    )

    @_captains.command(name="team", description="Display captain of a specific team")
    @app_commands.autocomplete(team=teams_autocomplete)
    async def _captains_team(
        self,
        interaction: discord.Interaction,
        team: str,
    ):
        """Get a list of captains by search criteria"""
        captain = await self.team_captain(interaction.guild, team)
        if not captain:
            await interaction.response.send_message(
                embed=ErrorEmbed(
                    description=f"**{team}** does not exist or a captain has not been elected."
                ),
                ephemeral=True,
            )
            return

        tier_color = await tier_color_by_name(interaction.guild, captain.tier.name)

        # fetch discord.Member from id
        m = interaction.guild.get_member(captain.player.discord_id)
        cpt_fmt = m.mention if m else captain.player.name

        # fetch franchise role
        frole = await franchise_role_from_name(
            interaction.guild, captain.team.franchise.name
        )
        franchise_fmt = frole.mention if frole else captain.team.franchise.name

        desc = f"**Captain:** {cpt_fmt}\n" f"**Franchise:** {franchise_fmt}"

        embed = discord.Embed(title=f"{team}", description=desc, color=tier_color)
        await interaction.response.send_message(embed=embed)

    @_captains.command(
        name="tier", description="Display captains of all teams in a tier"
    )
    @app_commands.autocomplete(tier=TierMixIn.tier_autocomplete)
    async def _captains_tier(self, interaction: discord.Interaction, tier: str):
        """Get a list of captains by search criteria"""
        captains = await self.tier_captains(interaction.guild, tier)
        if not captains:
            await interaction.response.send_message(
                embed=ErrorEmbed(
                    description=f"**{tier}** is not a valid tier or no captains have been elected."
                ),
                ephemeral=True,
            )
            return

        tier_color = await tier_color_by_name(interaction.guild, tier)

        embed = discord.Embed(title=f"{tier} Captains", color=tier_color)

        # Convert Discord IDs to `discord.Member`
        cpt_fmt = []
        for c in captains:
            m = interaction.guild.get_member(c.player.discord_id)
            cpt_fmt.append(m.mention if m else c.player.name)

        embed.add_field(name="Captain", value="\n".join(cpt_fmt), inline=True)
        embed.add_field(
            name="Team", value="\n".join([c.team.name for c in captains]), inline=True
        )
        embed.add_field(name="Franchise", value="\n".join([c.team.franchise.name for c in captains]), inline=True)
        await interaction.response.send_message(embed=embed)

    @_captains.command(
        name="franchise", description="Display captains of all teams in a franchise"
    )
    @app_commands.autocomplete(franchise=FranchiseMixIn.franchise_autocomplete)
    async def _captains_franchise(
        self,
        interaction: discord.Interaction,
        franchise: str,
    ):
        """Get a list of captains by search criteria"""
        captains = await self.franchise_captains(interaction.guild, franchise)
        if not captains:
            await interaction.response.send_message(
                embed=ErrorEmbed(
                    description=f"**{franchise}** is not a valid franchise or no captains have been elected."
                ),
                ephemeral=True,
            )
            return

        # Convert Discord IDs to `discord.Member`
        cpt_fmt = []
        for c in captains:
            m = interaction.guild.get_member(c.player.discord_id)
            cpt_fmt.append(m.mention if m else c.player.name)

        frole = await franchise_role_from_name(
            interaction.guild, captains[0].team.franchise.name
        )

        gm = interaction.guild.get_member(captains[0].team.franchise.gm.discord_id)

        embed = BlueEmbed(title=f"{franchise} Captains")

        if gm and frole:
            embed.description = (
                f"General Manager: {gm.mention}\nFranchise: {frole.mention}"
            )

        embed.add_field(name="Captain", value="\n".join(cpt_fmt), inline=True)
        embed.add_field(
            name="Team", value="\n".join([x.team.name for x in captains]), inline=True
        )
        embed.add_field(
            name="Tier", value="\n".join([x.tier.name for x in captains]), inline=True
        )
        await interaction.response.send_message(embed=embed)

    # Functions

    async def team_id_by_name(self, guild: discord.Guild, name: str) -> int:
        """Return a teams ID in the API by name. (Zero indicates not found)"""
        teams = await self.teams(guild, name=name)
        if not teams:
            return 0
        if len(teams) > 1:
            raise ValueError(f"More than one result for team: {name}")
        if not teams[0].id:
            return 0
        return teams[0].id

    async def team_captain(
        self, guild: discord.Guild, team_name: str
    ) -> Optional[LeaguePlayer]:
        """Return captain of a team by name"""
        players = await self.players(guild, status=Status.ROSTERED, team_name=team_name)
        if not players:
            return None
        return next((x for x in players if x.captain), None)

    async def tier_captains(
        self, guild: discord.Guild, tier_name: str
    ) -> List[LeaguePlayer]:
        """Return all captains in a tier"""
        players = await self.players(
            guild, status=Status.ROSTERED, tier_name=tier_name, limit=1000
        )
        if not players:
            return []

        captains = [x for x in players if x.captain]
        log.debug(captains)
        captains.sort(key=lambda x: x.team.name)
        return captains

    async def franchise_captains(
        self, guild: discord.Guild, franchise_name: str
    ) -> List[LeaguePlayer]:
        """Return all captains in a franchise"""
        players = await self.players(
            guild, status=Status.ROSTERED, franchise=franchise_name
        )
        if not players:
            return []

        captains = [x for x in players if x.captain]
        captains.sort(key=lambda x: x.tier.position, reverse=True)
        return captains

    # API

    async def teams(
        self,
        guild: discord.Guild,
        seasons: Optional[str] = None,
        franchise: Optional[str] = None,
        name: Optional[str] = None,
        tier: Optional[str] = None,
    ) -> List[TeamList]:
        """Fetch teams from API"""
        async with ApiClient(self._api_conf[guild.id]) as client:
            api = TeamsApi(client)
            teams = await api.teams_list(
                seasons=seasons,
                franchise=franchise,
                name=name,
                tier=tier,
                league=self._league[guild.id],
            )

            # Populate cache
            if teams:
                if self._team_cache.get(guild.id):
                    log.debug(f"[{guild.name}] Adding new teams to cache")
                    cached = set(self._team_cache[guild.id])
                    different = set([t.name for t in teams]) - cached
                    log.debug(f"[{guild.name}] Teams being added to cache: {different}")
                    self._team_cache[guild.id] += list(different)
                else:
                    log.debug(f"[{guild.name}] Starting fresh teams cache")
                    self._team_cache[guild.id] = [t.name for t in teams]
                self._team_cache[guild.id].sort()
            return teams

    async def team_by_id(
        self,
        guild: discord.Guild,
        id: int,
    ) -> Team:
        """Fetch team data by id"""
        async with ApiClient(self._api_conf[guild.id]) as client:
            api = TeamsApi(client)
            return await api.teams_read(id)

    async def team_players(
        self,
        guild: discord.Guild,
        id: int,
    ) -> List[Player]:
        """Fetch team data by id"""
        async with ApiClient(self._api_conf[guild.id]) as client:
            api = TeamsApi(client)
            return await api.teams_players(id)

    async def next_match(
        self,
        guild: discord.Guild,
        id: int,
    ) -> Optional[Match]:
        async with ApiClient(self._api_conf[guild.id]) as client:
            api = TeamsApi(client)
            return await api.teams_next_match(id)

    async def season_matches(
        self,
        guild: discord.Guild,
        id: int,
        season: Optional[int] = None,
        preseason: bool = False,
    ) -> List[Match]:
        async with ApiClient(self._api_conf[guild.id]) as client:
            api = TeamsApi(client)
            return await api.teams_season_matches(
                id, preseason=preseason, season=season
            )
