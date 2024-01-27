import logging
from os import PathLike
from urllib.parse import urljoin

import discord
from redbot.core import app_commands
from rscapi import ApiClient, FranchisesApi
from rscapi.exceptions import ApiException
from rscapi.models.franchise import Franchise
from rscapi.models.franchise_gm import FranchiseGM
from rscapi.models.franchise_list import FranchiseList
from rscapi.models.rebrand_a_franchise import RebrandAFranchise
from rscapi.models.transfer_franchise import TransferFranchise

from rsc.abc import RSCMixIn
from rsc.embeds import BlueEmbed
from rsc.exceptions import RscException

log = logging.getLogger("red.rsc.franchises")


class FranchiseMixIn(RSCMixIn):
    def __init__(self):
        log.debug("Initializing FranchiseMixIn")
        self._franchise_cache: dict[int, list[str]] = {}
        super().__init__()

    # Autocomplete

    async def franchise_autocomplete(
        self, interaction: discord.Interaction, current: str
    ) -> list[app_commands.Choice[str]]:
        if not interaction.guild_id:
            return []

        # Return nothing if cache does not exist.
        if not self._franchise_cache.get(interaction.guild_id):
            return []

        if not current:
            return [
                app_commands.Choice(name=f, value=f)
                for f in self._franchise_cache[interaction.guild_id][:25]
            ]

        choices = []
        for f in self._franchise_cache[interaction.guild_id]:
            if current.lower() in f.lower():
                choices.append(app_commands.Choice(name=f, value=f))
            if len(choices) == 25:
                return choices
        return choices

    # Commands

    @app_commands.command(
        name="franchises", description="Get a list of all RSC franchises"
    )
    @app_commands.guild_only
    async def _franchises(self, interaction: discord.Interaction):
        """Get a list of all RSC franchises"""
        guild = interaction.guild
        if not guild:
            return

        await interaction.response.defer()
        franchises = await self.franchises(guild)

        gm_names = []
        for f in franchises:
            member = guild.get_member(f.gm.discord_id)
            if member:
                gm_names.append(member.mention)
            else:
                gm_names.append(f.gm.rsc_name)

        embed = BlueEmbed(title=f"{guild.name} Franchises")
        embed.add_field(
            name="Prefix", value="\n".join([f.prefix for f in franchises]), inline=True
        )
        embed.add_field(
            name="Franchise", value="\n".join([f.name for f in franchises]), inline=True
        )
        embed.add_field(
            name="General Manager",
            value="\n".join(gm_names),
            inline=True,
        )
        if guild.icon:
            embed.set_thumbnail(url=guild.icon.url)
        await interaction.followup.send(embed=embed)

    # Functions

    async def franchise_name_to_id(
        self, guild: discord.Guild, franchise_name: str
    ) -> int:
        franchise = await self.franchises(guild, name=franchise_name)
        if not franchise:
            return 0

        return franchise[0].id

    async def delete_franchise_by_name(self, guild: discord.Guild, franchise_name: str):
        flist = await self.franchises(guild, name=franchise_name)
        if not flist:
            raise ValueError(f"{franchise_name} does not exist")

        if len(flist) > 1:
            raise ValueError(f"{franchise_name} matches more than one franchise name")

        f = flist.pop()
        await self.delete_franchise(guild, f.id)

    async def full_logo_url(self, guild: discord.Guild, logo_url: str) -> str | None:
        host = await self._get_api_url(guild)
        if not host:
            log.warning(f"[{guild.name}] RSC API host is not configured.")
            return None
        return urljoin(host, logo_url)

    # API

    async def franchises(
        self,
        guild: discord.Guild,
        prefix: str | None = None,
        gm_name: str | None = None,
        name: str | None = None,
        tier: str | None = None,
        tier_name: str | None = None,
    ) -> list[FranchiseList]:
        async with ApiClient(self._api_conf[guild.id]) as client:
            api = FranchisesApi(client)
            franchises = await api.franchises_list(
                prefix=prefix,
                gm_name=gm_name,
                name=name,
                tier=tier,
                tier_name=tier_name,
                league=self._league[guild.id],
            )

            # Populate cache
            if franchises:
                franchises.sort(key=lambda f: f.name)
                if self._franchise_cache.get(guild.id):
                    cached = set(self._franchise_cache[guild.id])
                    different = {f.name for f in franchises} - cached
                    if different:
                        log.debug(
                            f"[{guild.name}] Franchises being added to cache: {different}"
                        )
                        self._franchise_cache[guild.id] += list(different)
                else:
                    log.debug(f"[{guild.name}] Starting fresh franchises cache")
                    self._franchise_cache[guild.id] = [f.name for f in franchises]
                self._franchise_cache[guild.id].sort()
            return franchises

    async def franchise_by_id(self, guild: discord.Guild, id: int) -> Franchise | None:
        async with ApiClient(self._api_conf[guild.id]) as client:
            api = FranchisesApi(client)
            return await api.franchises_read(id)

    async def upload_franchise_logo(
        self,
        guild: discord.Guild,
        id: int,
        logo: str | bytes | PathLike,
    ) -> Franchise:
        async with ApiClient(self._api_conf[guild.id]) as client:
            api = FranchisesApi(client)
            return await api.franchises_upload_logo(id=id, logo=logo)  # type: ignore

    async def create_franchise(
        self,
        guild: discord.Guild,
        name: str,
        prefix: str,
        gm: discord.Member,
    ) -> Franchise:
        async with ApiClient(self._api_conf[guild.id]) as client:
            api = FranchisesApi(client)
            league = await self.league(guild)
            if not league:
                raise RuntimeError(
                    "Unable to get league from API for guild: {guild.name}"
                )

            data = Franchise(
                name=name,
                league=league,
                prefix=prefix,
                gm=FranchiseGM(discord_id=gm.id),
            )
            log.debug(f"Create Franchise Data: {data}")
            try:
                result = await api.franchises_create(data)
            except ApiException as exc:
                raise RscException(response=exc)

            # Populate cache
            if result.name not in self._franchise_cache[guild.id]:
                log.debug(f"Adding {result.name} to franchise cache")
                self._franchise_cache[guild.id].append(result.name)
                self._franchise_cache[guild.id].sort()

            return await api.franchises_create(data)

    async def delete_franchise(self, guild: discord.Guild, id: int) -> None:
        async with ApiClient(self._api_conf[guild.id]) as client:
            api = FranchisesApi(client)
            try:
                await api.franchises_delete(id)
            except ApiException as exc:
                raise RscException(response=exc)

    async def rebrand_franchise(
        self, guild: discord.Guild, id: int, rebrand: RebrandAFranchise
    ) -> Franchise:
        async with ApiClient(self._api_conf[guild.id]) as client:
            api = FranchisesApi(client)
            try:
                log.debug(f"Rebrand Params: {rebrand}")
                return await api.franchises_rebrand(id, rebrand)
            except ApiException as exc:
                raise RscException(response=exc)

    async def transfer_franchise(
        self, guild: discord.Guild, id: int, gm: discord.Member
    ) -> Franchise:
        async with ApiClient(self._api_conf[guild.id]) as client:
            api = FranchisesApi(client)
            try:
                data = TransferFranchise(
                    general_manager=gm.id, league=self._league[guild.id]
                )
                log.debug(f"Transfer Params: {data}")
                return await api.franchises_transfer_franchise(id, data)
            except ApiException as exc:
                raise RscException(response=exc)

    async def franchise_logo(self, guild: discord.Guild, id: int) -> str | None:
        host = await self._get_api_url(guild)
        if not host:
            return None

        async with ApiClient(self._api_conf[guild.id]) as client:
            api = FranchisesApi(client)
            try:
                logo = await api.franchises_logo(id)
                if not (logo and logo.logo):
                    return None
                full_url = urljoin(host, logo.logo)
                log.debug(f"Franchise Logo: {full_url}")
                return full_url
            except ApiException as exc:
                raise RscException(response=exc)
