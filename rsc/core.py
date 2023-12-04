import discord
import logging
import asyncio
import validators
from aiohttp import ClientConnectionError

import pytz
from zoneinfo import ZoneInfo

from redbot.core import Config, app_commands, commands, checks

from rscapi import Configuration

# Types
from rsc.abc import CompositeMetaClass
from rsc.enums import LogLevel

# Mix Ins
from rsc.ballchasing import BallchasingMixIn
from rsc.combines import CombineMixIn
from rsc.freeagents import FreeAgentMixIn
from rsc.franchises import FranchiseMixIn
from rsc.matches import MatchMixIn
from rsc.members import MemberMixIn
from rsc.leagues import LeagueMixIn
from rsc.teams import TeamMixIn
from rsc.tiers import TierMixIn
from rsc.transactions import TransactionMixIn
from rsc.utils import UtilsMixIn

# Views
from rsc.views import LeagueSelectView, RSCSetupModal

# Util
from rsc.embeds import SuccessEmbed, ErrorEmbed

from typing import Optional, Dict, List

log = logging.getLogger("red.rsc.core")

defaults_guild = {
    "ApiKey": None,
    "ApiUrl": None,
    "League": None,
    "TimeZone": "UTC",
}


class RSC(
    BallchasingMixIn,
    CombineMixIn,
    FranchiseMixIn,
    LeagueMixIn,
    FreeAgentMixIn,
    MemberMixIn,
    MatchMixIn,
    TeamMixIn,
    TierMixIn,
    TransactionMixIn,
    UtilsMixIn,
    commands.Cog,
    metaclass=CompositeMetaClass,
):
    def __init__(self, bot):
        self.bot = bot
        self.config = Config.get_conf(
            self, identifier=6349109713, force_registration=True
        )

        self.config.register_guild(**defaults_guild)

        # Define state of API connection
        self._api_conf: Dict[int, Configuration] = {}
        # Cache the league associated with each guild
        self._league: Dict[int, int] = {}
        super().__init__()
        log.info("RSC Bot has been started.")

    # Setup

    async def cog_load(self):
        """Perform initial bot setup on Cog reload"""
        log.debug("In cog_load()")
        await asyncio.create_task(self.setup())

    @commands.Cog.listener()
    async def on_ready(self):
        """
        Perform initial bot setup on ready. This event ensures we are connected to guilds first.

        Does NOT trigger on Cog reload.
        """
        log.debug("In on_ready()")
        await asyncio.create_task(self.setup())

    async def setup(self):
        """Prepare the bot API and caches. Requires API configuration"""
        log.debug("In RSC setup()")
        for guild in self.bot.guilds:
            log.debug(f"[{guild}] Preparing API configuration")
            await self.prepare_api(guild)
            log.debug(f"[{guild}] Preparing league data")
            await self.prepare_league(guild)
            if self._api_conf.get(guild.id):
                log.debug(f"[{guild}] Preparing caches")
                try:
                    await self.tiers(guild)
                    await self.franchises(guild)
                    await self.teams(guild)
                    await self._populate_combines_cache(guild)
                    await self._populate_free_agent_cache(guild)
                except ClientConnectionError:
                    # Pass so that the package loads successfully with invalid url/key
                    pass

    async def prepare_league(self, guild: discord.Guild):
        league = await self._get_league(guild)
        if league:
            self._league[guild.id] = league
        else:
            log.warning(f"[{guild}] RSC API league has not been configured!")

    async def prepare_api(self, guild: discord.Guild):
        url = await self._get_api_url(guild)
        key = await self._get_api_key(guild)
        if url and key:
            self._api_conf[guild.id] = Configuration(
                host=url,
                api_key={"Api-Key": key},
                api_key_prefix={"Api-Key": "Api-Key"},
            )
        else:
            log.warning(f"[{guild}]RSC API key or url has not been configured!")

    # Autocomplete

    async def timezone_autocomplete(
        self, interaction: discord.Interaction, current: str
    ) -> List[app_commands.Choice[str]]:
        if not current:
            return [
                app_commands.Choice(name=tz, value=tz)
                for tz in pytz.common_timezones[:25]
            ]

        return [
            app_commands.Choice(name=tz, value=tz)
            for tz in pytz.common_timezones
            if current.lower() in tz.lower()
        ]

    # Settings

    rsc_settings = app_commands.Group(
        name="rsc",
        description="RSC API Configuration",
        guild_only=True,
        default_permissions=discord.Permissions(manage_guild=True),
    )

    @rsc_settings.command(name="key", description="Configure the RSC API key.")
    async def _rsc_set_key(self, interaction: discord.Interaction, key: str):
        await self._set_api_key(interaction.guild, key)
        await interaction.response.send_message(
            embed=SuccessEmbed(
                description="RSC API key has been successfully configured.",
            ),
            ephemeral=True,
        )

    @rsc_settings.command(name="url", description="Configure the RSC API web address.")
    async def _rsc_set_url(self, interaction: discord.Interaction, url: str):
        await self._set_api_url(interaction.guild, url)
        await interaction.response.send_message(
            embed=SuccessEmbed(
                description="RSC API url has been successfully configured.",
            ),
            ephemeral=True,
        )

    @rsc_settings.command(
        name="settings", description="Display the current RSC API settings."
    )
    async def _rsc_settings(self, interaction: discord.Interaction):
        key = (
            "Configured"
            if await self._get_api_key(interaction.guild)
            else "Not Configured"
        )
        url = await self._get_api_url(interaction.guild) or "Not Configured"
        league_int = await self._get_league(interaction.guild)
        tz = await self._get_timezone(interaction.guild)

        # Find league name if it is configured/exists
        league = None
        if self._league[interaction.guild_id]:
            league = await self.league(interaction.guild)

        league_str = "Not Configured"
        if league:
            league_str = league.name

        settings_embed = discord.Embed(
            title="RSC API Settings",
            description="Current RSC configuration.",
            color=discord.Color.blue(),
        )
        settings_embed.add_field(name="API Key", value=key, inline=False)
        settings_embed.add_field(name="API URL", value=url, inline=False)
        settings_embed.add_field(name="League", value=league_str, inline=False)
        settings_embed.add_field(name="Time Zone", value=tz, inline=False)
        await interaction.response.send_message(embed=settings_embed, ephemeral=True)

    @rsc_settings.command(
        name="league", description="Set the league this guild correlates to in the API"
    )
    async def _rsc_league(self, interaction: discord.Interaction):
        leagues = await self.leagues(interaction.guild)
        log.debug(leagues)
        league_view = LeagueSelectView(interaction, leagues)
        await league_view.prompt()
        await league_view.wait()

        if league_view.result:
            await self._set_league(interaction.guild, league_view.result)
            league_name = next((x.name for x in leagues if x.id == league_view.result))
            await interaction.edit_original_response(
                embed=SuccessEmbed(
                    description=f"Configured the server league to **{league_name}**"
                ),
            )

    @rsc_settings.command(
        name="setup", description="Perform some basic first time setup for the server"
    )
    async def _rsc_setup(self, interaction: discord.Interaction):
        setup_modal = RSCSetupModal()
        await interaction.response.send_modal(setup_modal)
        await setup_modal.wait()
        setup_modal.stop()

        log.debug("Past modal.")
        if not (setup_modal.url and setup_modal.key):
            await interaction.response.send_message(
                embed=ErrorEmbed(
                    description="You must provide a valid URL and API key."
                ),
                ephemeral=True,
            )
            return

        # Validate URL
        if not validators.url(setup_modal.url.value):
            await interaction.followup.send(
                embed=ErrorEmbed(
                    description=f'The URL provided is invalid: **{setup_modal.url.value}**\n\nDid you remember to include **"https://"**?'
                ),
                ephemeral=True,
            )
            return

        await self._set_api_url(interaction.guild, setup_modal.url.value)
        await self._set_api_key(interaction.guild, setup_modal.key.value)
        await interaction.followup.send(
            embed=SuccessEmbed(
                description="Successfully configured RSC API key and url"
            )
        )

    @rsc_settings.command(
        name="timezone", description="Set the desired time zone for the guild"
    )
    @app_commands.describe(timezone="Common time zone string (Ex: America/New_York)")
    @app_commands.autocomplete(timezone=timezone_autocomplete)
    async def _rsc_timezone(self, interaction: discord.Interaction, timezone: str):
        if timezone not in pytz.common_timezones:
            await interaction.response.send_message(
                embed=ErrorEmbed(
                    description=f"Invalid time zone provided: **{timezone}**"
                ),
                ephemeral=True,
            )
            return

        await self._set_timezone(interaction.guild, timezone)
        await interaction.response.send_message(
            embed=SuccessEmbed(description=f"Time zone set to **{timezone}**"),
            ephemeral=True,
        )

    @rsc_settings.command(
        name="loglevel",
        description="Modify the log level of the bot (Development Feature)",
    )
    async def _rsc_dev_loglevel(
        self, interaction: discord.Interaction, level: LogLevel
    ):
        logging.getLogger("red.rsc").setLevel(level)
        await interaction.response.send_message(
            f"Logging level is now **{level}**", ephemeral=True
        )

    # Functions

    async def timezone(self, guild: discord.Guild) -> ZoneInfo:
        """Returns server timezone as ZoneInfo object for use in datetime objects"""
        return ZoneInfo(await self._get_timezone(guild))

    # Config

    async def _set_api_key(self, guild: discord.Guild, key: str):
        await self.config.guild(guild).ApiKey.set(key)
        if await self._get_api_url(guild):
            await self.prepare_api(guild)

    async def _get_api_key(self, guild: discord.Guild) -> Optional[str]:
        return await self.config.guild(guild).ApiKey()

    async def _set_api_url(self, guild: discord.Guild, url: str):
        await self.config.guild(guild).ApiUrl.set(url)
        if await self._get_api_key(guild):
            await self.prepare_api(guild)

    async def _get_api_url(self, guild: discord.Guild) -> Optional[str]:
        return await self.config.guild(guild).ApiUrl()

    async def _set_league(self, guild: discord.Guild, league: int):
        await self.config.guild(guild).League.set(league)
        self._league[guild.id] = league

    async def _get_league(self, guild: discord.Guild) -> Optional[int]:
        return await self.config.guild(guild).League()

    async def _set_timezone(self, guild: discord.Guild, tz: str):
        await self.config.guild(guild).TimeZone.set(tz)

    async def _get_timezone(self, guild: discord.Guild) -> str:
        """Default: UTC"""
        return await self.config.guild(guild).TimeZone()
