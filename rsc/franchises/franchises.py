import logging
from os import PathLike
from typing import cast
from urllib.parse import urljoin

import discord
from pydantic import ValidationError
from redbot.core import app_commands
from rscapi import FranchisesApi
from rscapi.exceptions import ApiException, NotFoundException
from rscapi.models.franchise import Franchise
from rscapi.models.franchise_agm_request import FranchiseAGMRequest
from rscapi.models.franchise_gm import FranchiseGM
from rscapi.models.franchise_league import FranchiseLeague
from rscapi.models.franchise_list import FranchiseList
from rscapi.models.franchise_rebrand import FranchiseRebrand
from rscapi.models.franchise_transfer_request import FranchiseTransferRequest

from rsc.abc import RSCMixIn
from rsc.const import API_TIMEOUT
from rsc.embeds import BlueEmbed
from rsc.exceptions import RscException
from rsc.utils.cache import merge_name_cache

log = logging.getLogger("red.rsc.franchises")


class FranchiseMixIn(RSCMixIn):
    def __init__(self):
        log.debug("Initializing FranchiseMixIn")
        self._franchise_cache: dict[int, list[str]] = {}
        super().__init__()

    # Autocomplete

    async def franchise_autocomplete(self, interaction: discord.Interaction, current: str) -> list[app_commands.Choice[str]]:
        if not interaction.guild_id:
            return []

        # Return nothing if cache does not exist.
        if not self._franchise_cache.get(interaction.guild_id):
            return []

        if not current:
            return [app_commands.Choice(name=f, value=f) for f in self._franchise_cache[interaction.guild_id][:25]]

        choices = []
        for f in self._franchise_cache[interaction.guild_id]:
            if current.lower() in f.lower():
                choices.append(app_commands.Choice(name=f, value=f))
            if len(choices) == 25:
                return choices
        return choices

    # Commands

    @app_commands.command(name="franchises", description="Get a list of all RSC franchises")
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

    async def franchise_gm_by_name(self, guild: discord.Guild, name: str) -> FranchiseGM | None:
        result = await self.franchises(guild=guild, name=name)

        if not result:
            return None

        if len(result) > 1:
            raise ValueError(f"Found more than one franchise matching: {name}")

        franchise = result.pop(0)

        if not franchise.gm:
            return None

        return franchise.gm

    async def fetch_franchise(self, guild: discord.Guild, name: str) -> FranchiseList | None:
        result = await self.franchises(guild=guild, name=name)

        if not result:
            return None

        if len(result) > 1:
            raise ValueError(f"Found more than one franchise matching: {name}")

        franchise = result.pop(0)
        return franchise

    async def franchise_name_to_id(self, guild: discord.Guild, franchise_name: str) -> int:
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
        tier_name: str | list[str] | None = None,
    ) -> list[FranchiseList]:
        tier_names = [tier_name] if isinstance(tier_name, str) else tier_name

        # An unfiltered query returns the authoritative full list, so the cache
        # is rebuilt from it. A filtered one can only add. Merging in both cases
        # meant a rebranded or deleted franchise lingered in autocomplete until
        # the process restarted.
        full_refresh = not any((prefix, gm_name, gm_discord_id, name, tier, tier_names))

        async with self.api_client(guild) as client:
            api = FranchisesApi(client)
            flist = await api.franchises_list(
                prefix=prefix,
                league=self._league[guild.id],
                gm_name=gm_name,
                gm_discord_id=gm_discord_id,
                name=name,
                tier=tier,
                tier_name=tier_names,
                _request_timeout=API_TIMEOUT,
            )

            # Populate cache
            if flist:
                if not all(f.name for f in flist):
                    raise AttributeError("API returned a franchise with no name.")

                flist.sort(key=lambda f: cast("str", f.name))
                cached = self._franchise_cache.get(guild.id, [])
                merged = merge_name_cache(cached, (f.name for f in flist if f.name), full_refresh=full_refresh)
                merged.sort()
                if merged != cached:
                    log.debug(f"[{guild.name}] Franchise cache now holds {len(merged)} franchises")
                self._franchise_cache[guild.id] = merged
            return flist

    async def franchise_by_id(self, guild: discord.Guild, id: int) -> Franchise | None:
        async with self.api_client(guild) as client:
            api = FranchisesApi(client)
            return await api.franchises_retrieve(id)

    async def upload_franchise_logo(
        self,
        guild: discord.Guild,
        id: int,
        logo: str | bytes | PathLike,
    ) -> Franchise:
        async with self.api_client(guild) as client:
            api = FranchisesApi(client)
            try:
                logo_param = str(logo) if isinstance(logo, PathLike) else logo
                return await api.franchises_upload_logo_update(id=id, logo=logo_param)
            except ApiException as exc:
                raise RscException(response=exc)

    async def create_franchise(
        self,
        guild: discord.Guild,
        name: str,
        prefix: str,
        gm: discord.Member,
    ) -> Franchise:
        async with self.api_client(guild) as client:
            api = FranchisesApi(client)

            # Remaining fields are read-only and excluded from the request body
            try:
                data = Franchise(
                    name=name,
                    prefix=prefix,
                    league=FranchiseLeague(id=self._league[guild.id]),
                    gm=FranchiseGM(discord_id=gm.id, rsc_name=gm.display_name),
                )
            except ValidationError as exc:
                raise RscException(message=f"Invalid franchise data: {exc.errors()[0]['msg']}")

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

            return result

    async def delete_franchise(self, guild: discord.Guild, id: int) -> None:
        async with self.api_client(guild) as client:
            api = FranchisesApi(client)
            try:
                await api.franchises_destroy(id)
            except ApiException as exc:
                raise RscException(response=exc)

    async def rebrand_franchise(self, guild: discord.Guild, id: int, rebrand: FranchiseRebrand) -> Franchise:
        async with self.api_client(guild) as client:
            api = FranchisesApi(client)
            try:
                log.debug(f"Rebrand Params: {rebrand}")
                return await api.franchises_rebrand_update(id, rebrand)
            except ApiException as exc:
                raise RscException(response=exc)

    async def transfer_franchise(self, guild: discord.Guild, id: int, gm: discord.Member) -> Franchise:
        async with self.api_client(guild) as client:
            api = FranchisesApi(client)
            try:
                data = FranchiseTransferRequest(general_manager=gm.id, league=self._league[guild.id])
                log.debug(f"Transfer Params: {data}")
                return await api.franchises_transfer_franchise_update(id, data)
            except ApiException as exc:
                raise RscException(response=exc)

    async def add_agm(
        self, guild: discord.Guild, id: int, agm: discord.Member | discord.User | int, executor: discord.Member | discord.User | int
    ) -> Franchise:
        """Add an AGM to a franchise.

        Both members are addressed by discord ID, not database ID. `executor`
        must hold the Admin elevated role in the franchise's league or the API
        answers 403. Idempotent: re-adding an existing AGM is a no-op that still
        returns 202 with the franchise.

        Returns the refreshed `Franchise`, so callers do not need to re-fetch to
        see the new `agms` list.
        """
        agm_id = agm if isinstance(agm, int) else agm.id
        executor_id = executor if isinstance(executor, int) else executor.id

        async with self.api_client(guild) as client:
            api = FranchisesApi(client)
            try:
                data = FranchiseAGMRequest(agm=agm_id, executor=executor_id)
                log.debug(f"Add AGM Params: franchise={id} {data}")
                return await api.franchises_add_agm_update(id=id, franchise_agm_request=data)
            except ApiException as exc:
                raise RscException(response=exc)

    async def remove_agm(
        self, guild: discord.Guild, id: int, agm: discord.Member | discord.User | int, executor: discord.Member | discord.User | int
    ) -> Franchise:
        """Remove an AGM from a franchise.

        Mirrors `add_agm`. Answers 404 if the member is not an AGM of this
        franchise, so callers that treat "already gone" as success must check
        `RscException.status`.
        """
        agm_id = agm if isinstance(agm, int) else agm.id
        executor_id = executor if isinstance(executor, int) else executor.id

        async with self.api_client(guild) as client:
            api = FranchisesApi(client)
            try:
                data = FranchiseAGMRequest(agm=agm_id, executor=executor_id)
                log.debug(f"Remove AGM Params: franchise={id} {data}")
                return await api.franchises_remove_agm_update(id=id, franchise_agm_request=data)
            except ApiException as exc:
                raise RscException(response=exc)

    async def franchises_agm_of(self, guild: discord.Guild, discord_id: int) -> list[FranchiseList]:
        """Every franchise in this league that lists `discord_id` as an AGM.

        The API has no reverse lookup for franchise staff, but `franchises_list`
        returns `agms` inline and prefetched, so one request answers it. Used to
        find records left behind when an AGM moves between franchises, and to
        explain a removal that names the wrong franchise.
        """
        flist = await self.franchises(guild)
        return [f for f in flist if any(a.discord_id == discord_id for a in (f.agms or []))]

    async def agm_franchise_of(self, guild: discord.Guild, discord_id: int) -> FranchiseList | None:
        """The single franchise this member is an AGM of, or `None`.

        The AGM answer every caller actually wants: role sync and `/match` need
        one franchise, not a list. Holding AGM records on two franchises is a
        data error -- `/admin agm add` drops the old record when an AGM moves --
        so first in list order wins and the collision is logged rather than
        silently picked.
        """
        memberships = await self.franchises_agm_of(guild, discord_id)
        if not memberships:
            return None

        if len(memberships) > 1:
            names = ", ".join(f.name or str(f.id) for f in memberships)
            log.warning(f"[{guild.name}] {discord_id} is an AGM of multiple franchises: {names}. Using {memberships[0].name}.")

        return memberships[0]

    async def agm_franchise_map(self, guild: discord.Guild) -> dict[int, FranchiseList]:
        """Every AGM in the league, keyed by discord ID.

        One request answers the whole league because `FranchiseList` carries
        `agms` inline. Bulk syncs must use this instead of calling
        `agm_franchise_of` per member: `_franchise_cache` only holds franchise
        *names*, so `franchises()` is a live request every time and a per-member
        lookup is one full franchise list per member.

        Raises `RuntimeError` if the API returns no franchises at all. Callers
        read a missing key as "not an AGM", so an empty answer would strip every
        AGM in the guild in a single bulk sync. A league always has franchises.
        """
        flist = await self.franchises(guild)
        if not flist:
            raise RuntimeError(f"[{guild.name}] API returned no franchises. Refusing to build an AGM map.")

        result: dict[int, FranchiseList] = {}
        for f in flist:
            for agm in f.agms or []:
                if not agm.discord_id:
                    continue
                existing = result.get(agm.discord_id)
                if existing is not None:
                    log.warning(
                        f"[{guild.name}] {agm.discord_id} is an AGM of multiple franchises: "
                        f"{existing.name}, {f.name}. Using {existing.name}."
                    )
                    continue
                result[agm.discord_id] = f
        return result

    async def franchise_logo(self, guild: discord.Guild, id: int) -> str | None:
        host = await self._get_api_url(guild)
        if not host:
            return None

        async with self.api_client(guild) as client:
            api = FranchisesApi(client)
            try:
                logo = await api.franchises_logo_retrieve(id)
                if not (logo and logo.logo):
                    return None
                full_url = urljoin(host, logo.logo)
                log.debug(f"Franchise Logo: {full_url}")
                return full_url
            except NotFoundException:
                return None
            except ApiException as exc:
                raise RscException(response=exc)
