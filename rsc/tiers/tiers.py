import discord
import logging

from pydantic import parse_obj_as
from redbot.core import app_commands, checks

from rscapi import ApiClient, FranchisesApi, TiersApi
from rscapi.exceptions import ApiException
from rscapi.models.tier import Tier

from rsc.abc import RSCMixIn
from rsc.exceptions import RscException
from rsc.embeds import ErrorEmbed
from rsc.utils.utils import role_by_name

from typing import List, Dict, Optional

log = logging.getLogger("red.rsc.tiers")


class TierMixIn(RSCMixIn):
    def __init__(self):
        log.debug("Initializing TierMixIn")
        self._tier_cache: Dict[int, List[str]] = {}
        super().__init__()

    # Autocomplete

    async def tier_autocomplete(
        self, interaction: discord.Interaction, current: str
    ) -> List[app_commands.Choice[str]]:
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
    @app_commands.guild_only()
    async def _tiers(self, interaction: discord.Interaction):
        """Get a list of all league tiers"""
        tiers = await self.tiers(interaction.guild)

        # Get roles from guild and additional data
        tier_roles = []
        for t in tiers:
            tier_roles.append(discord.utils.get(interaction.guild.roles, name=t.name))
            # Fetch teams from each tier

        embed = discord.Embed(
            title=f"{interaction.guild} Tiers",
            description="\n".join([r.mention for r in tier_roles]),
            color=discord.Color.blue(),
        )
        if interaction.guild.icon:
            embed.set_thumbnail(url=interaction.guild.icon.url)
        await interaction.response.send_message(embed=embed)

    # Functions

    async def is_valid_tier(self, guild: discord.Guild, name: str) -> bool:
        """Check if name is in the tier cache"""
        if not self._tier_cache.get(guild.id):
            return False

        if name in self._tier_cache[guild.id]:
            return True
        return False

    async def tier_fa_roles(self, guild: discord.Guild) -> List[discord.Role]:
        """Return a list of tier free agent roles (Ex: ProspectFA)"""
        tiers = await self.tiers(guild)
        roles = []
        for t in tiers:
            r = discord.utils.get(guild.roles, name=f"{t.name}FA")
            if r:
                roles.append(r)
        return r
        

    # API

    async def tiers(
        self, guild: discord.Guild, name: Optional[str] = None
    ) -> List[Tier]:
        """Fetch a list of tiers"""
        async with ApiClient(self._api_conf[guild.id]) as client:
            api = TiersApi(client)
            tiers = await api.tiers_list(name=name, league=self._league[guild.id])
            tiers.sort(key=lambda t: t.position, reverse=True)

            # Populate cache
            if tiers:
                if self._tier_cache.get(guild.id):
                    cached = set(self._tier_cache[guild.id])
                    different = set([t.name for t in tiers]) - cached
                    self._tier_cache[guild.id] += list(different)
                else:
                    self._tier_cache[guild.id] = [t.name for t in tiers]
            return tiers

    async def tier_by_id(self, guild: discord.Guild, id: int) -> Tier:
        async with ApiClient(self._api_conf[guild.id]) as client:
            api = TiersApi(client)
            tier = await api.tiers_read(id)
            return tier

    async def tiers(
        self, guild: discord.Guild, name: Optional[str] = None
    ) -> List[Tier]:
        """Fetch a list of tiers"""
        async with ApiClient(self._api_conf[guild.id]) as client:
            api = TiersApi(client)
            tiers = await api.tiers_list(name=name, league=self._league[guild.id])
            tiers.sort(key=lambda t: t.position, reverse=True)

            # Populate cache
            if tiers:
                if self._tier_cache.get(guild.id):
                    cached = set(self._tier_cache[guild.id])
                    different = set([t.name for t in tiers]) - cached
                    self._tier_cache[guild.id] += list(different)
                else:
                    self._tier_cache[guild.id] = [t.name for t in tiers]
            return tiers

    async def create_tier(self, guild: discord.Guild, name: str, color: int, position: int) -> Tier:
        async with ApiClient(self._api_conf[guild.id]) as client:
            api = TiersApi(client)
            data = Tier(
                name=name,
                color=color,
                position=position
            )
            log.debug(f"Create Tier Data: {data}")
            try:
                return await api.tiers_create()
            except ApiException as exc:
                raise RscException(response=exc)

    async def delete_tier(self, guild: discord.Guild, id: int) -> None:
        async with ApiClient(self._api_conf[guild.id]) as client:
            api = TiersApi(client)
            try:
                return await api.tiers_create(id)
            except ApiException as exc:
                raise RscException(response=exc)
