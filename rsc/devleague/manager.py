import logging

import discord
from redbot.core import app_commands

from rsc.abc import RSCMixIn
from rsc.embeds import BlueEmbed, ErrorEmbed, GreenEmbed, OrangeEmbed

log = logging.getLogger("red.rsc.devleague.manager")


class DevLeagueManagerMixIn(RSCMixIn):
    def __init__(self):
        log.debug("Initializing DevLeagueMixIn:Manager")
        super().__init__()

    # Settings

    _devleague_manager = app_commands.Group(
        name="devleaguemanager",
        description="Manage dev league",
        guild_only=True,
        default_permissions=discord.Permissions(manage_guild=True),
    )

    # Privileged Commands

    @_devleague_manager.command(name="settings", description="Display dev league settings")
    async def _devleague_settings_cmd(self, interaction: discord.Interaction):
        guild = interaction.guild
        if not guild:
            return

        active = await self._get_devleague_active(guild)
        category = await self._get_devleague_category(guild)
        announce_channel = await self._get_devleague_announce_channel(guild)

        embed = BlueEmbed(
            title="Dev League Settings",
            description="Current configuration for Dev League game channels",
        )
        embed.add_field(name="Dev League Active", value=active, inline=False)
        embed.add_field(
            name="Dev League Category",
            value=category.mention if category else "None",
            inline=False,
        )
        embed.add_field(
            name="Announcement Channel",
            value=announce_channel.mention if announce_channel else "None",
            inline=False,
        )
        await interaction.response.send_message(embed=embed, ephemeral=True)

    @_devleague_manager.command(name="category", description="Configure the dev league game channel category")
    @app_commands.describe(category="Category that dev league game channels are created in")
    async def _devleague_category_cmd(self, interaction: discord.Interaction, category: discord.CategoryChannel):
        guild = interaction.guild
        if not guild:
            return

        await self._set_devleague_category(guild, category)
        await interaction.response.send_message(
            embed=GreenEmbed(
                title="Dev League Category",
                description=f"Dev League category has been configured: {category.mention}",
            ),
            ephemeral=True,
        )

    @_devleague_manager.command(name="announcements", description="Configure the dev league game announcement channel")
    @app_commands.describe(channel="Channel that new dev league games are announced in")
    async def _devleague_announcements_cmd(self, interaction: discord.Interaction, channel: discord.TextChannel):
        guild = interaction.guild
        if not guild:
            return

        await self._set_devleague_announce_channel(guild, channel)
        await interaction.response.send_message(
            embed=GreenEmbed(
                title="Dev League Announcements",
                description=f"Dev League announcement channel has been configured: {channel.mention}",
            ),
            ephemeral=True,
        )

    @_devleague_manager.command(name="enable", description="Enable dev league game channel creation")
    async def _devleague_enable_cmd(self, interaction: discord.Interaction):
        guild = interaction.guild
        if not guild:
            return

        if not await self._get_devleague_category(guild):
            await interaction.response.send_message(
                embed=ErrorEmbed(description="Dev League category must be configured before enabling."),
                ephemeral=True,
            )
            return

        await self._set_devleague_active(guild, True)
        await interaction.response.send_message(
            embed=GreenEmbed(
                title="Dev League Enabled",
                description="Dev League game channels will now be created.",
            ),
            ephemeral=True,
        )

    @_devleague_manager.command(name="disable", description="Disable dev league game channel creation")
    async def _devleague_disable_cmd(self, interaction: discord.Interaction):
        guild = interaction.guild
        if not guild:
            return

        await self._set_devleague_active(guild, False)
        await interaction.response.send_message(
            embed=OrangeEmbed(
                title="Dev League Disabled",
                description="Dev League game channels will no longer be created.",
            ),
            ephemeral=True,
        )

    @_devleague_manager.command(name="teardown", description="End Dev League matches that are still up in Discord")
    @app_commands.describe(match_id="Match to end. Leave empty to end every match.")
    async def _devleague_teardown_cmd(self, interaction: discord.Interaction, match_id: int | None = None):
        guild = interaction.guild
        if not guild:
            return

        runner = self._devleague_runner
        open_ids = await runner.open_lobbies(guild)
        if match_id is not None and match_id not in open_ids:
            await interaction.response.send_message(
                embed=ErrorEmbed(description=f"Match {match_id} has no live card or voice channels."),
                ephemeral=True,
            )
            return

        targets = sorted({match_id} if match_id is not None else open_ids)
        if not targets:
            await interaction.response.send_message(
                embed=ErrorEmbed(description="There are no Dev League matches to end."),
                ephemeral=True,
            )
            return

        await interaction.response.defer(ephemeral=True)

        # One failed match must not stop the rest from being ended
        failed = []
        for lobby_id in targets:
            try:
                await runner.teardown(guild, lobby_id, delay=False)
            except discord.HTTPException as exc:
                log.exception(f"Error tearing down Dev League match {lobby_id}", exc_info=exc)
                failed.append(lobby_id)

        ended = [i for i in targets if i not in failed]
        lines = [f"Ended {_matches(ended)}."] if ended else []
        if failed:
            lines.append(f"Unable to end {_matches(failed)}. Check the bot's permissions.")
        embed = (GreenEmbed if not failed else OrangeEmbed)(title="Dev League Teardown", description="\n".join(lines))
        await interaction.followup.send(embed=embed, ephemeral=True)

    # Config

    async def _get_devleague_active(self, guild: discord.Guild) -> bool:
        return await self.config.custom("DevLeague", str(guild.id)).Active()

    async def _set_devleague_active(self, guild: discord.Guild, active: bool):
        await self.config.custom("DevLeague", str(guild.id)).Active.set(active)

    async def _get_devleague_category(self, guild: discord.Guild) -> discord.CategoryChannel | None:
        cat_id = await self.config.custom("DevLeague", str(guild.id)).DevLeagueCategory()
        if not cat_id:
            return None
        category = guild.get_channel(cat_id)
        if not isinstance(category, discord.CategoryChannel):
            return None
        return category

    async def _set_devleague_category(self, guild: discord.Guild, category: discord.CategoryChannel):
        await self.config.custom("DevLeague", str(guild.id)).DevLeagueCategory.set(category.id)

    async def _get_devleague_announce_channel(self, guild: discord.Guild) -> discord.TextChannel | None:
        channel_id = await self.config.custom("DevLeague", str(guild.id)).DevLeagueAnnounceChannel()
        if not channel_id:
            return None
        channel = guild.get_channel(channel_id)
        if not isinstance(channel, discord.TextChannel):
            return None
        return channel

    async def _set_devleague_announce_channel(self, guild: discord.Guild, channel: discord.TextChannel):
        await self.config.custom("DevLeague", str(guild.id)).DevLeagueAnnounceChannel.set(channel.id)


def _matches(lobby_ids: list[int]) -> str:
    """ "match 101" or "3 matches: 101, 102, 103"."""
    if len(lobby_ids) == 1:
        return f"match {lobby_ids[0]}"
    return f"{len(lobby_ids)} matches: {', '.join(map(str, lobby_ids))}"
