import discord
import logging
import tempfile

from pydantic import parse_obj_as
from os import PathLike
from redbot.core import app_commands, checks

from rscapi import ApiClient, FranchisesApi, TeamsApi
from rscapi.exceptions import ApiException
from rscapi.models.franchise import Franchise
from rscapi.models.franchise_gm import FranchiseGM
from rscapi.models.franchise_list import FranchiseList
from rscapi.models.team_list import TeamList

from rsc.abc import RSCMixIn
from rsc.const import FREE_AGENT_ROLE, GM_ROLE
from rsc.embeds import ErrorEmbed, SuccessEmbed, BlueEmbed, ApiExceptionErrorEmbed
from rsc.exceptions import RscException
from rsc.enums import Status
from rsc.franchises.views import (
    CreateFranchiseView,
    DeleteFranchiseView,
    FranchiseRebrandModal,
    RebrandFranchiseView,
)
from rsc.views import LinkButton
from rsc.utils.utils import franchise_role_from_name, update_prefix_for_role, remove_prefix

from typing import List, Dict, Optional, Union

log = logging.getLogger("red.rsc.franchises")


class FranchiseMixIn(RSCMixIn):
    def __init__(self):
        log.debug("Initializing FranchiseMixIn")
        self._franchise_cache: Dict[int, List[str]] = {}
        super().__init__()

    # Autocomplete

    async def franchise_autocomplete(
        self, interaction: discord.Interaction, current: str
    ) -> List[app_commands.Choice[str]]:
        if not interaction.guild_id:
            return []

        # Return nothing if cache does not exist.
        if not self._franchise_cache.get(interaction.guild_id):
            return []

        choices = []
        for f in self._franchise_cache[interaction.guild_id]:
            if current.lower() in f.lower():
                choices.append(app_commands.Choice(name=f, value=f))
            if len(choices) == 25:
                return choices
        return choices

    # Franchise Management

    _franchise = app_commands.Group(
        name="franchise",
        description="Manage league franchises",
        guild_only=True,
        default_permissions=discord.Permissions(manage_guild=True),
    )

    @_franchise.command(
        name="create", description="Create a new franchise in the league"
    )
    async def _franchise_create(
        self,
        interaction: discord.Interaction,
        name: str,
        prefix: str,
        gm: discord.Member,
    ):
        create_view = CreateFranchiseView(interaction, name, gm)
        await create_view.prompt()
        await create_view.wait()

        if not create_view.result:
            return

        try:
            log.debug(f"Creating franchise: {name}")
            f = await self.create_franchise(interaction.guild, name, prefix, gm)
        except ApiException as exc:
            log.debug(exc)
            await interaction.edit_original_response(
                embed=ApiExceptionErrorEmbed(exc=RscException(response=exc)), view=None
            )
            return

        # Create franchise role
        frole = await interaction.guild.create_role(
            name=f"{name} ({f.gm.rsc_name})", reason="New franchise created"
        )

        # GM role
        gm_role = discord.utils.get(interaction.guild.roles, name=GM_ROLE)

        await gm.add_roles(frole, gm_role)

        # Update GM Prefix
        gm_name = await remove_prefix(gm)
        await gm.edit(nick=f"{prefix} | {gm_name}")

        embed = SuccessEmbed(description=f"Franchise has been created.")
        embed.add_field(name="Name", value=name, inline=True)
        embed.add_field(name="GM", value=gm.mention, inline=True)
        await interaction.edit_original_response(embed=embed, view=None)

    @_franchise.command(name="delete", description="Delete a franchise")
    @app_commands.autocomplete(franchise=franchise_autocomplete)
    async def _franchise_delete(
        self,
        interaction: discord.Interaction,
        franchise: str,
    ):
        await interaction.response.defer(ephemeral=True)
        fl = await self.franchises(interaction.guild, name=franchise)
        if not fl:
            await interaction.followup.send(
                embed=ErrorEmbed(description="No franchise found with that name."),
                ephemeral=True
            )
            return
        if len(fl) > 1:
            await interaction.followup.send(
                embed=ErrorEmbed(
                    description="Found multiple franchises matching that name... Please be more specific."
                ),
                ephemeral=True
            )
            return

        fdata = fl.pop()
        delete_view = DeleteFranchiseView(interaction, name=franchise)
        await delete_view.prompt()
        await delete_view.wait()

        if not delete_view.result:
            return

        # Get franchise role
        frole = await franchise_role_from_name(
            interaction.guild, franchise_name=franchise
        )
        if not frole:
            log.error(
                f"[{interaction.guild}] Unable to find franchise role for deletion: {franchise}"
            )
            await interaction.edit_original_response(
                embed=ErrorEmbed(
                    description=f"Unable to find role for franchise: {franchise}\n\nFranchise was not deleted."
                )
            )
            return

        # Delete franchise in API
        await self.delete_franchise(interaction.guild, id=fdata.id)

        # Free Agent
        fa_role = discord.utils.get(interaction.guild.roles, name=FREE_AGENT_ROLE)

        # Move all players to FA

        # Remove GM role from GM, Add Former

        # Delete role
        log.debug(f"Deleting franchise role: {frole.name}")
        await frole.delete(reason="Franchise has been deleted")

        # Send result
        await interaction.edit_original_response(
            embed=SuccessEmbed(
                description=f"**{franchise}** has been successfully deleted."
            ),
            view=None,
        )

    @_franchise.command(name="rebrand", description="Rebrand a franchise")
    @app_commands.autocomplete(franchise=franchise_autocomplete)
    async def _franchise_rebrand(
        self,
        interaction: discord.Interaction,
        franchise: str,
    ):
        # Send modal
        rebrand_modal = FranchiseRebrandModal()
        await interaction.response.send_modal(rebrand_modal)

        # Fetch franchise data while user is in modal
        fl = await self.franchises(interaction.guild, name=franchise)
        await rebrand_modal.wait()

        # Validate original franchise exists
        if not fl:
            await rebrand_modal.interaction.response.send_message(
                embed=ErrorEmbed(description="No franchise found with that name."),
                ephemeral=True
            )
            return
        if len(fl) > 1:
            await rebrand_modal.interaction.response.send_message(
                embed=ErrorEmbed(
                    description="Found multiple franchises matching that name... Please be more specific."
                ),
                ephemeral=True
            )
            return

        fdata = fl.pop()

        if len(rebrand_modal.teams) != len(fdata.tiers):
            await rebrand_modal.interaction.response.send_message(
                embed=ErrorEmbed(
                    description=(
                        "Number of team names does not match number of tiers in franchise.\n\n"
                        f"**Tiers:** {len(fdata.tiers)}\n"
                        f"**Team Names:** {len(rebrand_modal.teams)}"
                    )
                ),
                ephemeral=True,
            )
            return

        # Match teams to tiers
        teams = {}
        for t in fdata.tiers:
            teams[t.name] = rebrand_modal.teams.pop(0)

        rebrand_view = RebrandFranchiseView(
            rebrand_modal.interaction,
            old_name=franchise,
            name=rebrand_modal.name,
            prefix=rebrand_modal.prefix,
            teams=teams,
        )
        await rebrand_view.prompt()
        await rebrand_view.wait()

        if not rebrand_view.result:
            return

        # Rebrand Franchise
        log.debug("Rebranding franchise.")

        # Update franchise role
        frole = await franchise_role_from_name(interaction.guild, franchise)
        if not frole:
            log.error(
                f"[{interaction.guild}] Unable to find franchise role for rebrand: {franchise}"
            )
            return
        await frole.edit(name=f"{rebrand_modal.name} ({fdata.gm.rsc_name})")

        # Update all prefix
        await update_prefix_for_role(frole, rebrand_modal.prefix)


    @_franchise.command(name="logo", description="Upload a logo for the franchise")
    @app_commands.autocomplete(franchise=franchise_autocomplete)
    async def _franchise_logo(
        self, interaction: discord.Interaction, franchise: str, logo: discord.Attachment
    ):
        # validate franchise
        franchise_data = await self.franchises(interaction.guild, name=franchise)
        if not franchise_data:
            await interaction.response.send_message(
                embed=ErrorEmbed(description=f"**{franchise}** does not exist."),
                ephemeral=True,
            )
            return

        # Defer in case file is large
        await interaction.response.defer(ephemeral=True)

        # have to do this because monty sux
        with tempfile.NamedTemporaryFile() as fp:
            fp.write(await logo.read())
            fp.seek(0)
            result = await self.upload_franchise_logo(
                interaction.guild, franchise_data[0].id, fp.name
            )

        embed = SuccessEmbed(
            title="Logo Updated",
            description=f"{franchise} logo has been uploaded to the API.",
        )
        embed.add_field(name="Height", value=logo.height, inline=True)
        embed.add_field(name="Width", value=logo.width, inline=True)
        embed.add_field(name="Size", value=logo.size, inline=True)

        # URL Button (Fix this once full link is returned)
        url_button = LinkButton(
            label="Logo Link", url=f"https://staging-api.rscna.com{result.logo}"
        )
        logo_view = discord.ui.View()
        logo_view.add_item(url_button)

        # Add new logo as thumbnail in embed
        embed.set_thumbnail(url=logo.url)
        await interaction.followup.send(embed=embed, view=logo_view, ephemeral=True)

    # Commands

    @app_commands.command(
        name="franchises", description="Get a list of all RSC franchises"
    )
    @app_commands.guild_only()
    async def _franchises(self, interaction: discord.Interaction):
        """Get a list of all RSC franchises"""
        franchises = await self.franchises(interaction.guild)

        gm_names = []
        for f in franchises:
            member = interaction.guild.get_member(f.gm.discord_id)
            if member:
                gm_names.append(member.mention)
            else:
                gm_names.append(f.gm.rsc_name)

        embed = discord.Embed(
            title=f"{interaction.guild} Franchises",
            color=discord.Color.blue(),
        )
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
        if interaction.guild.icon:
            embed.set_thumbnail(url=interaction.guild.icon.url)
        await interaction.response.send_message(embed=embed)

    # Functions

    async def franchise_name_to_id(
        self, guild: discord.Guild, franchise_name: str
    ) -> int:
        franchise = await self.franchises(guild, name=franchise_name)
        if not franchise:
            return 0

        return franchise[0].id

    # API

    async def franchises(
        self,
        guild: discord.Guild,
        prefix: Optional[str] = None,
        gm_name: Optional[str] = None,
        name: Optional[str] = None,
        tier: Optional[str] = None,
        tier_name: Optional[str] = None,
    ) -> List[FranchiseList]:
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
                    log.debug(f"[{guild.name}] Adding new franchises to cache")
                    cached = set(self._franchise_cache[guild.id])
                    different = set([f.name for f in franchises]) - cached
                    log.debug(f"[{guild.name}] Franchises being added to cache: {different}")
                    self._franchise_cache[guild.id] += list(different)
                else:
                    log.debug(f"[{guild.name}] Starting fresh franchises cache")
                    self._franchise_cache[guild.id] = [f.name for f in franchises]
                self._franchise_cache[guild.id].sort()
            return franchises

    async def franchise_by_id(
        self, guild: discord.Guild, id: int
    ) -> Optional[Franchise]:
        async with ApiClient(self._api_conf[guild.id]) as client:
            api = FranchisesApi(client)
            return await api.franchises_read(id)

    async def upload_franchise_logo(
        self,
        guild: discord.Guild,
        id: int,
        logo: Union[str, bytes, PathLike],
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
    ) -> FranchiseList:
        async with ApiClient(self._api_conf[guild.id]) as client:
            api = FranchisesApi(client)
            data = FranchiseList(
                name=name,
                league=self._league[guild.id],
                prefix=prefix,
                gm=FranchiseGM(discord_id=gm.id),
            )
            return await api.franchises_create(data)

    async def delete_franchise(self, guild: discord.Guild, id: int) -> None:
        async with ApiClient(self._api_conf[guild.id]) as client:
            api = FranchisesApi(client)
            await api.franchises_delete(id)
