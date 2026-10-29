import logging
from typing import TYPE_CHECKING

import discord
from redbot.core import app_commands

from rsc.abc import RSCMixIn
from rsc.const import (
    COMBINES_HELP_1,
    COMBINES_HELP_2,
    COMBINES_HELP_3,
    MUTED_ROLE,
)
from rsc.combines.guide import combines_command_mentions, combines_guide, is_combines_guide
from rsc.embeds import BlueEmbed, ErrorEmbed, GreenEmbed, OrangeEmbed
from rsc.lobbies.commands import ended_lines, teardown_command
from rsc.types import CombineSettings
from rsc.utils import utils

if TYPE_CHECKING:
    from collections.abc import MutableMapping

log = logging.getLogger("red.rsc.combines.manager")

defaults_guild = CombineSettings(
    Active=False,
    CombinesApi=None,
    CombinesCategory=None,
    LobbyMessages={},
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

    @_combine_manager.command(name="settings", description="Display combine settings")
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
        if category:
            category_value = category.mention
        elif await self._combines_category_deleted(guild):
            category_value = "Deleted. Set a new one with `/combinemanager category`."
        else:
            category_value = "None"
        embed.add_field(name="Combines Category", value=category_value, inline=False)
        await interaction.response.send_message(embed=embed, ephemeral=True)

    @_combine_manager.command(name="category", description="Configure the combines category channel")
    @app_commands.describe(category="Combines Category Channel")
    async def _combines_category_cmd(self, interaction: discord.Interaction, category: discord.CategoryChannel):
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

    @_combine_manager.command(name="api", description="Configure the API url for combines")
    @app_commands.describe(url="Combines API location (Ex: https://devleague.rscna.com/c-api/)")
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

    @_combine_manager.command(name="start", description="Begin RSC combines and create channels")
    async def _combines_start(self, interaction: discord.Interaction):
        guild = interaction.guild
        if not guild:
            return

        status = await self._get_combines_active(guild)
        if status:
            return await interaction.response.send_message(embed=ErrorEmbed(description="Combines are already active!"), ephemeral=True)

        api = await self._get_combines_api(guild)
        category = await self._get_combines_category(guild)

        if not api:
            return await interaction.response.send_message(
                embed=ErrorEmbed(description="Combines API has not been configured!"), ephemeral=True
            )
        if not category:
            return await interaction.response.send_message(embed=ErrorEmbed(description=await self._no_category_msg(guild)), ephemeral=True)

        await interaction.response.defer(ephemeral=True)

        # Get required role references
        league_role = await utils.get_league_role(guild)
        muted_role = discord.utils.get(guild.roles, name=MUTED_ROLE)
        admin_role = discord.utils.get(guild.roles, name="Admin")
        log.debug(f"[{guild}] Default Role: {guild.default_role}")

        if not league_role:
            return await interaction.followup.send(embed=ErrorEmbed(description="League role does not exist."), ephemeral=True)

        if not admin_role:
            return await interaction.followup.send(embed=ErrorEmbed(description="Admin role does not exist."), ephemeral=True)

        # Admin only overwrites
        admin_overwrites: MutableMapping[discord.Role | discord.Member | discord.Object, discord.PermissionOverwrite] = {
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
        new_how_to_play = combines_how_to_play is None
        if not combines_how_to_play:
            combines_how_to_play = await guild.create_text_channel(
                name="how-to-play",
                category=category,
                overwrites=admin_overwrites,
                reason="Starting combines",
            )

        combines_announce = discord.utils.get(category.channels, name="combines-announcements")
        if not combines_announce:
            combines_announce = await guild.create_text_channel(
                name="combines-announcements",
                category=category,
                overwrites=admin_overwrites,
                reason="Starting combines",
            )

        # Sent once the announcements channel exists, so the guide can link it
        if new_how_to_play and isinstance(combines_how_to_play, discord.TextChannel):
            await self.send_combines_how_to_play(combines_how_to_play, announcements=combines_announce)

        # Configure permissions
        player_overwrites: MutableMapping[discord.Role | discord.Member | discord.Object, discord.PermissionOverwrite] = {
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
            player_overwrites[muted_role] = discord.PermissionOverwrite(view_channel=True, connect=False, speak=False)

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
        combines_waiting = discord.utils.get(category.channels, name="combines-waiting-room-1")
        if not combines_waiting:
            combines_waiting = await guild.create_voice_channel(
                name="combines-waiting-room-1",
                category=category,
                overwrites=player_overwrites,
                reason="Starting combines",
            )

        combines_waiting2 = discord.utils.get(category.channels, name="combines-waiting-room-2")
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
            ),
            ephemeral=True,
        )

    @_combine_manager.command(name="stop", description="End RSC combines and delete channels")
    async def _combines_stop(self, interaction: discord.Interaction):
        guild = interaction.guild
        if not guild:
            return

        status = await self._get_combines_active(guild)
        if not status:
            return await interaction.response.send_message(
                embed=ErrorEmbed(description="Combines are not currently active."), ephemeral=True
            )

        await interaction.response.defer(ephemeral=True)
        # Off first, so no new lobby starts while the open ones are torn down
        await self._set_combines_active(guild, active=False)

        # Ending a lobby turns its card and DMs Final and deletes its channels
        runner = self._combines_runner
        lobby_ids = sorted(await runner.open_lobbies(guild))
        failed = await runner.end_now(guild, lobby_ids)

        # The combines category and its standing channels stay for the next start.
        # Overflow categories only ever hold lobby channels, so they go.
        category = await self._get_combines_category(guild)
        if category:
            for i in range(2, 5):
                overflow = discord.utils.get(guild.categories, name=f"{category.name}-{i}")
                if overflow:
                    await self.delete_overflow_category(overflow)

        lines = [
            "Combines have been stopped. The combines category and its channels are kept.",
            *ended_lines(runner.league, lobby_ids, failed),
        ]
        await interaction.followup.send(
            embed=(OrangeEmbed if failed else GreenEmbed)(title="Combines Stopped", description="\n".join(lines)),
            ephemeral=True,
        )

    @_combine_manager.command(name="teardown", description="End combine lobbies that are still up in Discord")
    @app_commands.describe(lobby_id="Lobby to end. Leave empty to end every lobby.")
    async def _combines_teardown_cmd(self, interaction: discord.Interaction, lobby_id: int | None = None):
        await teardown_command(interaction, self._combines_runner, lobby_id)

    @_combine_manager.command(name="guide", description="Post the combines how-to-play guide")
    @app_commands.describe(
        channel="Where to post it. Defaults to #how-to-play in the combines category.",
        overwrite="Update the guide that's already posted there with the current one",
    )
    async def _combines_guide_cmd(
        self, interaction: discord.Interaction, channel: discord.TextChannel | None = None, overwrite: bool = False
    ):
        guild = interaction.guild
        if not guild:
            return

        category = await self._get_combines_category(guild)
        if not channel:
            if not category:
                msg = await self._no_category_msg(guild)
                return await interaction.response.send_message(embed=ErrorEmbed(description=msg), ephemeral=True)
            channel = discord.utils.get(category.text_channels, name="how-to-play")
            if not channel:
                return await interaction.response.send_message(
                    embed=ErrorEmbed(description=f"There's no #how-to-play channel in {category.mention}. Pick a channel to post in."),
                    ephemeral=True,
                )

        await interaction.response.defer(ephemeral=True)
        existing = await anext((m async for m in channel.history(limit=100) if m.author == guild.me and is_combines_guide(m)), None)
        if existing and not overwrite:
            return await interaction.followup.send(
                embed=OrangeEmbed(
                    title="Combines Guide",
                    description=f"A guide is already posted: {existing.jump_url}\nRun this again with `overwrite` to update it.",
                ),
                ephemeral=True,
            )

        announcements = discord.utils.get(category.text_channels, name="combines-announcements") if category else None
        view, files = await self.combines_guide_card(guild, announcements)
        try:
            # Edited in place, so the guide keeps its spot in the channel and its link
            if existing:
                message = await existing.edit(view=view, attachments=files, allowed_mentions=discord.AllowedMentions.none())
            else:
                message = await channel.send(view=view, files=files, allowed_mentions=discord.AllowedMentions.none())
        except discord.HTTPException as exc:
            log.warning(f"Unable to post the combines guide in #{channel.name}: {exc}")
            return await interaction.followup.send(
                embed=ErrorEmbed(description=f"Couldn't post the guide in {channel.mention}: {exc.text}"), ephemeral=True
            )

        await interaction.followup.send(
            embed=GreenEmbed(title="Combines Guide", description=f"{'Updated' if existing else 'Posted'} the guide: {message.jump_url}"),
            ephemeral=True,
        )

    # Helper Functions

    async def delete_overflow_category(self, category: discord.CategoryChannel):
        """Delete a combines overflow category and any lobby channels left in it"""
        log.debug(f"[{category.guild}] Deleting combines overflow category: {category.name}")
        channels = category.channels
        for c in channels:
            try:
                await c.delete(reason="Combines have ended.")
            except discord.NotFound:
                # Lobby teardown just deleted it, before the cache caught up
                pass
        await category.delete(reason="Combines have ended.")

    async def send_combines_help_msg(self, channel: discord.TextChannel):
        await channel.send(content=COMBINES_HELP_1)
        await channel.send(content=COMBINES_HELP_2)
        await channel.send(content=COMBINES_HELP_3)

    async def send_combines_how_to_play(self, channel: discord.TextChannel, announcements: discord.abc.GuildChannel | None = None):
        """Post the how-to-play guide card."""
        view, files = await self.combines_guide_card(channel.guild, announcements)
        await channel.send(view=view, files=files, allowed_mentions=discord.AllowedMentions.none())

    async def combines_guide_card(
        self, guild: discord.Guild, announcements: discord.abc.GuildChannel | None = None
    ) -> tuple[discord.ui.LayoutView, list[discord.File]]:
        """The how-to-play guide card. Commands it names become clickable when they're synced."""
        try:
            synced = await self.bot.tree.fetch_commands() or await self.bot.tree.fetch_commands(guild=guild)
        except discord.HTTPException as exc:
            log.warning(f"Unable to look up command mentions for the combines guide: {exc}")
            synced = []
        where = announcements.mention if announcements else "#combines-announcements"
        return combines_guide(combines_command_mentions(synced), announcements=where)

    # Config

    async def _set_combines_category(self, guild: discord.Guild, category: discord.CategoryChannel):
        await self.config.custom("Combines", str(guild.id)).CombinesCategory.set(category.id)

    async def _get_combines_category(self, guild: discord.Guild) -> discord.CategoryChannel | None:
        cat_id = await self.config.custom("Combines", str(guild.id)).CombinesCategory()
        if not cat_id:
            return None
        category = guild.get_channel(cat_id)
        if not isinstance(category, discord.CategoryChannel):
            return None
        return category

    async def _combines_category_deleted(self, guild: discord.Guild) -> bool:
        """A category was set, but it no longer exists in the guild."""
        return bool(await self.config.custom("Combines", str(guild.id)).CombinesCategory()) and not await self._get_combines_category(guild)

    async def _no_category_msg(self, guild: discord.Guild) -> str:
        """Why there is no combines category to use."""
        if await self._combines_category_deleted(guild):
            return "The combines category no longer exists. Set a new one with `/combinemanager category`."
        return "Combines category channel has not been configured!"

    async def _get_combines_api(self, guild: discord.Guild) -> str | None:
        return await self.config.custom("Combines", str(guild.id)).CombinesApi()

    async def _set_combines_api(self, guild: discord.Guild, url: str):
        await self.config.custom("Combines", str(guild.id)).CombinesApi.set(url)

    async def _get_combines_active(self, guild: discord.Guild) -> bool:
        return await self.config.custom("Combines", str(guild.id)).Active()

    async def _set_combines_active(self, guild: discord.Guild, active: bool):
        await self.config.custom("Combines", str(guild.id)).Active.set(active)
