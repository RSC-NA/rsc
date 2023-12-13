import discord
import logging

from datetime import datetime, time, timedelta
from discord import VoiceState
from discord.ext import tasks

from redbot.core import app_commands, checks, commands, Config

from rscapi import ApiClient, LeaguePlayersApi
from rscapi.models.tier import Tier
from rscapi.models.league_player import LeaguePlayer
from rscapi.models.member import Member

from rsc.abc import RSCMixIn
from rsc.tiers import TierMixIn
from rsc.const import LEAGUE_ROLE, MUTED_ROLE
from rsc.embeds import ErrorEmbed, SuccessEmbed
from rsc.enums import Status
from rsc.types import CheckIn
from rsc.utils.utils import (
    role_by_name,
    member_from_rsc_name,
    tier_color_by_name,
)

from rsc.freeagents.views import CheckInView, CheckOutView


from typing import List, Dict, Tuple, TypedDict, Optional

log = logging.getLogger("red.rsc.freeagents")

# Noon - Eastern (-5) - Not DST aware
# Have to use UTC for loop. TZ aware object causes issues with clock drift calculations
FA_LOOP_TIME = time(hour=17)


defaults_guild: dict[str, list[CheckIn]] = {"CheckIns": []}


class FreeAgentMixIn(RSCMixIn):
    def __init__(self):
        log.debug("Initializing FreeAgentMixIn")

        self._check_ins: dict[int, list[CheckIn]] = {}

        self.config: Config
        self.config.init_custom("FreeAgents", 1)
        self.config.register_custom("FreeAgents", **defaults_guild)
        super().__init__()

        # Start FA check in loop
        self.expire_free_agent_checkins_loop.start()

    # Setup

    async def _populate_free_agent_cache(self, guild: discord.Guild):
        """Populate checked in free agents to cache"""
        fa_checkins = await self._get_check_ins(guild)
        self._check_ins[guild.id] = fa_checkins
        log.debug(f"FA Cache: {self._check_ins[guild.id]}")

    # Tasks

    @tasks.loop(time=FA_LOOP_TIME)
    async def expire_free_agent_checkins_loop(self):
        log.debug("Expire FA Loop is running")
        for k, v in self._check_ins.items():
            guild = self.bot.get_guild(k)

            # Validate the guild exists
            if not guild:
                log.error(
                    f"Unable to resolve guild during expire FA check in loop: {k}"
                )
                continue

            log.info(f"[{guild.name}] Removing expired free agents.")
            guild_tz = await self.timezone(guild)
            yesterday = datetime.now(guild_tz) - timedelta(1)

            # Loop through checkins.
            for player in v:
                checkin_date = datetime.fromisoformat(player["date"])
                if checkin_date.date() <= yesterday.date():
                    log.debug(f"[{guild.name} Expiring FA check in: {player['player']}")
                    await self.remove_checkin(guild, player)

    # Commands

    @app_commands.command(
        name="freeagents", description="List free agents in a specified tier"
    )
    @app_commands.describe(tier="Free agent tier (Ex: \"Elite\")")
    @app_commands.autocomplete(tier=TierMixIn.tier_autocomplete)
    @app_commands.guild_only()
    async def _free_agents(self, interaction: discord.Interaction, tier: str):
        await interaction.response.defer()
        if not await self.is_valid_tier(interaction.guild, tier):
            await interaction.followup.send(
                embed=ErrorEmbed(description=f"**{tier}** is not a valid tier."),
            )
            return
        free_agents = await self.free_agents(interaction.guild, tier)
        free_agents.extend(await self.permanent_free_agents(interaction.guild, tier))

        data: list[str] = []
        for fa in free_agents:
            log.debug(fa.player)
            fmember = None
            if hasattr(fa.player, "discord_id"):
                log.debug("Found discord_id for free agent")
                fmember = interaction.guild.get_member(fa.player.discord_id)
            fstr = fmember.display_name if fmember else fa.player.name
            if fa.status == Status.PERM_FA:
                fstr += " (Permanent FA)"
            data.append(fstr)
        data = "\n".join(data)

        tier_role = await role_by_name(interaction.guild, tier)

        embed = discord.Embed(
            title=f"{tier} Free Agents",
            description=f"```\n{data}\n```",
            color=tier_role.color if tier_role else discord.Color.blue(),
        )

        await interaction.followup.send(embed=embed)

    @app_commands.command(
        name="checkin",
        description="Check in as an available free agent for the current match day",
    )
    @app_commands.guild_only()
    async def _fa_checkin(self, interaction: discord.Interaction):
        # Check if this player already checked in
        if await self.is_checked_in(interaction.user):
            await interaction.response.send_message(
                embed=ErrorEmbed(
                    title="Check In Error",
                    description="You are already checked in for today",
                ),
                ephemeral=True,
            )
            return

        # Check if match day
        if not await self.is_match_day(interaction.guild):
            await interaction.response.send_message(
                embed=ErrorEmbed(
                    title="Check In Error", description="There are no matches today!"
                ),
                ephemeral=True,
            )
            return

        # Check if player is an FA in the guilds league
        players = await self.players(
            interaction.guild,
            discord_id=interaction.user.id,
            limit=1,
        )

        # Check if member exists in RSC
        if not players:
            await interaction.response.send_message(
                embed=ErrorEmbed(
                    title="Check In Error",
                    description="You are not currently a member of this RSC league",
                ),
                ephemeral=True,
            )
            return

        player: LeaguePlayer = players[0]

        # Check if player is a Free Agent or PermFA
        if not (player.status == Status.FREE_AGENT or player.status == Status.PERM_FA):
            await interaction.response.send_message(
                embed=ErrorEmbed(
                    title="Check In Error",
                    description="You are not a free agent.",
                ),
                ephemeral=True,
            )
            return

        # Tier
        tier_role = await role_by_name(interaction.guild, player.tier.name)
        tier_color = None
        if tier_role:
            tier_color = tier_role.color

        # Prompt for check in
        checkin_view = CheckInView(interaction, tier=player.tier.name, color=tier_color)
        await checkin_view.prompt()

        if checkin_view.result:
            tz = await self.timezone(interaction.guild)
            checkin = CheckIn(
                date=str(datetime.now(tz)),
                player=interaction.user.id,
                tier=player.tier.name,
            )
            await self.add_checkin(interaction.guild, checkin)

    @app_commands.command(
        name="checkout",
        description="Check out as an available free agent for the current match day",
    )
    @app_commands.guild_only()
    async def _fa_checkout(self, interaction: discord.Interaction):
        # Check if this player already checked in
        checkin = await self.get_checkin(interaction.user)
        if not checkin:
            await interaction.response.send_message(
                embed=ErrorEmbed(
                    title="Check Out Error",
                    description="You are not currently checked in...",
                ),
                ephemeral=True,
            )
            return

        checkout_view = CheckOutView(interaction, tier=checkin["tier"])
        await checkout_view.prompt()

        if checkout_view.result:
            await self.remove_checkin(interaction.guild, checkin)

    @app_commands.command(
        name="availability",
        description="Get list of available free agents for specified tier",
    )
    @app_commands.describe(tier="Free agent tier (Ex: \"Elite\")")
    @app_commands.autocomplete(tier=TierMixIn.tier_autocomplete)
    @app_commands.guild_only()
    async def _fa_availability(self, interaction: discord.Interaction, tier: str):
        checkins = await self.checkins_by_tier(interaction.guild, tier)

        tier_color = (
            await tier_color_by_name(interaction.guild, tier)
            or discord.Color.blue()
        )

        # Filter out anyone who isn't in the guild
        available = []
        for c in checkins:
            m = interaction.guild.get_member(c["player"])
            if m:
                available.append(m)

        embed = discord.Embed(
            title=f"{tier} Free Agent Availability",
            description="The following free agents are available",
            color=tier_color,
        )
        if not available:
            embed.description = f"No players have checked in for the **{tier}** tier"
        else:
            embed.add_field(
                name="Players",
                value="\n".join([m.display_name for m in available]),
                inline=False,
            )
        await interaction.response.send_message(embed=embed)

    @app_commands.command(
        name="clearavailability",
        description="Clear free agent availability for a specified tier",
    )
    @app_commands.describe(tier="Free agent tier (Ex: \"Elite\")")
    @app_commands.autocomplete(tier=TierMixIn.tier_autocomplete)
    @app_commands.checks.has_permissions(manage_guild=True)
    @app_commands.guild_only()
    async def _clear_fa_availability(self, interaction: discord.Interaction, tier: str):
        await self.clear_checkins_by_tier(interaction.guild, tier)
        await interaction.response.send_message(
            embed=SuccessEmbed(
                description=f"Cleared all free agent availability for **{tier}**"
            )
        )

    @app_commands.command(
        name="clearallavailability",
        description="Clear free agent availability for all tiers",
    )
    @app_commands.checks.has_permissions(manage_guild=True)
    @app_commands.guild_only()
    async def _clear_all_fa_availability(self, interaction: discord.Interaction):
        await self.clear_all_checkins(interaction.guild)
        await interaction.response.send_message(
            embed=SuccessEmbed(description="Cleared all free agent availability")
        )

    # Functions

    async def checkins_by_tier(self, guild: discord.Guild, tier: str) -> list[CheckIn]:
        """Return cached list of FA check ins for a guild's tier"""
        if not self._check_ins.get(guild.id):
            return []

        return [x for x in self._check_ins[guild.id] if x["tier"] == tier]

    async def checkins(self, guild: discord.Guild) -> list[CheckIn]:
        """Return cached list of FA check ins for guild"""
        return self._check_ins.get(guild.id, [])

    async def clear_checkins_by_tier(self, guild: discord.Guild, tier: str):
        """Remove all free agent check ins for a specific tier"""
        if not self._check_ins.get(guild.id):
            return

        current = await self._get_check_ins(guild)
        new = [x for x in current if x["tier"] != tier]
        self._check_ins[guild.id] = new
        await self._save_check_ins(guild, new)

    async def clear_all_checkins(self, guild: discord.Guild):
        """Remove all free agent check ins"""
        self._check_ins[guild.id] = []
        await self._save_check_ins(guild, [])

    async def add_checkin(self, guild: discord.Guild, player: CheckIn):
        """Add free agent check in for guild"""
        current = await self._get_check_ins(guild)
        current.append(player)
        self._check_ins[guild.id] = current
        await self._save_check_ins(guild, current)

    async def remove_checkin(self, guild: discord.Guild, player: CheckIn):
        """Remove free agent check in for guild"""
        current = await self._get_check_ins(guild)
        current.remove(player)
        self._check_ins[guild.id] = current
        await self._save_check_ins(guild, current)

    async def is_checked_in(self, player: discord.Member) -> bool:
        """Check if discord.Member is checked in as FA"""
        if not self._check_ins.get(player.guild.id):
            return False
        if next(
            (x for x in self._check_ins[player.guild.id] if x["player"] == player.id),
            None,
        ):
            return True
        return False

    async def get_checkin(self, player: discord.Member) -> Optional[CheckIn]:
        """Return a CheckIn for discord.Member if it exists"""
        if not self._check_ins.get(player.guild.id):
            return None
        return next(
            (x for x in self._check_ins[player.guild.id] if x["player"] == player.id),
            None,
        )

    # API Calls

    async def free_agents(
        self, guild: discord.Guild, tier_name: str
    ) -> list[LeaguePlayer]:
        """Fetch a list of Free Agents for specified tier"""
        return await self.players(guild, status=Status.FREE_AGENT, tier_name=tier_name, limit=1000)

    async def permanent_free_agents(
        self, guild: discord.Guild, tier_name: str
    ) -> list[LeaguePlayer]:
        """Fetch a list of Permanent Free Agents for specified tier"""
        return await self.players(guild, status=Status.PERM_FA, tier_name=tier_name, limit=1000)

    # Config

    async def _get_check_ins(self, guild: discord.Guild) -> list[CheckIn]:
        return await self.config.custom("FreeAgents", guild.id).CheckIns()

    async def _save_check_ins(self, guild: discord.Guild, check_ins: list[CheckIn]):
        await self.config.custom("FreeAgents", guild.id).CheckIns.set(check_ins)
