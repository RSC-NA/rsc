import discord
import logging
import pytz
from datetime import datetime, timedelta

from discord import VoiceState
from discord.app_commands import Choice, Transform

from redbot.core import app_commands, checks, commands, Config

from rscapi.models.tier import Tier
from rscapi.models.match import Match

from rsc.abc import RSCMixIn
from rsc.const import LEAGUE_ROLE, MUTED_ROLE
from rsc.embeds import ErrorEmbed, SuccessEmbed
from rsc.teams import TeamMixIn
from rsc.transformers import DateTransformer

from typing import List, Dict, Tuple, Optional

log = logging.getLogger("red.rsc.ballchasing")

defaults_guild = {
    "AuthToken": None,
    "TopLevelGroup": None,
    "LogChannel": None,
    "ManagerRole": None,
    "RscSteamId": None,
    "ReportCategory": None,
}

verify_timeout = 30
BALLCHASING_URL = "https://ballchasing.com"
DONE = "Done"
WHITE_X_REACT = "\U0000274E"  # :negative_squared_cross_mark:
WHITE_CHECK_REACT = "\U00002705"  # :white_check_mark:
# RSC_STEAM_ID = 76561199096013422  # RSC Steam ID
RSC_STEAM_ID = 76561197960409023 # REMOVEME - my steam id for development


class BallchasingMixIn(RSCMixIn):
    COMBINE_PLAYER_RATIO = 0.5

    def __init__(self):
        log.debug("Initializing BallchasingMixIn")

        self.config.init_custom("Ballchasing", 1)
        self.config.register_custom("Ballchasing", **defaults_guild)
        self._ballchasing_api = {}
        # self.task = asyncio.create_task(self.pre_load_data())
        # self.ffp = {}  # forfeit processing
        super().__init__()

    # Setup

    # async def prepare_ballchasing_api(self, guild: discord.Guild):

    # Settings
    _ballchasing: app_commands.Group = app_commands.Group(
        name="ballchasing",
        description="Ballchasing commands and configuration",
        guild_only=True,
    )

    @_ballchasing.command(
        name="settings",
        description="Display settings for ballchasing replay management",
    )
    @app_commands.checks.has_permissions(manage_guild=True)
    async def _bc_settings(self, interaction: discord.Interaction):
        """Show transactions settings"""
        url = BALLCHASING_URL
        token = (
            "Configured"
            if await self._get_bc_auth_token(interaction.guild)
            else "Not Configured"
        )
        log_channel = await self._get_bc_log_channel(interaction.guild)
        tz = await self.timezone(interaction.guild)
        score_category = await self._get_score_reporting_category(interaction.guild)
        role = await self._get_bc_manager_role(interaction.guild)

        embed = discord.Embed(
            title="Ballchasing Settings",
            description="Current configuration for Ballchasing replay management",
            color=discord.Color.blue(),
        )

        embed.add_field(name="Ballchasing URL", value=url, inline=False)
        embed.add_field(name="Ballchasing API Token", value=token, inline=False)
        embed.add_field(
            name="Management Role", value=role.mention if role else "None", inline=False
        )
        embed.add_field(
            name="Log Channel",
            value=log_channel.mention if log_channel else "None",
            inline=False,
        )
        embed.add_field(
            name="Report Category",
            value=score_category,
            inline=False,
        )
        embed.add_field(name="Time Zone", value=str(tz), inline=False)

        await interaction.response.send_message(embed=embed, ephemeral=True)

    @_ballchasing.command(
        name="key", description="Configure the Ballchasing API key for the server"
    )
    @app_commands.checks.has_permissions(manage_guild=True)
    async def _bc_key(self, interaction: discord.Interaction, key: str):
        await self._save_bc_auth_token(interaction.guild, key)
        await interaction.response.send_message(
            embed=SuccessEmbed(
                description="Ballchasing API key have been successfully configured"
            ),
            ephemeral=True,
        )

    @_ballchasing.command(
        name="manager",
        description="Configure the ballchasing management role (Ex: @Stats Committee)",
    )
    @app_commands.checks.has_permissions(manage_guild=True)
    async def _bc_management_role(
        self, interaction: discord.Interaction, role: discord.Role
    ):
        await self._save_bc_manager_role(interaction.guild, role)
        await interaction.response.send_message(
            embed=SuccessEmbed(
                description=f"Ballchasing management role set to {role.mention}"
            ),
            ephemeral=True,
        )

    @_ballchasing.command(
        name="log",
        description="Configure the logging channel for Ballchasing commands (Ex: #stats-committee)",
    )
    @app_commands.checks.has_permissions(manage_guild=True)
    async def _bc_log_channel(
        self, interaction: discord.Interaction, channel: discord.TextChannel
    ):
        await self._save_bc_log_channel(interaction.guild, channel)
        await interaction.response.send_message(
            embed=SuccessEmbed(
                description=f"Ballchasing log channel set to {channel.mention}"
            ),
            ephemeral=True,
        )

    @_ballchasing.command(
        name="category",
        description="Configure the score reporting category for the server",
    )
    @app_commands.checks.has_permissions(manage_guild=True)
    async def _bc_score_category(
        self, interaction: discord.Interaction, category: discord.CategoryChannel
    ):
        await self._save_score_reporting_category(interaction.guild, category)
        await interaction.response.send_message(
            embed=SuccessEmbed(
                description=f"Score reporting category set to **{category.name}**"
            ),
            ephemeral=True,
        )

    # Commands

    @_ballchasing.command(
        name="reportall",
        description="Find and report all matches for the day on ballchasing",
    )
    async def _bc_reportall(self, interaction: discord.Interaction):
        if not await self.has_bc_permissions(interaction.user):
            await interaction.response.send_message(
                "You do not have permission to run this command.", ephemeral=True
            )
            return

        # Check if league match day (Ex: Mon/Wed)
        # if not self.is_match_day(interaction.guild):
        #     #TODO

        # Todays Date
        tz = await self.timezone(interaction.guild)
        # dt_today = datetime.now(tz).date()
        dt_today = datetime(2023, 9, 1, tzinfo=tz)  # Dev TEST TIME
        log.info(f"Reporting all matches on {dt_today}")
        # TODO

    @_ballchasing.command(
        name="reportmatch",
        description="Report a specific match on ballchasing",
    )
    @app_commands.autocomplete(
        home=TeamMixIn.teams_autocomplete, away=TeamMixIn.teams_autocomplete
    )
    @app_commands.describe(
        home="Home team name",
        away="Away team name",
        date='Match date in ISO 8601 format. Defaults to todays date. (Example: "2023-01-25")',
    )
    async def _bc_reportmatch(
        self,
        interaction: discord.Interaction,
        home: str,
        away: str,
        date: Optional[Transform[datetime, DateTransformer]] = None,
    ):
        if not await self.has_bc_permissions(interaction.user):
            await interaction.response.send_message(
                "You do not have permission to run this command.", ephemeral=True
            )
            return

        # Get guild timezone
        tz = await self.timezone(interaction.guild)

        # Add timezone to date. If date not supplied, use todays date()
        if date:
            date = date.replace(tzinfo=tz)
        else:
            date = datetime.now(tz=tz).replace(
                hour=0, minute=0, second=0, microsecond=0
            )

        date = datetime(2023, 9, 1, tzinfo=tz)  # PRESEASON TEST REMOVE ME
        log.info(f"Reporting individual match. Home: {home} Away: {away} Date: {date}")

        # Get match by teams and date
        date_gt, date_lt = await self.get_date_search_range(date)
        matches = await self.matches(
            interaction.guild,
            date__lt=date_lt,
            date__gt=date_gt,
            home_team=home,
            away_team=away,
        )

        # No match found
        if not matches:
            await interaction.response.send_message(
                embed=ErrorEmbed(
                    description="No matches found for specified teams and date."
                )
            )
            return

        # Teams should only play once on the day
        if len(matches) > 1:
            log.error(
                f"Found more than one match result. Home: {home} Away: {away} Date: {date}"
            )
            await interaction.response.send_message(
                embed=ErrorEmbed(
                    description="Found more than one match result for criteria\n\n"
                    f"Home: {home}\n"
                    f"Away: {away}\n"
                    f"Date: {date}"
                )
            )
            return

        # Check if away team matches
        # TODO

        # Send "working" message
        await interaction.response.send_message(
            embed=discord.Embed(
                title="Processing Match",
                description=f"Searching ballchasing for match **{home}** vs **{away}**",
                color=discord.Color.yellow(),
            )
        )

        # Get detailed information for match
        match = await self.match_by_id(interaction.guild, matches[0].id)
        log.debug(match)

        result = await self.bc_report_match(match)

        # TODO display results

    # Functions

    async def bc_report_match(self, match: Match):
        pass

    async def get_date_search_range(self, date: datetime) -> Tuple[datetime, datetime]:
        """Return a tuple of datetime objects that has a search range for specified date"""
        date_gt = date - timedelta(minutes=1)
        date_lt = date.replace(hour=23, minute=59, second=59)
        return (date_gt, date_lt)

    async def has_bc_permissions(self, member: discord.Member) -> bool:
        """Determine if member is able to manage guild or part of manager role"""
        # Guild Manager
        if member.guild_permissions.manage_guild:
            return True

        # BC Manager Role
        manager_role = await self._get_bc_manager_role(member.guild)
        if manager_role in member.roles:
            return True
        return False

    # Config

    async def _get_bc_auth_token(self, guild: discord.Guild):
        return await self.config.custom("Ballchasing", guild.id).AuthToken()

    async def _save_bc_auth_token(self, guild: discord.Guild, key: str):
        await self.config.custom("Ballchasing", guild.id).AuthToken.set(key)

    # async def _save_top_level_group(self, guild: discord.Guild, group_id):
    #     await self.config.custom("Ballchasing", guild.id).TopLevelGroup.set(group_id)

    # async def _get_top_level_group(self, guild: discord.Guild):
    #     return await self.config.custom("Ballchasing", guild.id).TopLevelGroup()

    async def _get_bc_log_channel(self, guild: discord.Guild):
        return guild.get_channel(
            await self.config.custom("Ballchasing", guild.id).LogChannel()
        )

    async def _save_bc_log_channel(
        self, guild: discord.Guild, channel: discord.TextChannel
    ):
        await self.config.custom("Ballchasing", guild.id).LogChannel.set(channel.id)

    async def _get_bc_manager_role(self, guild: discord.Guild):
        return guild.get_role(
            await self.config.custom("Ballchasing", guild.id).ManagerRole()
        )

    async def _save_bc_manager_role(self, guild: discord.Guild, role: discord.Role):
        await self.config.custom("Ballchasing", guild.id).ManagerRole.set(role.id)

    async def _save_score_reporting_category(
        self, guild, category: discord.CategoryChannel
    ):
        await self.config.custom("Ballchasing", guild.id).ReportCategory.set(
            category.id
        )

    async def _get_score_reporting_category(self, guild):
        return guild.get_channel(
            await self.config.custom("Ballchasing", guild.id).ReportCategory()
        )
