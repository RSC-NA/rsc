import discord
import logging

from pydantic import parse_obj_as
from redbot.core import app_commands, checks

from rscapi import ApiClient, FranchisesApi, TiersApi
from rscapi.models.tier import Tier

from rsc.abc import RSCMeta
from rsc.embeds import ErrorEmbed

from typing import List, Dict, Optional

log = logging.getLogger("red.rsc.tiers")


class TierMixIn(metaclass=RSCMeta):
    def __init__(self):
        log.debug("Initializing TierMixIn")
        self._tier_cache: Dict[int, List[str]] = {}
        super().__init__()

    # Autocomplete

    async def tiers_autocomplete(
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

    @app_commands.command(name="tier", description="Get a list of teams in a tier")
    @app_commands.autocomplete(tier=tiers_autocomplete)
    @app_commands.guild_only()
    async def _tier(self, interaction: discord.Interaction, tier: str):
        """Get a list of teams in a tier"""
        teams = await self.teams(interaction.guild, tier=tier)
        teams.sort(key=lambda t: t.name)

        embed = discord.Embed(
            title=f"{tier} Teams",
            color=discord.Color.blue(),
        )
        embed.add_field(
            name="Team", value="\n".join([t.name for t in teams]), inline=True
        )
        embed.add_field(
            name="Franchise", value="\n".join(t.franchise for t in teams), inline=True
        )
        if interaction.guild.icon:
            embed.set_thumbnail(url=interaction.guild.icon.url)
        await interaction.response.send_message(embed=embed)

    # Functions

    async def tiers(
        self, guild: discord.Guild, name: Optional[str] = None
    ) -> List[Tier]:
        """Fetch a list of tiers"""
        async with ApiClient(self._api_conf[guild]) as client:
            api = TiersApi(client)
            tiers = await api.tiers_list(
                name=name, league=str(self._league[guild])
            )  # INT
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
        async with ApiClient(self._api_conf[guild]) as client:
            api = TiersApi(client)
            tier = await api.tiers_read(id)
            return tier
