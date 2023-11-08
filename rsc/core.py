import discord
import logging

from redbot.core import Config, app_commands, commands, checks

from rscapi import Configuration

from rsc.abc import CoreMeta
from rsc.transactions import TransactionMixIn
from rsc.numbers import NumbersMixIn
from rsc.league import LeagueMixIn
from rsc.franchises import FranchiseMixIn
from rsc.teams import TeamMixIn

from typing import Optional

log = logging.getLogger("red.rsc.core")

defaults_global = {
    "ApiKey": None,
    "ApiUrl": None,
}


class RSC(
    FranchiseMixIn,
    LeagueMixIn,
    NumbersMixIn,
    TransactionMixIn,
    commands.Cog,
):
    def __init__(self, bot):
        self.bot = bot
        self.config = Config.get_conf(
            self, identifier=6349109713, force_registration=True
        )

        self.config.register_global(**defaults_global)

        # Define state of API connection
        self._api_conf = None
        super().__init__()
        log.info("RSC Bot has been started.")

    async def prepare_api(self):
        url = await self._get_api_url()
        key = await self._get_api_key()
        if url and key:
            self._api_conf = Configuration(
                host=url,
                api_key=key,
            )
        else:
            log.warning("RSC API key or url has not been configured!")

    # Configuration

    api_settings = app_commands.Group(
        name="rscapi", description="RSC API Configuration"
    )

    @api_settings.command(name="key", description="Configure the RSC API key.")
    @checks.admin_or_permissions(manage_guild=True)
    async def _rscapi_set_key(self, interaction: discord.Interaction, key: str):
        await self._set_api_key(interaction.guild, key)
        await interaction.response.send_message(
            embed=discord.Embed(
                title="RSC API Key",
                description="RSC API key has been successfully configured.",
                color=discord.Color.green(),
            ),
            ephemeral=True,
        )

    @api_settings.command(name="url", description="Configure the RSC API web address.")
    @checks.admin_or_permissions(manage_guild=True)
    async def _rscapi_set_url(self, interaction: discord.Interaction, url: str):
        await self._set_api_url(interaction.guild, url)
        await interaction.response.send_message(
            embed=discord.Embed(
                title="RSC API Url",
                description="RSC API url has been successfully configured.",
                color=discord.Color.green(),
            ),
            ephemeral=True,
        )

    @api_settings.command(
        name="settings", description="Display the current RSC API settings."
    )
    @checks.admin_or_permissions(manage_guild=True)
    async def _rscapi_settings(self, interaction: discord.Interaction):
        key = (
            "Configured"
            if await self._get_api_key(interaction.guild)
            else "Not Configured"
        )
        url = await self._get_api_url(interaction.guild) or "Not Configured"
        log.debug(f"Key: {key} URL: {url}")
        settings_embed = discord.Embed(
            title="RSC API Settings",
            description="Current RSCI API configuration.",
            color=discord.Color.blue(),
        )

        settings_embed.add_field(name="API Key", value=key, inline=False)
        settings_embed.add_field(name="API URL", value=url, inline=False)
        await interaction.response.send_message(embed=settings_embed, ephemeral=True)

    async def _set_leauge(self, key: str):
        await self.config.ApiKey.set(key)

    async def _set_api_key(self, key: str):
        await self.config.ApiKey.set(key)

    async def _get_api_key(self) -> Optional[str]:
        return await self.config.ApiKey()

    async def _set_api_url(self, url: str):
        await self.config.ApiUrl.set(url)

    async def _get_api_url(self) -> Optional[str]:
        return await self.config.ApiUrl()
