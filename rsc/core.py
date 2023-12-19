import discord
import logging
import asyncio
import validators
import itertools
from aiohttp import ClientConnectionError

import pytz
from zoneinfo import ZoneInfo

from redbot.core import Config, app_commands, commands, checks

from rscapi import Configuration

# Types
from rsc.abc import CompositeMetaClass
from rsc.enums import LogLevel

# Mix Ins
from rsc.admin import AdminMixIn
from rsc.ballchasing import BallchasingMixIn
from rsc.combines import CombineMixIn
from rsc.freeagents import FreeAgentMixIn
from rsc.franchises import FranchiseMixIn
from rsc.matches import MatchMixIn
from rsc.members import MemberMixIn
from rsc.moderator import ModeratorMixIn, ThreadMixIn
from rsc.numbers import NumberMixIn
from rsc.leagues import LeagueMixIn
from rsc.ranks import RankMixIn
from rsc.ranks.api import RapidApi
from rsc.teams import TeamMixIn
from rsc.tiers import TierMixIn
from rsc.trackers import TrackerMixIn
from rsc.transactions import TransactionMixIn
from rsc.utils import UtilsMixIn
from rsc.welcome import WelcomeMixIn

# Views
from rsc.views import LeagueSelectView, RSCSetupModal

# Util
from rsc.embeds import SuccessEmbed, ErrorEmbed, BlueEmbed

from typing import Optional, Dict, List, Union, TYPE_CHECKING

log = logging.getLogger("red.rsc.core")

HIDDEN_COMMANDS = ["feet"]

defaults_guild = {
    "ApiKey": None,
    "ApiUrl": None,
    "League": None,
    "RapidApi": None,
    "TimeZone": "UTC",
}


class RSC(
    AdminMixIn,
    BallchasingMixIn,
    CombineMixIn,
    FranchiseMixIn,
    LeagueMixIn,
    FreeAgentMixIn,
    MemberMixIn,
    MatchMixIn,
    ModeratorMixIn,
    NumberMixIn,
    RankMixIn,
    TeamMixIn,
    TierMixIn,
    ThreadMixIn,
    TrackerMixIn,
    TransactionMixIn,
    UtilsMixIn,
    WelcomeMixIn,
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
        self._api_conf: dict[int, Configuration] = {}
        self.rapid_api: dict[int, RapidApi] = {}
        # Cache the league associated with each guild
        self._league: dict[int, int] = {}

        super().__init__()
        log.info("RSC Bot has been started.")

    # Setup

    async def cog_load(self):
        """Perform initial bot setup on Cog reload"""
        log.debug("In cog_load()")
        await self.setup()

    async def cog_unload(self):
        """Cancel task loops on unload to avoid multiple tasks"""
        log.info("Cancelling task loops due to cog_unload()")
        self.expire_sub_contract_loop.cancel()
        self.expire_free_agent_checkins_loop.cancel()
        await self.close_ballchasing_sessions()

    async def setup(self):
        """Prepare the bot API and caches. Requires API configuration"""
        log.info("Preparing API connector and local caches")
        for guild in self.bot.guilds:
            log.debug(f"[{guild}] Preparing RSC API configuration")
            await self.prepare_api(guild)

            log.debug(f"[{guild}] Preparing RapidAPI connector")
            await self.prepare_rapidapi(guild)

            if self._api_conf.get(guild.id):
                await self.prepare_league(guild)
                log.debug(f"[{guild}] Preparing caches")
                try:
                    async with asyncio.TaskGroup() as tg:
                        tg.create_task(self.tiers(guild))
                        tg.create_task(self.franchises(guild))
                        tg.create_task(self.teams(guild))
                        tg.create_task(self._populate_combines_cache(guild))
                        tg.create_task(self._populate_free_agent_cache(guild))
                        tg.create_task(self.prepare_ballchasing(guild))
                except ExceptionGroup as eg:
                    for err in eg.exceptions:
                        raise err

    async def prepare_rapidapi(self, guild: discord.Guild):
        token = await self._get_rapidapi_key(guild)
        if token:
            self.rapid_api[guild.id] = RapidApi(token=token)

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

    # Listeners

    @commands.Cog.listener()
    async def on_ready(self):
        """
        Perform initial bot setup on ready. This event ensures we are connected to guilds first.

        Does NOT trigger on Cog reload.
        """
        log.debug("In on_ready()")
        await self.setup()

    # Autocomplete

    async def command_autocomplete(
        self, interaction: discord.Interaction, current: str
    ) -> list[app_commands.Choice[str]]:
        cmds = self.walk_app_commands()
        if not cmds:
            return []

        if not current:
            return [
                app_commands.Choice(name=c.qualified_name, value=c.qualified_name)
                for c in itertools.islice(cmds, 25) if c not in HIDDEN_COMMANDS
            ]

        choices = []
        for c in cmds:
            if (
                c.default_permissions
                and (interaction.user.guild_permissions & c.default_permissions).value
                == 0
            ):
                continue
            elif current.lower() in c.qualified_name.lower() and c.name not in HIDDEN_COMMANDS:
                choices.append(
                    app_commands.Choice(name=c.qualified_name, value=c.qualified_name)
                )
            if len(choices) == 25:
                return choices
        return choices

    async def timezone_autocomplete(
        self, interaction: discord.Interaction, current: str
    ) -> list[app_commands.Choice[str]]:
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
        tz = await self._get_timezone(interaction.guild)
        rapid_api_key = (
            "Configured"
            if await self._get_rapidapi_key(interaction.guild)
            else "Not Configured"
        )

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
        settings_embed.add_field(name="RapidAPI Key", value=rapid_api_key, inline=False)
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


    @rsc_settings.command(
        name="rapidapikey",
        description="Configure the guild RapidAPI key",
    )
    async def _rsc_set_rapidapi(
        self, interaction: discord.Interaction, key: str
    ):
        await self._set_rapidapi_key(interaction.guild, key)
        await interaction.response.send_message(
            embed=SuccessEmbed(description=f"RapidAPI key has been configured."),
            ephemeral=True
        )

    # Non-Group Commands


    @app_commands.command(
        name="whatami", description="What am I?"
    )
    async def _whatami(self, interaction: discord.Interaction):
        embed = BlueEmbed(
            title="What Am I?",
            description="I am a discord bot created to operate Rocket Soccar Confederation (RSC) discord servers.\n\nI was designed and written by **nickm**."
        )
        await interaction.response.send_message(embed=embed)

    @app_commands.command(
        name="help", description="Display a help for RSC Bot or a specific command."
    )
    @app_commands.describe(command="Display help for a specific command.")
    @app_commands.autocomplete(command=command_autocomplete)
    @app_commands.guild_only()
    async def _help_cmd(self, interaction: discord.Interaction, command: str | None):
        cmds = self.get_app_commands()
        if not command:
            embeds = []
            groups: list[discord.app_commands.Group] = []
            cmd_list: list[discord.app_commands.Command] = []
            for cmd in cmds:
                if (
                    cmd.default_permissions
                    and (
                        interaction.user.guild_permissions & cmd.default_permissions
                    ).value
                    == 0
                ):
                    log.debug(f"Insufficient Perms for help: {cmd.name}")
                    continue

                # super secret tech
                if cmd.name.lower() == "feet":
                    continue

                # Custom role permission validation
                if cmd.name.lower() == "ballchasing":
                    stats_role = await self._get_bc_manager_role(interaction.guild)
                    if (
                        stats_role and stats_role in interaction.user.roles
                    ) or interaction.user.guild_permissions.manage_guild:
                        groups.append(cmd)
                    continue

                if isinstance(cmd, discord.app_commands.Group):
                    groups.append(cmd)
                else:
                    cmd_list.append(cmd)

            groups.sort(key=lambda x: x.name)
            cmd_list.sort(key=lambda x: x.name)

            # Build Group Embeds
            group_desc = "List of group commands available to you.\n\n"
            gembed = BlueEmbed(title=f"RSC Command Groups")
            for g in groups:
                group_desc += f"**/{g.name}** - {g.description}\n"
            gembed.description = group_desc
            embeds.append(gembed)

            # Build Non-Group Command Embeds
            cmd_desc = "List of individual commands available to you.\n\n"
            cmdembed = BlueEmbed(title="RSC Non-Group Commands")
            for c in cmd_list:
                cmd_desc += f"**/{c.name}** - {c.description}\n"
            cmdembed.description = cmd_desc

            if interaction.guild.icon:
                gembed.set_thumbnail(url=interaction.guild.icon.url)
                cmdembed.set_thumbnail(url=interaction.guild.icon.url)
            embeds.append(cmdembed)

            await interaction.response.send_message(embeds=embeds, ephemeral=True)
        else:
            cmd = None
            for c in self.walk_app_commands():
                if c.name == "feet":
                    continue
                if c.qualified_name == command:
                    log.debug(f"Qualified Name: {c.qualified_name}")
                    cmd = c

            if not cmd:
                await interaction.response.send_message(
                    f"**{command}** is not a valid command name.", ephemeral=True
                )
                return

            desc = ""
            embed = BlueEmbed()
            if isinstance(cmd, discord.app_commands.Group):
                embed.title = f"{cmd.qualified_name.title()} Command Group Help"
                for c in cmd.walk_commands():
                    desc += f"**/{c.qualified_name}** - {c.description}\n"
            else:
                embed.title = f"{cmd.qualified_name.title()} Command Help"
                desc = (
                    f"**Command:** /{cmd.qualified_name}\n"
                    f"**Description:** {cmd.description}\n"
                )
                if cmd.parameters:
                    desc += "\n__**Parameters**__\n\n"
                    for p in cmd.parameters:
                        desc += f"**{p.name}** - {p.description}\n"
            embed.description = desc

            if interaction.guild.icon:
                embed.set_thumbnail(url=interaction.guild.icon.url)

            await interaction.response.send_message(embed=embed)

    # Functions

    async def timezone(self, guild: discord.Guild) -> ZoneInfo:
        """Returns server timezone as ZoneInfo object for use in datetime objects"""
        return ZoneInfo(await self._get_timezone(guild))

    async def rapid_connector(self, guild: discord.Guild) -> Optional[RapidApi]:
        """Returns server timezone as ZoneInfo object for use in datetime objects"""
        return self.rapid_api.get(guild.id, None)

    # Config

    async def _set_api_key(self, guild: discord.Guild, key: str):
        await self.config.guild(guild).ApiKey.set(key)
        if await self._get_api_url(guild):
            await self.prepare_api(guild)

    async def _get_api_key(self, guild: discord.Guild) -> str | None:
        return await self.config.guild(guild).ApiKey()

    async def _set_api_url(self, guild: discord.Guild, url: str):
        await self.config.guild(guild).ApiUrl.set(url)
        if await self._get_api_key(guild):
            await self.prepare_api(guild)

    async def _get_api_url(self, guild: discord.Guild) -> str | None:
        return await self.config.guild(guild).ApiUrl()

    async def _set_league(self, guild: discord.Guild, league: int):
        await self.config.guild(guild).League.set(league)
        self._league[guild.id] = league

    async def _get_league(self, guild: discord.Guild) -> int | None:
        return await self.config.guild(guild).League()

    async def _set_timezone(self, guild: discord.Guild, tz: str):
        await self.config.guild(guild).TimeZone.set(tz)

    async def _get_timezone(self, guild: discord.Guild) -> str:
        """Default: UTC"""
        return await self.config.guild(guild).TimeZone()

    async def _set_rapidapi_key(self, guild: discord.Guild, key: str):
        self.rapid_api[guild.id] = RapidApi(token=key)
        await self.config.guild(guild).RapidApi.set(key)

    async def _get_rapidapi_key(self, guild: discord.Guild) -> str | None:
        return await self.config.guild(guild).RapidApi()
