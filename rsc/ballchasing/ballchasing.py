import discord
import logging

from discord import VoiceState

from redbot.core import app_commands, checks, commands, Config

from rscapi.models.tier import Tier

from rsc.abc import RSCMeta
from rsc.const import LEAGUE_ROLE, MUTED_ROLE
from rsc.embeds import ErrorEmbed, SuccessEmbed

from typing import List, Dict, Tuple

log = logging.getLogger("red.rsc.ballchasing")

defaults_guild = {
    "ReplayDumpChannel": None,
    "AuthToken": None,
    "TopLevelGroup": None,
    "TimeZone": "America/New_York",
    "LogChannel": None,
    "StatsManagerRole": None,
    "RscSteamId": None,
    "ScoreReportCategory": None,
}

verify_timeout = 30
BALLCHASING_URL = "https://ballchasing.com"
DONE = "Done"
WHITE_X_REACT = "\U0000274E"  # :negative_squared_cross_mark:
WHITE_CHECK_REACT = "\U00002705"  # :white_check_mark:
RSC_STEAM_ID = 76561199096013422  # RSC Steam ID
# RSC_STEAM_ID = 76561197960409023 # REMOVEME - my steam id for development


class BallchasingMixIn(metaclass=RSCMeta):
    COMBINE_PLAYER_RATIO = 0.5

    def __init__(self):
        log.debug("Initializing BallchasingMixIn")

        self.config: Config
        self.config.init_custom("Ballchasing", 1)
        self.config.register_custom("Ballchasing", **defaults_guild)
        self._ballchasing_api = None
        # self.task = asyncio.create_task(self.pre_load_data())
        # self.ffp = {}  # forfeit processing
        super().__init__()

    # Setup

    # async def prepare_ballchasing_api(self, guild: discord.Guild):

    # Settings
    _ballchasing = app_commands.Group(
        name="ballchasing",
        description="Ballchasing Configuration",
        guild_only=True,
        default_permissions=discord.Permissions(manage_guild=True),
    )

    @_ballchasing.command(
        name="settings",
        description="Display settings for ballchasing replay management",
    )
    async def _bc_settings(self, interaction: discord.Interaction):
        """Show transactions settings"""
        url = BALLCHASING_URL
        token = (
            "Configured"
            if await self._get_bc_auth_token(interaction.guild)
            else "Not Configured"
        )
        log_channel = await self._get_bc_log_channel(interaction.guild)
        tz = await self._get_time_zone(interaction.guild)
        score_category = await self._get_score_reporting_category(interaction.guild)

        embed = discord.Embed(
            title="Ballchasing Settings",
            description="Current configuration for Ballchasing replay management",
            color=discord.Color.blue(),
        )

        embed.add_field(name="Ballchasing URL", value=url, inline=False)
        embed.add_field(name="Ballchasing API Token", value=token, inline=False)
        embed.add_field(
            name="Log Channel",
            value=log_channel.mention if log_channel else "None",
            inline=False,
        )
        embed.add_field(
            name="Score Reporting Category",
            value=score_category.mention if score_category else "None",
            inline=False,
        )

        await interaction.response.send_message(embed=embed, ephemeral=True)

    # Config

    async def _get_bc_auth_token(self, guild: discord.Guild):
        return await self.config.custom("Ballchasing", guild.id).AuthToken()

    async def _save_bc_auth_token(self, guild: discord.Guild, token):
        await self.config.custom("Ballchasing", guild.id).AuthToken.set(token)

    # async def _save_top_level_group(self, guild: discord.Guild, group_id):
    #     await self.config.custom("Ballchasing", guild.id).TopLevelGroup.set(group_id)

    # async def _get_top_level_group(self, guild: discord.Guild):
    #     return await self.config.custom("Ballchasing", guild.id).TopLevelGroup()

    async def _save_time_zone(self, guild, time_zone):
        await self.config.custom("Ballchasing", guild.id).TimeZone.set(time_zone)

    async def _get_time_zone(self, guild):
        return await self.config.custom("Ballchasing", guild.id).TimeZone()

    async def _get_bc_log_channel(self, guild: discord.Guild):
        return guild.get_channel(
            await self.config.custom("Ballchasing", guild.id).LogChannel()
        )

    async def _save_bc_log_channel(
        self, guild: discord.Guild, channel: discord.TextChannel
    ):
        await self.config.custom("Ballchasing", guild.id).LogChannel.set(channel.id)

    async def _get_stats_manager_role(self, guild: discord.Guild):
        return guild.get_role(
            await self.config.custom("Ballchasing", guild.id).StatsManagerRole()
        )

    async def _save_stats_manager_role(self, guild: discord.Guild, role: discord.Role):
        await self.config.custom("Ballchasing", guild.id).StatsManagerRole.set(role.id)

    async def _save_score_reporting_category(
        self, guild, category: discord.CategoryChannel
    ):
        await self.config.custom("Ballchasing", guild.id).ScoreReportCategory.set(
            category.id
        )

    async def _get_score_reporting_category(self, guild):
        return await self.config.custom("Ballchasing", guild.id).ScoreReportCategory()
