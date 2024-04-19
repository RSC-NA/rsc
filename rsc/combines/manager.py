import logging
import re
from pathlib import Path
from typing import MutableMapping

import discord
from redbot.core import app_commands

from rsc.abc import RSCMixIn
from rsc.const import (
    COMBINES_HELP_1,
    COMBINES_HELP_2,
    COMBINES_HELP_3,
    COMBINES_HOW_TO_PLAY_1,
    COMBINES_HOW_TO_PLAY_2,
    COMBINES_HOW_TO_PLAY_3,
    COMBINES_HOW_TO_PLAY_4,
    COMBINES_HOW_TO_PLAY_5,
    MUTED_ROLE,
)
from rsc.embeds import BlueEmbed, ErrorEmbed, GreenEmbed
from rsc.types import CombineSettings
from rsc.utils import utils

log = logging.getLogger("red.rsc.combines.manager")

defaults_guild = CombineSettings(
    Active=False,
    CombinesApi=None,
    CombinesCategory=None,
)


class CombineManagerMixIn(RSCMixIn):
    def __init__(self):
        log.debug("Initializing CombineMixIn:Manager")
        self.config.init_custom("Combines", 1)
        self.config.register_custom("Combines", **defaults_guild)
        super().__init__()

    # Settings

    _combine_manager = app_commands.Group(
        name="combinemanager",
        description="Manage combines",
        guild_only=True,
        default_permissions=discord.Permissions(manage_guild=True),
    )

    # Privileged Commands

    @_combine_manager.command(name="settings", description="Display combine settings")  # type: ignore
    async def _combines_settings_cmd(self, interaction: discord.Interaction):
        guild = interaction.guild
        if not guild:
            return

        active = await self._get_combines_active(guild)
        api_url = await self._get_combines_api(guild)
        category = await self._get_combines_category(guild)

        embed = BlueEmbed(
            title="Combine Settings",
            description="Current configuration for Combines Cog",
        )
        embed.add_field(name="Combines Active", value=active, inline=False)
        embed.add_field(name="Combines API", value=api_url, inline=False)
        embed.add_field(
            name="Combines Category",
            value=category.mention if category else "None",
            inline=False,
        )
        await interaction.response.send_message(embed=embed, ephemeral=True)

    @_combine_manager.command(name="category", description="Configure the combines category channel")  # type: ignore
    @app_commands.describe(category="Combines Category Channel")
    async def _combines_category_cmd(
        self, interaction: discord.Interaction, category: discord.CategoryChannel
    ):
        guild = interaction.guild
        if not guild:
            return

        await self._set_combines_category(guild, category)
        await interaction.response.send_message(
            embed=GreenEmbed(
                title="Combines Category",
                description=f"Combines category has been configured: {category.mention}",
            ),
            ephemeral=True,
        )

    @_combine_manager.command(name="api", description="Configure the API url for combines")  # type: ignore
    @app_commands.describe(
        url="Combines API location (Ex: https://devleague.rscna.com/c-api/)"
    )
    async def _combines_api_cmd(self, interaction: discord.Interaction, url: str):
        guild = interaction.guild
        if not guild:
            return

        await self._set_combines_api(guild, url)
        await interaction.response.send_message(
            embed=GreenEmbed(
                title="Combines API",
                description=f"Combines API location has been configured: {url}",
            ),
            ephemeral=True,
        )

    @_combine_manager.command(  # type: ignore
        name="start", description="Begin RSC combines and create channels"
    )
    async def _combines_start(self, interaction: discord.Interaction):
        guild = interaction.guild
        if not guild:
            return

        status = await self._get_combines_active(guild)
        if status:
            return await interaction.response.send_message(
                embed=ErrorEmbed(description="Combines are already active!")
            )

        api = await self._get_combines_api(guild)
        category = await self._get_combines_category(guild)

        if not api:
            return await interaction.response.send_message(
                embed=ErrorEmbed(description="Combines API has not been configured!")
            )
        if not category:
            return await interaction.response.send_message(
                embed=ErrorEmbed(
                    description="Combines category channel has not been configured!"
                )
            )

        await interaction.response.defer(ephemeral=True)

        # Get required role references
        league_role = await utils.get_league_role(guild)
        muted_role = discord.utils.get(guild.roles, name=MUTED_ROLE)
        admin_role = discord.utils.get(guild.roles, name="Admin")
        log.debug(f"[{guild}] Default Role: {guild.default_role}")

        if not league_role:
            return await interaction.followup.send(
                embed=ErrorEmbed(description="League role does not exist.")
            )

        if not admin_role:
            return await interaction.followup.send(
                embed=ErrorEmbed(description="Admin role does not exist.")
            )

        # Admin only overwrites
        admin_overwrites: MutableMapping[
            discord.Member | discord.Role, discord.PermissionOverwrite
        ] = {
            guild.default_role: discord.PermissionOverwrite(
                view_channel=True,
                connect=False,
                speak=False,
                send_messages=False,
                add_reactions=False,
            ),
            league_role: discord.PermissionOverwrite(
                view_channel=True,
                read_messages=True,
                connect=False,
                speak=False,
                send_messages=False,
                add_reactions=False,
            ),
        }

        combines_how_to_play = discord.utils.get(category.channels, name="how-to-play")
        if not combines_how_to_play:
            combines_how_to_play = await guild.create_text_channel(
                name="how-to-play",
                category=category,
                overwrites=admin_overwrites,
                reason="Starting combines",
            )

            # Send how to play
            if isinstance(combines_how_to_play, discord.TextChannel):
                await self.send_combines_how_to_play(combines_how_to_play)

        combines_announce = discord.utils.get(
            category.channels, name="combines-announcements"
        )
        if not combines_announce:
            combines_announce = await guild.create_text_channel(
                name="combines-announcements",
                category=category,
                overwrites=admin_overwrites,
                reason="Starting combines",
            )

        # Configure permissions
        player_overwrites: MutableMapping[
            discord.Member | discord.Role, discord.PermissionOverwrite
        ] = {
            guild.default_role: discord.PermissionOverwrite(
                view_channel=True,
                connect=False,
                speak=False,
                send_messages=False,
                add_reactions=False,
            ),
            league_role: discord.PermissionOverwrite(
                view_channel=True,
                connect=True,
                speak=True,
                send_messages=True,
                read_messages=True,
                add_reactions=True,
                stream=True,
                use_application_commands=True,
            ),
        }
        if muted_role:
            player_overwrites[muted_role] = discord.PermissionOverwrite(
                view_channel=True, connect=False, speak=False
            )

        combines_help = discord.utils.get(category.channels, name="combines-help")
        if not combines_help:
            combines_help = await guild.create_text_channel(
                name="combines-help",
                category=category,
                overwrites=player_overwrites,
                reason="Starting combines",
            )

            # Send help message
            if isinstance(combines_help, discord.TextChannel):
                await self.send_combines_help_msg(combines_help)

        # Make default channels
        combines_chat = discord.utils.get(category.channels, name="combines-general")
        if not combines_chat:
            combines_chat = await guild.create_text_channel(
                name="combines-general",
                category=category,
                overwrites=player_overwrites,
                slowmode_delay=5,  # Add 5 second slowmode
                reason="Starting combines",
            )

        # Waiting Room VC
        combines_waiting = discord.utils.get(
            category.channels, name="combines-waiting-room-1"
        )
        if not combines_waiting:
            combines_waiting = await guild.create_voice_channel(
                name="combines-waiting-room-1",
                category=category,
                overwrites=player_overwrites,
                reason="Starting combines",
            )

        combines_waiting2 = discord.utils.get(
            category.channels, name="combines-waiting-room-2"
        )
        if not combines_waiting2:
            combines_waiting2 = await guild.create_voice_channel(
                name="combines-waiting-room-2",
                category=category,
                overwrites=player_overwrites,
                reason="Starting combines",
            )

        await self._set_combines_active(guild, active=True)

        await interaction.followup.send(
            embed=GreenEmbed(
                title="Combines Started",
                description="Combines have been started and the required channels created.",
            )
        )

    @_combine_manager.command(name="stop", description="End RSC combines and delete channels")  # type: ignore
    async def _combines_stop(self, interaction: discord.Interaction):
        guild = interaction.guild
        if not guild:
            return

        status = await self._get_combines_active(guild)
        if not status:
            return await interaction.response.send_message(
                embed=ErrorEmbed(description="Combines are not currently active.")
            )

        category = await self._get_combines_category(guild)

        if not category:
            return await interaction.response.send_message(
                embed=ErrorEmbed(
                    description="Combines category channel has not been configured!"
                )
            )

        await interaction.response.defer(ephemeral=True)

        # tear down combine category
        await self.delete_combine_category(category)
        for i in range(2, 5):
            extra_cat = discord.utils.get(guild.categories, name=f"{category.name}-{i}")
            if extra_cat:
                await self.delete_combine_category(extra_cat)

        await self._set_combines_active(guild, active=False)
        await interaction.followup.send(
            embed=GreenEmbed(
                title="Combines Stopped",
                description="Combines have been ended and channels deleted.",
            )
        )

    @_combine_manager.command(name="delrooms", description="Delete all combine lobby channels. (Preserves general channels)")  # type: ignore
    async def _combines_delrooms_cmd(self, interaction: discord.Interaction):
        guild = interaction.guild
        if not guild:
            return

        category = await self._get_combines_category(guild)
        if not category:
            return await interaction.response.send_message(
                embed=ErrorEmbed(
                    description="Combines category channel has not been configured!"
                )
            )

        await interaction.response.defer(ephemeral=True)

        # tear down combine category
        await self.delete_combine_game_rooms(category)
        for i in range(2, 5):
            extra_cat = discord.utils.get(guild.categories, name=f"{category.name}-{i}")
            if extra_cat:
                # Delete entire category that isn't the primary
                await self.delete_combine_category(extra_cat)

        await interaction.followup.send(
            embed=GreenEmbed(
                title="Combine Rooms Deleted",
                description="Removed all combine game lobby channels.",
            )
        )

    # Helper Functions

    async def delete_combine_category(self, category: discord.CategoryChannel):
        """Delete a combine category and it's associated channels"""
        log.debug(f"[{category.guild}] Deleting combine category: {category.name}")
        channels = category.channels
        for c in channels:
            await c.delete(reason="Combines have ended.")
        await category.delete(reason="Combines have ended.")

    async def delete_combine_game_rooms(self, category: discord.CategoryChannel):
        """Delete a combine category and it's associated channels"""
        log.debug(
            f"[{category.guild}] Deleting combine category game rooms: {category.name}"
        )

        combine_vc_regex = re.compile(r"^\w+-\d+-(home|away)$", flags=re.IGNORECASE)

        vclist = category.channels
        for vc in vclist:
            if not isinstance(vc, discord.VoiceChannel):
                continue

            if not vc.category:
                continue

            if not vc.category.name.lower().startswith("combines"):
                continue

            if combine_vc_regex.match(vc.name):
                log.debug(f"Deleting {vc.name}")
                await vc.delete(reason="Combine lobby has finished.")

    async def send_combines_help_msg(self, channel: discord.TextChannel):
        await channel.send(content=COMBINES_HELP_1)
        await channel.send(content=COMBINES_HELP_2)
        await channel.send(content=COMBINES_HELP_3)

    async def send_combines_how_to_play(self, channel: discord.TextChannel):
        resources_root = Path(__file__).parent.parent / "resources" / "combines"

        login_img = discord.File(resources_root / "combines_login.png")
        checkin_img = discord.File(resources_root / "combines_check_in.png")
        announce_img = discord.File(resources_root / "combines_announcement.png")
        report_img = discord.File(resources_root / "combines_report.png")

        await channel.send(content=COMBINES_HOW_TO_PLAY_1, file=login_img)
        await channel.send(content=COMBINES_HOW_TO_PLAY_2, file=checkin_img)
        await channel.send(content=COMBINES_HOW_TO_PLAY_3, file=announce_img)
        await channel.send(content=COMBINES_HOW_TO_PLAY_4, file=report_img)
        await channel.send(content=COMBINES_HOW_TO_PLAY_5)

    # Config

    async def _set_combines_category(
        self, guild: discord.Guild, category: discord.CategoryChannel
    ):
        await self.config.custom("Combines", str(guild.id)).CombinesCategory.set(
            category.id
        )

    async def _get_combines_category(
        self, guild: discord.Guild
    ) -> discord.CategoryChannel | None:
        cat_id = await self.config.custom("Combines", str(guild.id)).CombinesCategory()
        if not cat_id:
            return None
        category = guild.get_channel(cat_id)
        if not isinstance(category, discord.CategoryChannel):
            return None
        return category

    async def _get_combines_api(self, guild: discord.Guild) -> str | None:
        return await self.config.custom("Combines", str(guild.id)).CombinesApi()

    async def _set_combines_api(self, guild: discord.Guild, url: str):
        await self.config.custom("Combines", str(guild.id)).CombinesApi.set(url)

    async def _get_combines_active(self, guild: discord.Guild) -> bool:
        return await self.config.custom("Combines", str(guild.id)).Active()

    async def _set_combines_active(self, guild: discord.Guild, active: bool):
        await self.config.custom("Combines", str(guild.id)).Active.set(active)
