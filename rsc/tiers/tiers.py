import logging
from typing import cast

import discord
from redbot.core import app_commands
from rscapi import ApiClient, TiersApi
from rscapi.exceptions import ApiException
from rscapi.models.tier import Tier
from rscapi.models.team_standings import TeamStandings

from rsc.abc import RSCMixIn
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

    @app_commands.command(name="tiers", description="Get a list of all league tiers")  # type: ignore[type-var]
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
        async with ApiClient(self._api_conf[guild.id]) as client:
            api = TiersApi(client)
            tier = await api.tiers_read(id)
            return tier

    async def tiers(self, guild: discord.Guild, name: str | None = None) -> list[Tier]:
        """Fetch a list of tiers"""
        async with ApiClient(self._api_conf[guild.id]) as client:
            api = TiersApi(client)
            tiers = await api.tiers_list(name=name, league=self._league[guild.id])
            tiers.sort(key=lambda t: cast(int, t.position), reverse=True)

            # Populate cache
            if tiers:
                if not all(t.name for t in tiers):
                    raise AttributeError("API returned a tier with no name.")

                if self._tier_cache.get(guild.id):
                    cached = set(self._tier_cache[guild.id])
                    different = {t.name for t in tiers if t.name} - cached
                    if different:
                        self._tier_cache[guild.id] += list(different)
                else:
                    self._tier_cache[guild.id] = [t.name for t in tiers if t.name]
            return tiers

    async def tier_standings(self, guild: discord.Guild, tier_id: int, season: int) -> list[TeamStandings]:
        """Fetch a list of tiers"""
        async with ApiClient(self._api_conf[guild.id]) as client:
            api = TiersApi(client)
            try:
                standings: list[TeamStandings] = await api.tiers_standings(id=tier_id, season=season)
                standings.sort(key=lambda t: (t.rank, t.team))
                return standings
            except ApiException as exc:
                raise RscException(response=exc)

    async def create_tier(self, guild: discord.Guild, name: str, color: int, position: int) -> Tier:
        async with ApiClient(self._api_conf[guild.id]) as client:
            api = TiersApi(client)
            data = Tier(name=name, color=color, position=position)
            log.debug(f"Create Tier Data: {data}")
            try:
                return await api.tiers_create(data)
            except ApiException as exc:
                raise RscException(response=exc)

    async def delete_tier(self, guild: discord.Guild, id: int) -> None:
        async with ApiClient(self._api_conf[guild.id]) as client:
            api = TiersApi(client)
            try:
                return await api.tiers_delete(id)
            except ApiException as exc:
                raise RscException(response=exc)
