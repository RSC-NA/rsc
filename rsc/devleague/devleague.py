import logging

import discord
from aiohttp.client_exceptions import ClientConnectionError
from redbot.core import app_commands

from rsc.abc import RSCMixIn
from rsc.devleague import api
from rsc.embeds import BlueEmbed, ErrorEmbed, OrangeEmbed, SuccessEmbed
from rsc.utils import utils

log = logging.getLogger("red.rsc.devleague")

defaults_guild = {"DevLeagueRoleUsers": None}

BUFMAX = 1984


class DevLeagueMixIn(RSCMixIn):
    def __init__(self):
        log.debug("Initializing DevLeagueMixIn")

        self.config.init_custom("DevLeague", 1)
        self.config.register_custom("DevLeague", **defaults_guild)
        super().__init__()

    # Groups

    _dev_league = app_commands.Group(
        name="devleague",
        description="RSC Dev league commands",
        guild_only=True,
    )

    # Commands

    @_dev_league.command(
        name="status",
        description="Check your status for Dev League",
    )
    @app_commands.guild_only
    async def dev_league_status_cmd(
        self,
        interaction: discord.Interaction,
    ):
        if not interaction.guild:
            return

        if not isinstance(interaction.user, discord.Member):
            return

        await interaction.response.defer(ephemeral=True)
        try:
            result = await api.dev_league_status(interaction.user)
        except ClientConnectionError as exc:
            await interaction.followup.send(embed=ErrorEmbed(description="Error connecting to dev league API"))
            raise exc

        if result.error:
            return await interaction.followup.send(embed=ErrorEmbed(description=result.error), ephemeral=True)

        status_fmt = "**checked in**" if result.checked_in else "**not checked in**"

        embed = BlueEmbed(
            title="Dev League Status",
            description=f"You are currently {status_fmt} for dev league!",
        )

        embed.add_field(name="Name", value=str(result.player), inline=True)
        embed.add_field(name="Tier", value=str(result.tier), inline=True)

        await interaction.followup.send(embed=embed)

    @_dev_league.command(
        name="checkin",
        description="Check in for dev league",
    )
    @app_commands.guild_only
    async def dev_league_checkin_cmd(
        self,
        interaction: discord.Interaction,
    ):
        if not interaction.guild:
            return

        if not isinstance(interaction.user, discord.Member):
            return

        await interaction.response.defer(ephemeral=True)
        try:
            result = await api.dev_league_check_in(interaction.user)
        except ClientConnectionError as exc:
            await interaction.followup.send(embed=ErrorEmbed(description="Error connecting to dev league API"))
            raise exc

        if result.error:
            return await interaction.followup.send(embed=ErrorEmbed(description=result.error), ephemeral=True)

        embed = SuccessEmbed(
            title="Checked In",
            description="You are now **checked in** for dev league!",
        )
        await interaction.followup.send(embed=embed)

    @_dev_league.command(
        name="checkout",
        description="Check out of dev league",
    )
    @app_commands.guild_only
    async def dev_league_checkout_cmd(
        self,
        interaction: discord.Interaction,
    ):
        if not interaction.guild:
            return

        if not isinstance(interaction.user, discord.Member):
            return

        await interaction.response.defer(ephemeral=True)

        try:
            result = await api.dev_league_check_out(interaction.user)
        except ClientConnectionError as exc:
            await interaction.followup.send(embed=ErrorEmbed(description="Error connecting to dev league API"))
            raise exc

        if result.error:
            return await interaction.followup.send(embed=ErrorEmbed(description=result.error), ephemeral=True)

        embed = OrangeEmbed(
            title="Checked Out",
            description="You are now **checked out** for dev league!",
        )
        await interaction.followup.send(embed=embed)

    @_dev_league.command(
        name="optout",
        description="Opt out of dev league (role will be removed)",
    )
    @app_commands.guild_only
    async def dev_league_optout_cmd(
        self,
        interaction: discord.Interaction,
    ):
        if not interaction.guild:
            return

        if not isinstance(interaction.user, discord.Member):
            return

        await self.remove_devleague_role(interaction.user)

        embed = SuccessEmbed(
            title="Opted Out",
            description="You are now **opted out** of Dev League notifications.",
        )
        await interaction.response.send_message(embed=embed, ephemeral=True)

    @_dev_league.command(
        name="optin",  # codespell:ignore optin
        description="Opt in to dev league (role will be added)",
    )
    @app_commands.guild_only
    async def dev_league_optin_cmd(
        self,
        interaction: discord.Interaction,
    ):
        if not interaction.guild:
            return

        if not isinstance(interaction.user, discord.Member):
            return

        await self.add_devleague_role(interaction.user)

        embed = SuccessEmbed(
            title="Opted In",
            description="You are now **opted in** to Dev League notifications.",
        )
        await interaction.response.send_message(embed=embed, ephemeral=True)

    # region Helper Functions

    async def add_devleague_role(self, member: discord.Member):
        devleague_role = await utils.get_devleague_role(member.guild)

        if devleague_role not in member.roles:
            await member.add_roles(devleague_role, reason="Player opted in to Dev League")

        users = await self._get_devleague_role_users(member.guild) or []
        if member.id not in users:
            users.append(member.id)
            await self._save_devleague_role_users(member.guild, value=users)

    async def remove_devleague_role(self, member: discord.Member):
        """Remove Dev League role but keep in users list so they don't get it again automatically"""
        devleague_role = await utils.get_devleague_role(member.guild)

        if devleague_role in member.roles:
            await member.remove_roles(devleague_role, reason="Player opted out of Dev League")

    async def should_get_devleague_role(self, member: discord.Member) -> bool:
        users = await self._get_devleague_role_users(member.guild) or []
        return member.id not in users

    # region Config

    async def _save_devleague_role_users(self, guild: discord.Guild, value: list[int]):
        await self.config.custom("DevLeague", str(guild.id)).DevLeagueRoleUsers.set(value)

    async def _get_devleague_role_users(self, guild: discord.Guild):
        return await self.config.custom("DevLeague", str(guild.id)).DevLeagueRoleUsers()
