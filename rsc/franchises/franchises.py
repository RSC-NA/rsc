import discord
import logging
import tempfile

from pydantic import parse_obj_as
from os import PathLike
from redbot.core import app_commands, checks

from rscapi import ApiClient, FranchisesApi, TeamsApi
from rscapi.models.franchise import Franchise
from rscapi.models.franchise_list import FranchiseList
from rscapi.models.team_list import TeamList

from rsc.abc import RSCMixIn
from rsc.embeds import ErrorEmbed, SuccessEmbed
from rsc.enums import Status
from rsc.views import LinkButton

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
                ephemeral=True
            )
            return

        # Defer in case file is large
        await interaction.response.defer()

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
        url_button = LinkButton(label="Logo Link", url=f"https://staging-api.rscna.com{result.logo}")
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
                self._franchise_cache[guild.id] = [f.name for f in franchises]
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
            return await api.franchises_upload_logo(id=id, logo=logo) # type: ignore
