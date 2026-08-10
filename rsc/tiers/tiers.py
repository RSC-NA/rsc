import logging
from typing import cast

import discord
from redbot.core import app_commands
from rscapi import TiersApi
from rscapi.exceptions import ApiException
from rscapi.models.player_season_stats_in_depth import PlayerSeasonStatsInDepth
from rscapi.models.tier import Tier
from rscapi.models.team_season_stats import TeamSeasonStats
from rscapi.models.team_standings import TeamStandings

from rsc.abc import RSCMixIn
from rsc.const import API_TIMEOUT
from rsc.embeds import BlueEmbed, ErrorEmbed
from rsc.exceptions import RscException

log = logging.getLogger("red.rsc.tiers")


class TierMixIn(RSCMixIn):
    def __init__(self):
        log.debug("Initializing TierMixIn")
        self._tier_cache: dict[int, list[str]] = {}
        super().__init__()

    # Autocomplete

    async def tier_autocomplete(self, interaction: discord.Interaction, current: str) -> list[app_commands.Choice[str]]:
        if not interaction.guild_id:
            return []

        # Return nothing if cache does not exist.
        if not self._tier_cache.get(interaction.guild_id):
            return []

        choices = []
        for t in self._tier_cache[interaction.guild_id]:
            if current.lower() in t.lower():
                choices.append(app_commands.Choice(name=t, value=t))
            if len(choices) == 25:
                return choices
        return choices

    # Commands

    @app_commands.command(name="tiers", description="Get a list of all league tiers")
    @app_commands.guild_only
    async def _tiers(self, interaction: discord.Interaction):
        """Get a list of all league tiers"""
        guild = interaction.guild
        if not guild:
            return

        tiers = await self.tiers(guild)

        # Get roles from guild and additional data
        tier_roles = []
        for t in tiers:
            role = discord.utils.get(guild.roles, name=t.name)
            if not role:
                return await interaction.response.send_message(
                    embed=ErrorEmbed(description=f"{t.name} does not have a role in the guild. Please open a modmail ticket.")
                )
            tier_roles.append(role)
            # Fetch teams from each tier

        embed = BlueEmbed(
            title=f"{interaction.guild} Tiers",
            description="\n".join([r.mention for r in tier_roles]),
        )
        if guild.icon:
            embed.set_thumbnail(url=guild.icon.url)
        await interaction.response.send_message(embed=embed)

    # Functions

    async def is_valid_tier(self, guild: discord.Guild, name: str) -> bool:
        """Check if name is in the tier cache"""
        if not self._tier_cache.get(guild.id):
            return False

        return name in self._tier_cache[guild.id]

    async def tier_fa_roles(self, guild: discord.Guild) -> list[discord.Role]:
        """Return a list of tier free agent roles (Ex: ProspectFA)"""
        tiers = await self.tiers(guild)
        roles = []
        for t in tiers:
            r = discord.utils.get(guild.roles, name=f"{t.name}FA")
            if r:
                roles.append(r)
        return roles

    async def tier_id_by_name(self, guild: discord.Guild, tier: str) -> int:
        """Return a tier ID by its name"""
        tiers = await self.tiers(guild, name=tier)
        if not tiers:
            raise ValueError(f"Tier does not exist: **{tier}**")
        if len(tiers) > 1:
            raise ValueError(f"Found more than one tier matching: **{tier}**")

        t = tiers.pop(0)
        if t.id is None:
            raise ValueError("Found tier in API but it does not have an ID")

        return t.id

    # API

    async def tier_by_id(self, guild: discord.Guild, id: int) -> Tier:
        async with self.api_client(guild) as client:
            api = TiersApi(client)
            tier = await api.tiers_retrieve(id)
            return tier

    async def tiers(self, guild: discord.Guild, name: str | None = None) -> list[Tier]:
        """Fetch a list of tiers"""
        # An unfiltered query returns the authoritative full list, so the cache
        # is rebuilt from it. A filtered one can only add. Merging in both cases
        # meant a renamed or deleted tier lingered in autocomplete until restart.
        full_refresh = name is None

        async with self.api_client(guild) as client:
            api = TiersApi(client)
            tiers = await api.tiers_list(name=name, league=self._league[guild.id], _request_timeout=API_TIMEOUT)
            tiers.sort(key=lambda t: cast("int", t.position), reverse=True)

            # Populate cache
            if tiers:
                if not all(t.name for t in tiers):
                    raise AttributeError("API returned a tier with no name.")

                if full_refresh or not self._tier_cache.get(guild.id):
                    self._tier_cache[guild.id] = [t.name for t in tiers if t.name]
                else:
                    cached = set(self._tier_cache[guild.id])
                    different = {t.name for t in tiers if t.name} - cached
                    if different:
                        self._tier_cache[guild.id] += list(different)
            return tiers

    async def tier_standings(self, guild: discord.Guild, tier_id: int, season: int) -> list[TeamStandings]:
        """Fetch a list of tiers"""
        async with self.api_client(guild) as client:
            api = TiersApi(client)
            try:
                standings: list[TeamStandings] = await api.tiers_standings_list(id=tier_id, season=season)
                standings.sort(key=lambda t: (t.rank, t.team))
                return standings
            except ApiException as exc:
                raise RscException(response=exc)

    async def tier_player_stats(
        self,
        guild: discord.Guild,
        tier_id: int,
        season: int | None = None,
        name: str | None = None,
    ) -> list[PlayerSeasonStatsInDepth]:
        """Season stats for every player in a tier, in a single request.

        Each record carries server-computed ranks (`goals_rank`, `points_rank`,
        ...), so leaderboards need no client side sorting pass over the league.
        """
        async with self.api_client(guild) as client:
            api = TiersApi(client)
            try:
                return await api.tiers_player_stats_list(
                    id=tier_id,
                    league=self._league[guild.id],
                    name=name,
                    season=season,
                    _request_timeout=API_TIMEOUT,
                )
            except ApiException as exc:
                raise RscException(response=exc)

    async def tier_team_stats(
        self,
        guild: discord.Guild,
        tier_id: int,
        season: int | None = None,
        name: str | None = None,
    ) -> list[TeamSeasonStats]:
        """Season stats for every team in a tier, in a single request."""
        async with self.api_client(guild) as client:
            api = TiersApi(client)
            try:
                return await api.tiers_team_stats_list(
                    id=tier_id,
                    league=self._league[guild.id],
                    name=name,
                    season=season,
                    _request_timeout=API_TIMEOUT,
                )
            except ApiException as exc:
                raise RscException(response=exc)

    async def create_tier(self, guild: discord.Guild, name: str, color: int, position: int) -> Tier:
        async with self.api_client(guild) as client:
            api = TiersApi(client)
            data = cast("Tier", {"name": name, "color": color, "position": position})
            log.debug(f"Create Tier Data: {data}")
            try:
                return await api.tiers_create(data)
            except ApiException as exc:
                raise RscException(response=exc)

    async def delete_tier(self, guild: discord.Guild, id: int) -> None:
        async with self.api_client(guild) as client:
            api = TiersApi(client)
            try:
                return await api.tiers_destroy(id)
            except ApiException as exc:
                raise RscException(response=exc)
