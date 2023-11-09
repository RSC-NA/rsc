import discord
import logging

from redbot.core import Config, app_commands, commands, checks

from rscapi import Configuration

from rsc.abc import CompositeMetaClass
from rsc.leagues import LeagueMixIn
from rsc.franchises import FranchiseMixIn
from rsc.teams import TeamMixIn
from rsc.tiers import TierMixIn

from typing import Optional

log = logging.getLogger("red.rsc.core")

defaults_global = {
    "ApiKey": None,
    "ApiUrl": None,
}


class RSC(
    FranchiseMixIn,
    LeagueMixIn,
    TeamMixIn,
    TierMixIn,
    commands.Cog,
    metaclass=CompositeMetaClass,
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

    # Setup 

    def cog_load(self):
        log.debug("rsc cog_load() called")
        self.bot.add_listener(self.populate_cache, 'on_ready')

    async def populate_cache(self):
        """Populate caches for autocompletion. Requires API config"""
        if self._api_conf:
            for guild in self.bot.guilds:
                log.debug(f"Preparing cache for {guild}")
                await self.franchises(guild)
                await self.tiers(guild)



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
        await self._set_api_key(key)
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
        await self._set_api_url(url)
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
        key = "Configured" if await self._get_api_key() else "Not Configured"
        url = await self._get_api_url() or "Not Configured"
        log.debug(f"Key: {key} URL: {url}")
        settings_embed = discord.Embed(
            title="RSC API Settings",
            description="Current RSCI API configuration.",
            color=discord.Color.blue(),
        )

        settings_embed.add_field(name="API Key", value=key, inline=False)
        settings_embed.add_field(name="API URL", value=url, inline=False)
        await interaction.response.send_message(embed=settings_embed, ephemeral=True)

    async def _set_api_key(self, key: str):
        await self.config.ApiKey.set(key)

    async def _get_api_key(self) -> Optional[str]:
        return await self.config.ApiKey()

    async def _set_api_url(self, url: str):
        await self.config.ApiUrl.set(url)

    async def _get_api_url(self) -> Optional[str]:
        return await self.config.ApiUrl()
