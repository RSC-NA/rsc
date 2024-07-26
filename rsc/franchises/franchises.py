import logging
from os import PathLike
from typing import cast
from urllib.parse import urljoin

import discord
from redbot.core import app_commands
from rscapi import ApiClient, FranchisesApi
from rscapi.exceptions import ApiException, NotFoundException
from rscapi.models.franchise import Franchise
from rscapi.models.franchise_gm import FranchiseGM
from rscapi.models.franchise_league import FranchiseLeague
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

    @app_commands.command(  # type: ignore
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
            if not (f.gm and f.gm.rsc_name and f.gm.discord_id):
                gm_names.append("None")
                continue
            member = guild.get_member(f.gm.discord_id)
            if member:
                gm_names.append(member.mention)
            else:
                gm_names.append(f.gm.rsc_name)

        embed = BlueEmbed(title=f"{guild.name} Franchises")
        embed.add_field(
            name="Prefix",
            value="\n".join([f.prefix or "None" for f in franchises]),
            inline=True,
        )
        embed.add_field(
            name="Franchise",
            value="\n".join([f.name or "Error" for f in franchises]),
            inline=True,
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

    async def franchise_gm_by_name(
        self, guild: discord.Guild, name: str
    ) -> FranchiseGM | None:
        result = await self.franchises(guild=guild, name=name)

        if not result:
            return None

        if len(result) > 1:
            raise ValueError(f"Found more than one franchise matching: {name}")

        franchise = result.pop(0)

        if not franchise.gm:
            return None

        return franchise.gm

    async def franchise_name_to_id(
        self, guild: discord.Guild, franchise_name: str
    ) -> int:
        franchise = await self.franchises(guild, name=franchise_name)
        if not franchise:
            return 0

        fId = franchise[0].id
        if not fId:
            raise AttributeError("Franchise data has no ID attached.")
        return fId

    async def delete_franchise_by_name(self, guild: discord.Guild, franchise_name: str):
        flist = await self.franchises(guild, name=franchise_name)
        if not flist:
            raise ValueError(f"{franchise_name} does not exist")

        if len(flist) > 1:
            raise ValueError(f"{franchise_name} matches more than one franchise name")
        f = flist.pop()
        if not f.id:
            raise AttributeError("Franchise data has no ID attached.")
        await self.delete_franchise(guild, f.id)

    async def full_logo_url(self, guild: discord.Guild, logo_url: str) -> str:
        host = await self._get_api_url(guild)
        if not host:
            raise RuntimeError(f"[{guild.name}] RSC API host is not configured.")
        return urljoin(host, logo_url)

    # API

    async def franchises(
        self,
        guild: discord.Guild,
        prefix: str | None = None,
        gm_name: str | None = None,
        gm_discord_id: int | None = None,
        name: str | None = None,
        tier: int | None = None,
        tier_name: str | None = None,
    ) -> list[FranchiseList]:
        async with ApiClient(self._api_conf[guild.id]) as client:
            api = FranchisesApi(client)
            flist = await api.franchises_list(
                prefix=prefix,
                league=self._league[guild.id],
                gm_name=gm_name,
                gm_discord_id=gm_discord_id,
                name=name,
                tier=tier,
                tier_name=tier_name,
            )

            # Populate cache
            if flist:
                if not all(f.name for f in flist):
                    raise AttributeError("API returned a franchise with no name.")

                flist.sort(key=lambda f: cast(str, f.name))
                if self._franchise_cache.get(guild.id):
                    cached = set(self._franchise_cache[guild.id])
                    different = {f.name for f in flist if f.name} - cached
                    if different:
                        log.debug(
                            f"[{guild.name}] Franchises being added to cache: {different}"
                        )
                        self._franchise_cache[guild.id] += list(different)
                else:
                    log.debug(f"[{guild.name}] Starting fresh franchises cache")
                    self._franchise_cache[guild.id] = [f.name for f in flist if f.name]
                self._franchise_cache[guild.id].sort()
            return flist

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
            try:
                return await api.franchises_upload_logo(id=id, logo=logo)  # type: ignore
            except ApiException as exc:
                raise RscException(response=exc)

    async def create_franchise(
        self,
        guild: discord.Guild,
        name: str,
        prefix: str,
        gm: discord.Member,
    ) -> Franchise:
        async with ApiClient(self._api_conf[guild.id]) as client:
            api = FranchisesApi(client)

            fleague = FranchiseLeague(id=self._league[guild.id], guild_id=guild.id)
            data = Franchise(
                name=name,
                league=fleague,
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
            except NotFoundException:
                return None
            except ApiException as exc:
                raise RscException(response=exc)
