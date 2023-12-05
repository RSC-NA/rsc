import discord
import logging


from redbot.core import app_commands, checks, commands

from rscapi import ApiClient, MembersApi
from rscapi.exceptions import ApiException
from rscapi.models.tier import Tier
from rscapi.models.members_list200_response import MembersList200Response
from rscapi.models.member import Member
from rscapi.models.elevated_role import ElevatedRole
from rscapi.models.league_player import LeaguePlayer

from rsc.abc import RSCMixIn
from rsc.exceptions import RscException
from rsc.tiers import TierMixIn
from rsc.const import LEAGUE_ROLE, MUTED_ROLE
from rsc.embeds import ErrorEmbed, SuccessEmbed, ApiExceptionErrorEmbed, BlueEmbed
from rsc.enums import Status
from rsc.members.views import SignupView, SignupState, PlayerType, Platform, Referrer
from rsc.utils.utils import get_tier_color_by_name, get_franchise_role_from_name

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


    # Privileged Commands

    _members = app_commands.Group(
        name="members",
        description="Manage RSC members",
        guild_only=True,
        default_permissions=discord.Permissions(manage_guild=True),
    )

    @_members.command(name="create", description="Create an RSC member in the API")
    @app_commands.describe(
        member="Discord member being added",
        rsc_name="RSC player name (Defaults to members display name)",
    )
    async def _member_create(
        self,
        interaction: discord.Interaction,
        member: discord.Member,
        rsc_name: Optional[str] = None,
    ):
        try:
            lp = await self.create_member(
                interaction.guild,
                member=member,
                rsc_name=rsc_name or member.display_name,
            )
        except RscException as exc:
            await interaction.response.send_message(
                embed=ApiExceptionErrorEmbed(exc), ephemeral=True
            )
            return

        # Change nickname if specified
        if rsc_name:
            await member.edit(nick=rsc_name)

        await interaction.response.send_message(
            embed=SuccessEmbed(
                description=f"{member.mention} has been created in the RSC API."
            ),
            ephemeral=True,
        )

    @_members.command(name="delete", description="Delete an RSC member in the API")
    async def _member_delete(
        self, interaction: discord.Interaction, member: discord.Member
    ):
        try:
            await self.delete_member(interaction.guild, member=member)
        except RscException as exc:
            await interaction.response.send_message(
                embed=ApiExceptionErrorEmbed(exc), ephemeral=True
            )
            return
        await interaction.response.send_message(
            embed=SuccessEmbed(
                description=f"{member.mention} has been deleted from the RSC API."
            ),
            ephemeral=True,
        )

    @_members.command(
        name="list", description="Fetch a list of members based on specified criteria."
    )
    @app_commands.describe(
        rsc_name="RSC in-game player name (Do not include prefix)",
        discord_username="Player discord username without discriminator",
        discord_id="Player discord ID",
        limit="Number of results to return (Default: 10, Max: 64)",
        offset="Return results starting at specified offset (Default: 0)",
    )
    async def _member_list(
        self,
        interaction: discord.Interaction,
        rsc_name: Optional[str] = None,
        discord_username: Optional[str] = None,
        discord_id: Optional[int] = None,
        limit: app_commands.Range[int, 1, 64] = 10,
        offset: app_commands.Range[int, 0, 64] = 0,
    ):
        if not (rsc_name or discord_username or discord_id):
            await interaction.response.send_message(
                "You must specify at least one search option.", ephemeral=True
            )
            return
        await interaction.response.defer(ephemeral=True)
        ml = await self.members(
            interaction.guild,
            rsc_name=rsc_name,
            discord_username=discord_username,
            discord_id=discord_id,
            limit=limit,
            offset=offset,
        )

        league_id = self._league[interaction.guild.id]
        m_fmt = []
        for m in ml:
            x = interaction.guild.get_member(m.discord_id)
            l: LeaguePlayer = next(
                (i for i in m.player_leagues if i.league.id == league_id), None
            )
            m_fmt.append(
                (
                    x.mention if x else m.rsc_name,
                    m.discord_id,
                    Status(l.status).full_name() if l else "Spectator",
                )
            )

        embed = BlueEmbed(
            title="RSC Member Results",
            description="The following members matched the specified criteria",
        )
        embed.add_field(
            name="Member", value="\n".join([x[0] for x in m_fmt]), inline=True
        )
        embed.add_field(
            name="ID", value="\n".join([str(x[1]) for x in m_fmt]), inline=True
        )
        embed.add_field(
            name="Status", value="\n".join([x[2] for x in m_fmt]), inline=True
        )

        await interaction.followup.send(embed=embed, ephemeral=True)

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

        frole = await get_franchise_role_from_name(
            interaction.guild, p.team.franchise.name
        )
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
            try:
                return await api.members_signup(member.id, data)
            except ApiException as exc:
                raise RscException(response=exc)

    async def create_member(
        self,
        guild: discord.Guild,
        member: discord.Member,
        rsc_name: Optional[str] = None,
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
