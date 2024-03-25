import logging

import discord
from aiohttp.client_exceptions import ClientConnectionError
from redbot.core import app_commands

from rsc.abc import RSCMixIn
from rsc.devleague import api
from rsc.embeds import BlueEmbed, ErrorEmbed, OrangeEmbed, SuccessEmbed

log = logging.getLogger("red.rsc.devleague")

BUFMAX = 1984


class DevLeagueMixIn(RSCMixIn):
    def __init__(self):
        log.debug("Initializing DevLeagueMixIn")
        super().__init__()

    # Groups

    _dev_league = app_commands.Group(
        name="devleague",
        description="RSC Dev league commands",
        guild_only=True,
    )

    # Commands

    @_dev_league.command(  # type: ignore
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
        except ClientConnectionError:
            return await interaction.followup.send(
                embed=ErrorEmbed(description="Error connecting to dev league API")
            )

        if result.error:
            return await interaction.followup.send(
                embed=ErrorEmbed(description=result.error), ephemeral=True
            )

        status_fmt = "**checked in**" if result.checked_in else "**not checked in**"

        embed = BlueEmbed(
            title="Dev League Status",
            description=f"You are currently {status_fmt} for dev league!",
        )

        embed.add_field(name="Name", value=str(result.player), inline=True)
        embed.add_field(name="Tier", value=str(result.tier), inline=True)

        await interaction.followup.send(embed=embed)

    @_dev_league.command(  # type: ignore
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
        except ClientConnectionError:
            return await interaction.followup.send(
                embed=ErrorEmbed(description="Error connecting to dev league API")
            )

        if result.error:
            return await interaction.followup.send(
                embed=ErrorEmbed(description=result.error), ephemeral=True
            )

        embed = SuccessEmbed(
            title="Checked In",
            description="You are now **checked in** for dev league!",
        )
        await interaction.followup.send(embed=embed)

    @_dev_league.command(  # type: ignore
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
        except ClientConnectionError:
            return await interaction.followup.send(
                embed=ErrorEmbed(description="Error connecting to dev league API")
            )

        if result.error:
            return await interaction.followup.send(
                embed=ErrorEmbed(description=result.error), ephemeral=True
            )

        embed = OrangeEmbed(
            title="Checked Out",
            description="You are now **checked out** for dev league!",
        )
        await interaction.followup.send(embed=embed)
