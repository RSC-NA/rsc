import logging
from datetime import datetime, time, timedelta

import discord
from discord.ext import tasks
from redbot.core import Config, app_commands
from rscapi.models.league_player import LeaguePlayer

from rsc.abc import RSCMixIn
from rsc.embeds import ErrorEmbed, SuccessEmbed
from rsc.enums import Status
from rsc.freeagents.views import CheckInView, CheckOutView
from rsc.tiers import TierMixIn
from rsc.types import CheckIn
from rsc.utils import utils

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
                log.error(f"Unable to resolve guild during expire FA check in loop: {k}")
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

    # Groups

    _free_agent_group = app_commands.Group(
        name="freeagent",
        description="List of free agent commands for match check in",
        guild_only=True,
    )

    # Commands

    @app_commands.command(  # type: ignore[type-var]
        name="freeagents", description="List free agents in a specified tier"
    )
    @app_commands.describe(tier='Free agent tier (Ex: "Elite")')
    @app_commands.autocomplete(tier=TierMixIn.tier_autocomplete)  # type: ignore[type-var]
    @app_commands.guild_only
    async def _free_agents(self, interaction: discord.Interaction, tier: str):
        guild = interaction.guild
        if not guild:
            return

        await interaction.response.defer()

        tier = tier.capitalize()
        if not await self.is_valid_tier(guild, tier):
            await interaction.followup.send(
                embed=ErrorEmbed(description=f"**{tier}** is not a valid tier."),
            )
            return
        free_agents = await self.free_agents(guild, tier)
        free_agents.extend(await self.permanent_free_agents(guild, tier))

        fa_fmt_list: list[str] = []
        for fa in free_agents:
            log.debug(fa.player)
            if not fa.player.discord_id:
                log.warning(f"FA player has no discord_id: {fa.id}")
                continue

            # Skip if they aren't in the guild. Could retire...
            fmember = guild.get_member(fa.player.discord_id)
            if not fmember:
                continue

            fstr = fmember.display_name
            if fa.status == Status.PERM_FA:
                fstr += " (Permanent FA)"
            fa_fmt_list.append(fstr)
        data = "\n".join(fa_fmt_list)

        tier_role = await utils.role_by_name(guild, tier)

        embed = discord.Embed(
            title=f"{tier} Free Agents",
            description=f"```\n{data}\n```",
            color=tier_role.color if tier_role else discord.Color.blue(),
        )

        await interaction.followup.send(embed=embed)

    @_free_agent_group.command(  # type: ignore[type-var]
        name="checkin",
        description="Check in as an available free agent for the current match day",
    )
    @app_commands.guild_only
    async def _fa_checkin_cmd(self, interaction: discord.Interaction):
        guild = interaction.guild
        if not guild or not isinstance(interaction.user, discord.Member):
            return

        # Check if this player already checked in
        if await self.is_checked_in(interaction.user):
            return await interaction.response.send_message(
                embed=ErrorEmbed(
                    title="Check In Error",
                    description="You are already checked in for today",
                ),
                ephemeral=True,
            )

        # Check if match day
        if not await self.is_match_day(guild):
            return await interaction.response.send_message(
                embed=ErrorEmbed(title="Check In Error", description="There are no matches today!"),
                ephemeral=True,
            )

        # Check if player is an FA in the guilds league
        players = await self.players(
            guild,
            discord_id=interaction.user.id,
            limit=1,
        )

        # Check if member exists in RSC
        if not players:
            return await interaction.response.send_message(
                embed=ErrorEmbed(
                    title="Check In Error",
                    description="You are not currently a member of this RSC league",
                ),
                ephemeral=True,
            )

        player: LeaguePlayer = players[0]

        # Check if player is a Free Agent or PermFA
        if player.status not in (Status.FREE_AGENT, Status.PERM_FA, Status.WAIVERS):
            return await interaction.response.send_message(
                embed=ErrorEmbed(
                    title="Check In Error",
                    description="You are not a free agent.",
                ),
                ephemeral=True,
            )

        # More player validation
        if not (player.tier and player.tier.name):
            return await interaction.response.send_message(
                embed=ErrorEmbed(
                    title="Check In Error",
                    description="API does not have a tier associated with you. Please open a modmail.",
                ),
                ephemeral=True,
            )

        # Tier
        tier_role = await utils.role_by_name(guild, player.tier.name)
        tier_color = None
        if tier_role:
            tier_color = tier_role.color

        # Prompt for check in
        checkin_view = CheckInView(interaction, tier=player.tier.name, color=tier_color)
        await checkin_view.prompt()

        if checkin_view.result:
            tz = await self.timezone(guild)
            checkin = CheckIn(
                date=str(datetime.now(tz)),
                player=interaction.user.id,
                tier=player.tier.name,
                visible=True,
            )
            await self.add_checkin(guild, checkin)

    @_free_agent_group.command(  # type: ignore[type-var]
        name="checkout",
        description="Check out as an available free agent for the current match day",
    )
    @app_commands.guild_only
    async def _fa_checkout_cmd(self, interaction: discord.Interaction):
        guild = interaction.guild
        if not guild or not isinstance(interaction.user, discord.Member):
            return

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
            await self.remove_checkin(guild, checkin)

    @_free_agent_group.command(  # type: ignore[type-var]
        name="availability",
        description="Get list of available free agents for specified tier",
    )
    @app_commands.describe(tier='Free agent tier (Ex: "Elite")')
    @app_commands.autocomplete(tier=TierMixIn.tier_autocomplete)  # type: ignore[type-var]
    @app_commands.guild_only
    async def _fa_availability_cmd(self, interaction: discord.Interaction, tier: str):
        guild = interaction.guild
        if not guild:
            return

        # Auto fix capitalization mistakes
        tier = tier.capitalize()
        checkins = await self.checkins_by_tier(guild, tier)
        tier_color = await utils.tier_color_by_name(guild, tier) or discord.Color.blue()

        # Filter out anyone who isn't in the guild
        available = []
        for c in checkins:
            v = c.get("visible")
            # In the event that a player doesn't have the attribute
            # Yes this happened... the first day I wrote this code.
            if v is None:
                c["visible"] = True
            # Skip if not visible (False)
            if not v:
                continue
            m = guild.get_member(c["player"])
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

    @app_commands.command(  # type: ignore[type-var]
        name="clearavailability",
        description="Clear free agent availability for a specified tier",
    )
    @app_commands.describe(tier='Free agent tier (Ex: "Elite")')
    @app_commands.autocomplete(tier=TierMixIn.tier_autocomplete)  # type: ignore[type-var]
    @app_commands.checks.has_permissions(manage_guild=True)
    @app_commands.guild_only
    async def _clear_fa_availability(self, interaction: discord.Interaction, tier: str):
        if not interaction.guild:
            return

        tier = tier.capitalize()
        await self.clear_checkins_by_tier(interaction.guild, tier)
        await interaction.response.send_message(embed=SuccessEmbed(description=f"Cleared all free agent availability for **{tier}**"))

    @app_commands.command(  # type: ignore[type-var]
        name="clearallavailability",
        description="Clear free agent availability for all tiers",
    )
    @app_commands.checks.has_permissions(manage_guild=True)
    @app_commands.guild_only
    async def _clear_all_fa_availability(self, interaction: discord.Interaction):
        if not interaction.guild:
            return

        await self.clear_all_checkins(interaction.guild)
        await interaction.response.send_message(embed=SuccessEmbed(description="Cleared all free agent availability"))

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

    async def update_freeagent_visibility(self, guild: discord.Guild, player: discord.Member, visibility: bool):
        """Remove free agent check in for guild"""
        log.debug(f"Changing checkin visibility for {player.id} to {visibility}")
        checkins = await self._get_check_ins(guild)
        log.debug(f"Current Checkins: {checkins}")
        for c in checkins:
            if c["player"] == player.id:
                c["visible"] = visibility
        log.debug(f"New Checkins: {checkins}")
        self._check_ins[guild.id] = checkins
        await self._save_check_ins(guild, checkins)

    async def is_checked_in(self, player: discord.Member) -> bool:
        """Check if discord.Member is checked in as FA"""
        if not self._check_ins.get(player.guild.id):
            return False
        return bool(next((x for x in self._check_ins[player.guild.id] if x["player"] == player.id), None))

    async def get_checkin(self, player: discord.Member) -> CheckIn | None:
        """Return a CheckIn for discord.Member if it exists"""
        if not self._check_ins.get(player.guild.id):
            return None
        return next(
            (x for x in self._check_ins[player.guild.id] if x["player"] == player.id),
            None,
        )

    # API Calls

    async def free_agents(self, guild: discord.Guild, tier_name: str) -> list[LeaguePlayer]:
        """Fetch a list of Free Agents for specified tier"""
        return await self.players(guild, status=Status.FREE_AGENT, tier_name=tier_name, limit=1000)

    async def permanent_free_agents(self, guild: discord.Guild, tier_name: str) -> list[LeaguePlayer]:
        """Fetch a list of Permanent Free Agents for specified tier"""
        return await self.players(guild, status=Status.PERM_FA, tier_name=tier_name, limit=1000)

    # Config

    async def _get_check_ins(self, guild: discord.Guild) -> list[CheckIn]:
        return await self.config.custom("FreeAgents", str(guild.id)).CheckIns()

    async def _save_check_ins(self, guild: discord.Guild, check_ins: list[CheckIn]):
        await self.config.custom("FreeAgents", str(guild.id)).CheckIns.set(check_ins)
