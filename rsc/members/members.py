import discord
import logging


from redbot.core import app_commands, checks, commands

from rscapi import ApiClient, MembersApi
from rscapi.exceptions import ApiException
from rscapi.models.tier import Tier
from rscapi.models.members_list200_response import MembersList200Response
from rscapi.models.member import Member
from rscapi.models.league_player import LeaguePlayer

from rsc.abc import RSCMixIn
from rsc.exceptions import RscException
from rsc.tiers import TierMixIn
from rsc.const import LEAGUE_ROLE, MUTED_ROLE
from rsc.embeds import ErrorEmbed, SuccessEmbed, ApiExceptionErrorEmbed
from rsc.enums import Status
from rsc.members.views import SignupView, SignupState, PlayerType, Platform, Referrer
from rsc.utils.utils import get_tier_color_by_name, get_franchise_role_from_name

from typing import List, Dict, Tuple, TypedDict, Optional

log = logging.getLogger("red.rsc.freeagents")


class MemberMixIn(RSCMixIn):
    def __init__(self):
        log.debug("Initializing MemberMixIn")
        super().__init__()

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
        tier_color = await get_tier_color_by_name(interaction.guild, p.tier.name)

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

        frole = await get_franchise_role_from_name(interaction.guild, p.team.franchise.name)
        f_fmt = frole.mention if frole else p.team.franchise.name

        # embed.add_field(name="\u200B", value="\u200B") # Line Break
        embed.add_field(name="Team", value=p.team.name, inline=True)
        embed.add_field(name="Franchise", value=f_fmt, inline=True)
        await interaction.response.send_message(embed=embed, ephemeral=True)

        



    # API

    async def members(
        self,
        guild: discord.Guild,
        rsc_name: Optional[str] = None,
        discord_username: Optional[str] = None,
        discord_id: Optional[int] = None,
        limit: int = 0,
        offset: int = 0,
    ) -> List[Member]:
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
        trackers: List[str],
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
            return await api.members_signup(member.id, data)
