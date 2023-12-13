import discord
import logging

from datetime import date

from redbot.core import app_commands, checks, commands

from rscapi import ApiClient, MembersApi
from rscapi.exceptions import ApiException
from rscapi.models.tier import Tier
from rscapi.models.members_list200_response import MembersList200Response
from rscapi.models.member import Member
from rscapi.models.update_member_rsc_name import UpdateMemberRSCName
from rscapi.models.elevated_role import ElevatedRole
from rscapi.models.league_player import LeaguePlayer
from rscapi.models.player_season_stats import PlayerSeasonStats

from rsc.abc import RSCMixIn
from rsc.exceptions import RscException
from rsc.tiers import TierMixIn
from rsc.const import LEAGUE_ROLE, MUTED_ROLE
from rsc.embeds import ErrorEmbed, SuccessEmbed, ApiExceptionErrorEmbed, BlueEmbed
from rsc.enums import Status
from rsc.members.views import SignupView, SignupState, PlayerType, Platform, Referrer
from rsc.utils import utils

from typing import List, Dict, Tuple, TypedDict, Optional

log = logging.getLogger("red.rsc.freeagents")


class MemberMixIn(RSCMixIn):
    def __init__(self):
        log.debug("Initializing MemberMixIn")
        super().__init__()

    # Listeners

    @commands.Cog.listener("on_member_join")
    async def on_join_member_processing(self, member: discord.Member):
        log.debug(f"Processing new member on_join: {member}")
        ml = await self.members(member.guild, discord_id=member.id, limit=1)
        if not ml:
            # Member does not exist, create one
            log.debug(f"{member} does not exist. Creating member in API")
            await self.create_member(member.guild, member=member)
        else:
            # Change nickname to RSC name
            m = ml.pop()
            log.debug(f"{member} already exists. Changing nickname to {m.rsc_name}")
            await member.edit(nick=m.rsc_name)

    # App Commands

    @app_commands.command(name="signup", description="Sign up for the next RSC season")
    async def _member_signup(self, interaction: discord.Interaction):
        log.debug(f"{interaction.user} is signing up for the league")
        # Check if not a league player?
        # User prompts
        signup_view = SignupView(interaction)
        await signup_view.prompt()
        await signup_view.wait()

        if signup_view.state == SignupState.FINISHED:
            embed: discord.Embed = SuccessEmbed(
                title="Signup Submitted",
                description="You have been successfully signed up for the next RSC season!",
            )
            # Process signup if state is finished
            try:
                result = await self.signup(
                    interaction.guild,
                    interaction.user,
                    signup_view.rsc_name,
                    signup_view.trackers,
                )
                log.debug(f"Signup result: {result}")
                await interaction.edit_original_response(embed=embed, view=None)
            except ApiException as exc:
                await interaction.edit_original_response(
                    embed=ApiExceptionErrorEmbed(exc=RscException(response=exc)),
                    view=None,
                )
        elif signup_view.state == SignupState.CANCELLED:
            embed = ErrorEmbed(
                title="Signup Cancelled",
                description="You have cancelled signing up for RSC. Please try again if this was a mistake.",
            )
            await interaction.edit_original_response(embed=embed, view=None)
        else:
            embed = ErrorEmbed(
                title="Signup Failed",
                description="Signup failed for an unknown reason. Please try again, if the issue persists contact a staff member.",
            )
            await interaction.edit_original_response(embed=embed, view=None)

    @app_commands.command(
        name="intenttoplay", description="Declare your intent for the next RSC season"
    )
    async def _member_intent_to_play(self, interaction: discord.Interaction):
        pass

    @app_commands.command(
        name="playerinfo", description="Display league information about a player"
    )
    @app_commands.describe(player="Player discord name to query")
    async def _playerinfo(
        self, interaction: discord.Interaction, player: discord.Member
    ):
        players = await self.players(interaction.guild, discord_id=player.id, limit=1)
        if not players:
            await interaction.response.send_message(
                embed=discord.Embed(
                    title="Player Info",
                    description=f"{player.mention} is not currently playing in the league.",
                    color=discord.Color.yellow(),
                ),
                ephemeral=True,
            )
            return

        p = players[0]
        tier_color = await utils.tier_color_by_name(interaction.guild, p.tier.name)

        embed = discord.Embed(
            title="Player Info",
            color=tier_color,
        )

        embed.add_field(name="Player", value=player.mention, inline=True)
        embed.add_field(name="Tier", value=p.tier.name, inline=True)
        embed.add_field(name="Status", value=p.status, inline=True)

        if not p.team:
            await interaction.response.send_message(embed=embed, ephemeral=True)
            return

        frole = await utils.franchise_role_from_name(interaction.guild, p.team.franchise.name)
        f_fmt = frole.mention if frole else p.team.franchise.name

        embed.add_field(name="", value="", inline=False) # Line Break
        embed.add_field(name="Team", value=p.team.name, inline=True)
        embed.add_field(name="Franchise", value=f_fmt, inline=True)
        await interaction.response.send_message(embed=embed, ephemeral=True)

    @app_commands.command(
        name="waivers", description="Display players currently on waivers"
    )
    @app_commands.describe(tier="Waiver tier name (Ex: \"Elite\")")
    @app_commands.autocomplete(tier=TierMixIn.tier_autocomplete)
    async def _waivers(self, interaction: discord.Interaction, tier: str):
        await interaction.response.defer()
        players = await self.players(
            interaction.guild, status=Status.WAIVERS, tier_name=tier
        )

        tier_color = await utils.tier_color_by_name(interaction.guild, tier)
        embed = discord.Embed(
            title="Waiver List",
            description=f"Players on waivers in **{tier}**",
            color=tier_color,
        )

        if not players:
            embed.description = f"No players on waiver list for **{tier}**"
            await interaction.followup.send(embed=embed)
            return

        players.sort(key=lambda x: x.current_mmr, reverse=True)

        waiver_dates = []
        members = []
        for p in players:
            m = interaction.guild.get_member(p.player.discord_id)
            pstr = m.mention if m else p.player.name
            members.append(pstr)
            if p.waiver_period_end_date:
                waiver_dates.append(str(p.waiver_period_end_date.date()))
            else:
                waiver_dates.append("Unknown")


        embed.add_field(name="Player", value="\n".join(members), inline=True)
        embed.add_field(
            name="MMR",
            value="\n".join([str(p.current_mmr) for p in players]),
            inline=True,
        )
        embed.add_field(name="End Date", value="\n".join([d for d in waiver_dates]), inline=True)

        await interaction.followup.send(embed=embed)


    @app_commands.command(
        name="playerstats", description="Display RSC stats for a player"
    )
    @app_commands.describe(player="RSC Discord Member")
    async def _player_stats(self, interaction: discord.Interaction, player: discord.Member):
        await utils.not_implemented(interaction)
    
    @app_commands.command(
        name="staff", description="Display RSC Committees and Staff"
    )
    async def _staff_cmd(self, interaction: discord.Interaction):
        await utils.not_implemented(interaction)
    

    # Helper Functions

    async def league_player_from_member(
        self, guild: discord.Guild, member: Member
    ) -> Optional[LeaguePlayer]:
        """Return `LeaguePlayer` object for the guilds league from `Member`"""
        for lp in member.player_leagues:
            if lp.league.id == self._league[guild.id]:
                return lp
        return None

    # API

    async def members(
        self,
        guild: discord.Guild,
        rsc_name: str | None = None,
        discord_username: str | None = None,
        discord_id: int | None = None,
        limit: int = 0,
        offset: int = 0,
    ) -> list[Member]:
        async with ApiClient(self._api_conf[guild.id]) as client:
            api = MembersApi(client)
            members = await api.members_list(
                rsc_name=rsc_name,
                discord_username=discord_username,
                discord_id=discord_id,
                limit=limit,
                offset=offset,
            )
            return members.results

    async def signup(
        self,
        guild: discord.Guild,
        member: discord.Member,
        rsc_name: str,
        trackers: list[str],
        player_type: Optional[PlayerType] = None,
        platform: Optional[Platform] = None,
        referrer: Optional[Referrer] = None,
    ) -> LeaguePlayer:
        if not trackers:
            raise ValueError(
                "You must provide at least one tracker link during sign up"
            )

        async with ApiClient(self._api_conf[guild.id]) as client:
            api = MembersApi(client)
            data = {
                "rsc_name": rsc_name,
                "tracker_links": trackers,
                "league": self._league[guild.id],
            }
            try:
                return await api.members_signup(member.id, data)
            except ApiException as exc:
                raise RscException(response=exc)

    async def create_member(
        self,
        guild: discord.Guild,
        member: discord.Member,
        rsc_name: str | None = None,
    ) -> Member:
        async with ApiClient(self._api_conf[guild.id]) as client:
            api = MembersApi(client)
            data = Member(
                username=member.name,
                discord_id=member.id,
                rsc_name=rsc_name or member.display_name,
            )
            log.debug(f"Member Creation Data: {data}")
            try:
                return await api.members_create(data)
            except ApiException as exc:
                raise RscException(response=exc)

    async def delete_member(
        self,
        guild: discord.Guild,
        member: discord.Member,
    ):
        async with ApiClient(self._api_conf[guild.id]) as client:
            api = MembersApi(client)
            try:
                await api.members_delete(member.id)
            except ApiException as exc:
                raise RscException(response=exc)


    async def change_member_name(
        self,
        guild: discord.Guild,
        id: int,
        name: str,
    ) -> Member:
        async with ApiClient(self._api_conf[guild.id]) as client:
            api = MembersApi(client)
            try:
                data = UpdateMemberRSCName(name=name)
                log.debug(f"Name Change Data: {data}")
                return await api.members_name_change(id, data)
            except ApiException as exc:
                raise RscException(response=exc)


    async def player_stats(
        self,
        guild: discord.Guild,
        id: int,
        season: int | None,
    ) -> PlayerSeasonStats:
        async with ApiClient(self._api_conf[guild.id]) as client:
            api = MembersApi(client)
            try:
                return await api.members_stats(id, self._league[guild.id], season=season)
            except ApiException as exc:
                raise RscException(response=exc)