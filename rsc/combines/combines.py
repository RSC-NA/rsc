import logging

import discord
from discord import VoiceState
from redbot.core import app_commands, commands
from rscapi.models.tier import Tier

from rsc.abc import RSCMixIn
from rsc.const import LEAGUE_ROLE, MUTED_ROLE
from rsc.embeds import ErrorEmbed, SuccessEmbed

log = logging.getLogger("red.rsc.combines")

defaults_guild = {
    "Capacity": 10,
    "Public": False,
    "Active": False,
}


class CombineMixIn(RSCMixIn):
    COMBINE_PLAYER_RATIO = 0.5

    def __init__(self):
        log.debug("Initializing CombineMixIn")

        self._combine_cache: dict[discord.Guild, list[int]] = {}

        self.config.init_custom("Combines", 1)
        self.config.register_custom("Combines", **defaults_guild)
        super().__init__()

    # Setup

    async def _populate_combines_cache(self, guild: discord.Guild):
        self._combine_cache[guild] = [
            c.id for c in await self.get_combine_categories(guild)
        ]

    # Listeners

    @commands.Cog.listener("on_voice_state_update")
    async def combines_on_voice_state_update(
        self,
        member: discord.Member,
        before: discord.VoiceState,
        after: discord.VoiceState,
    ):
        if before.channel == after.channel:
            return

        # Combines not active or no categories exist
        if not self._combine_cache.get(member.guild):
            return

        log.debug(f"Member: {member}")
        log.debug(f"Before: {before}")
        log.debug(f"After: {after}")
        # Room Joined
        if after.channel:
            await self._maybe_add_combine_channel(after)
        # Room Left
        if before.channel:
            await self._maybe_remove_combine_channel(before)

    # Settings

    _combines = app_commands.Group(
        name="combines",
        description="Combine commands and configuration",
        guild_only=True,
        default_permissions=discord.Permissions(manage_guild=True),
    )

    @_combines.command(name="settings", description="Display combine settings")
    async def _combines_settings(self, interaction: discord.Interaction):
        guild = interaction.guild
        if not guild:
            return

        active = await self._get_combines_active(guild)
        capacity = await self._get_room_capacity(guild)
        public = await self._get_publicity(guild)

        embed = discord.Embed(
            title="Combine Settings",
            description="Current configuration for Combines Cog",
            color=discord.Color.blue(),
        )
        embed.add_field(name="Active", value=active, inline=False)
        embed.add_field(name="Room Capacity", value=str(capacity), inline=False)
        embed.add_field(name="Public", value=public, inline=False)
        await interaction.response.send_message(embed=embed, ephemeral=True)

    @_combines.command(
        name="public",
        description='Toggle combine rooms publicity (Private rooms require "League" role)',
    )
    async def _combines_public(self, interaction: discord.Interaction):
        guild = interaction.guild
        if not guild:
            return

        public = await self._get_publicity(guild)
        public ^= True
        await self._save_publicity(guild, public)
        await interaction.response.send_message(
            embed=discord.Embed(
                title="Room Publicity Configured",
                description=f"Combine rooms are now **{'public' if public else 'private'}**",
                color=discord.Color.green(),
            ),
            ephemeral=True,
        )

    @_combines.command(
        name="capacity",
        description="Define the combine room max capacity (Default: 10)",
    )
    @app_commands.describe(capacity="Max number of players in combine channel")
    async def _combines_capacity(self, interaction: discord.Interaction, capacity: int):
        if not interaction.guild:
            return

        await self._save_room_capacity(interaction.guild, capacity)
        await interaction.response.send_message(
            embed=discord.Embed(
                title="Combine Capacity Configured",
                description=f"Combine rooms now have a maximum of **{capacity}** players.",
                color=discord.Color.green(),
            ),
            ephemeral=True,
        )

    # Commands

    @_combines.command(
        name="start", description="Begin RSC combines and create channels"
    )
    async def _combines_start(self, interaction: discord.Interaction):
        guild = interaction.guild
        if not guild:
            return

        if await self._get_combines_active(guild):
            await interaction.response.send_message(
                embed=ErrorEmbed(description="Combines are already started."),
                ephemeral=True,
            )
            return
        # Get tiers for league
        tiers: list[Tier] = await self.tiers(guild)
        log.debug(tiers)

        # Exit if no Tiers exist
        if not tiers:
            await interaction.response.send_message(
                embed=ErrorEmbed(
                    description="There are currently no tiers configured for the league."
                ),
                ephemeral=True,
            )
            return

        # This can take more than 3 seconds. Defer response.
        await interaction.response.defer()

        await self._save_combines_active(guild, True)
        await self.create_combines(guild, tiers)
        await interaction.followup.send(
            embed=SuccessEmbed(
                description="Combines have been **started** and all channels created."
            )
        )

    @_combines.command(name="stop", description="End RSC combines and delete channels")
    async def _combines_stop(self, interaction: discord.Interaction):
        if not interaction.guild:
            return

        categories = await self.get_combine_categories(interaction.guild)

        # This can take more than 3 seconds. Defer response.
        await interaction.response.defer()

        for c in categories:
            await self.delete_combine_category(c)
        await self._save_combines_active(interaction.guild, False)
        await interaction.followup.send(
            embed=SuccessEmbed(
                description="Combines have been **ended** and all channels removed."
            )
        )

    @_combines.command(
        name="overview", description="Get overview of current combine channels"
    )
    async def _combines_overview(self, interaction: discord.Interaction):
        if not interaction.guild:
            return

        if not await self._get_combines_active(interaction.guild):
            await interaction.response.send_message(
                embed=ErrorEmbed(description="Combines are not currently active."),
                ephemeral=True,
            )
            return

        categories = await self.get_combine_categories(interaction.guild)
        if not categories:
            await interaction.response.send_message(
                embed=ErrorEmbed(
                    description="Combines are active but there are no combine categories created."
                ),
                ephemeral=True,
            )
            return

        overview: list[tuple[discord.CategoryChannel, int, int]] = []
        for c in categories:
            data = (
                c,
                len(c.voice_channels),
                await self.total_players_in_combine_category(c),
            )
            overview.append(data)

        embed = discord.Embed(
            title=f"{interaction.guild} Combine Overview",
            description="Overview of current combine channels.",
            color=discord.Color.blue(),
        )
        embed.add_field(
            name="Tier",
            value="\n".join([o[0].name.removesuffix(" Combines") for o in overview]),
            inline=True,
        )
        embed.add_field(
            name="Channels", value="\n".join([str(o[1]) for o in overview]), inline=True
        )
        embed.add_field(
            name="Total Players",
            value="\n".join([str(o[2]) for o in overview]),
            inline=True,
        )
        await interaction.response.send_message(embed=embed)

    # Functions

    async def create_combines(self, guild: discord.Guild, tiers: list[Tier]):
        """Create all combine categories and channels for specified tier(s)"""
        public = await self._get_publicity(guild)
        for t in tiers:
            log.debug(f"[{guild}] Creating combine channels for {t.name}")
            c = await self.create_combine_category(guild, t.name, public=public)
            self._combine_cache[guild].append(c.id)

    async def create_combine_category(
        self, guild: discord.Guild, tier_name: str, public: bool = False
    ) -> discord.CategoryChannel:
        """Create a combine category and voice channels"""
        # Check if category already exists and delete if so.
        # Re-using the category can result in a wide range of issues. (Permissions, size, etc)
        for c in guild.categories:
            if c.name.startswith(tier_name) and c.name.endswith("Combines"):
                await self.delete_combine_category(c)

        size = await self._get_room_capacity(guild)
        public = await self._get_publicity(guild)

        # Get required role references
        league_role = discord.utils.get(guild.roles, name=LEAGUE_ROLE)
        muted_role = discord.utils.get(guild.roles, name=MUTED_ROLE)
        log.debug(f"[{guild}] Default Role: {guild.default_role}")

        if not league_role:
            raise ValueError("League role does not exist.")

        # Configure permissions
        overwrites = {
            guild.default_role: discord.PermissionOverwrite(
                view_channel=public, connect=public, speak=public
            ),
            league_role: discord.PermissionOverwrite(
                view_channel=True, connect=True, speak=True
            ),
        }
        if muted_role:
            overwrites[muted_role] = discord.PermissionOverwrite(
                view_channel=True, connect=False, speak=False
            )

        category = await guild.create_category(
            name=f"{tier_name} Combines",
            position=len(guild.channels),
            overwrites=overwrites,
            reason="Starting combines",
        )
        log.debug(f"[{guild} Created combine category: {category.name}]")

        # Create voice channel (will sync with category overwrites)
        await category.create_voice_channel(
            name=f"{tier_name}1 // {tier_name}1", position=0, user_limit=size
        )

        return category

    async def get_combine_categories(
        self, guild: discord.Guild
    ) -> list[discord.CategoryChannel]:
        """Get a list of combine categories in the guild"""
        categories = []
        for x in guild.categories:
            if x.name.endswith("Combines"):
                categories.append(x)
        return categories

    async def delete_combine_category(self, category: discord.CategoryChannel):
        """Delete a combine category and it's associated channels"""
        log.debug(f"[{category.guild}] Deleting combine category: {category.name}")
        for channel in category.channels:
            await channel.delete(reason="Combines have ended.")
        await category.delete(reason="Combines have ended.")

    async def total_players_in_combine_category(
        self, category: discord.CategoryChannel
    ) -> int:
        total = 0
        for channel in category.voice_channels:
            total += len(channel.members)
        return total

    # Hidden

    async def _maybe_add_combine_channel(self, state: VoiceState):
        """Determine if we need more combine voice channels"""
        if not isinstance(state.channel, discord.VoiceChannel):
            return

        # Return if voice channel not in a category
        if not state.channel.category_id:
            return

        # Check if category is a combines category
        if state.channel.category_id not in self._combine_cache[state.channel.guild]:
            return

        category = state.channel.category
        if not category:
            return

        log.debug(f"Found combine category: {category.name}")

        # Check if there is a combine channel with enough spots still
        for c in category.channels:
            if not isinstance(c, discord.VoiceChannel):
                continue
            log.debug(
                f"[{c.name}] Members: {len(c.members)} Limit: {c.user_limit} Ratio: {len(c.members) / c.user_limit}"
            )
            # If member ratio is below COMBINE_PLAYER_RATIO, there are enough spots still
            if (len(c.members) / c.user_limit) < self.COMBINE_PLAYER_RATIO:
                log.debug(f"[{category.name}] Enough combine slots in {c.name}")
                return

        # All channels are above or equal to COMBINE_PLAYER_RATIO. Add Channel
        log.debug(f"Total Channels in Combine Category: {len(category.channels)}")
        num = len(category.channels) + 1
        tier = category.name.removesuffix(" Combines")
        size = await self._get_room_capacity(state.channel.guild)
        log.debug(
            f"[{category.name}] Creating new voice channel: {tier}{num} // {tier}{num}"
        )
        await category.create_voice_channel(
            name=f"{tier}{num} // {tier}{num}",
            position=0,
            user_limit=size,
            reason="Adding combine channel to accomodate more players",
        )

    async def _maybe_remove_combine_channel(self, state: VoiceState):
        """Determine if we should remove a combine voice channel"""
        if not isinstance(state.channel, discord.VoiceChannel):
            return

        # Return if voice channel not in a category
        if not (state.channel.category and state.channel.category_id):
            return

        # Do nothing if user still in voice
        if len(state.channel.members):
            return

        # Check if category is a combines category
        if state.channel.category_id not in self._combine_cache[state.channel.guild]:
            return

        # Do nothing if it's the first combine channel
        if state.channel.name.endswith("1"):
            return

        category = state.channel.category
        log.debug(f"Found combine category: {category.name}")

        # Check if another channel is below
        for c in category.channels:
            if not isinstance(c, discord.VoiceChannel):
                continue
            # If channel has open slots acccording to COMBINE_PLAYER_RATIO, remove channel
            if (len(c.members) / c.user_limit) < self.COMBINE_PLAYER_RATIO:
                log.debug(
                    f"[{category.name}] Enough combine slots in {c.name}. Deleting {state.channel.name}"
                )
                await state.channel.delete(
                    reason="Removing dynamically created combine channel."
                )

    # Config

    async def _get_room_capacity(self, guild: discord.Guild) -> int:
        return await self.config.custom("Combines", guild.id).Capacity()

    async def _save_room_capacity(self, guild: discord.Guild, capacity: int):
        await self.config.custom("Combines", guild.id).Capacity.set(capacity)

    async def _get_publicity(self, guild: discord.Guild) -> bool:
        return await self.config.custom("Combines", guild.id).Public()

    async def _save_publicity(self, guild: discord.Guild, public: bool):
        await self.config.custom("Combines", guild.id).Public.set(public)

    async def _get_combines_active(self, guild: discord.Guild) -> bool:
        return await self.config.custom("Combines", guild.id).Active()

    async def _save_combines_active(self, guild: discord.Guild, active: bool):
        await self.config.custom("Combines", guild.id).Active.set(active)
