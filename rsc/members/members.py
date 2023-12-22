import logging

import discord
from redbot.core import app_commands, commands
from rscapi import ApiClient, MembersApi
from rscapi.exceptions import ApiException
from rscapi.models.deleted import Deleted
from rscapi.models.intent_to_play_schema import IntentToPlaySchema
from rscapi.models.league_player import LeaguePlayer
from rscapi.models.member import Member
from rscapi.models.player_season_stats import PlayerSeasonStats
from rscapi.models.player_signup_schema import PlayerSignupSchema
from rscapi.models.update_member_rsc_name import UpdateMemberRSCName

from rsc.abc import RSCMixIn
from rsc.embeds import ApiExceptionErrorEmbed, ErrorEmbed, SuccessEmbed, YellowEmbed
from rsc.enums import Platform, PlayerType, Referrer, RegionPreference, Status
from rsc.exceptions import RscException
from rsc.members.views import IntentState, IntentToPlayView, SignupState, SignupView
from rsc.tiers import TierMixIn
from rsc.utils import utils

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
    @app_commands.guild_only
    async def _member_signup(self, interaction: discord.Interaction):
        guild = interaction.guild
        if not guild or not isinstance(interaction.user, discord.Member):
            return

        log.debug(f"{interaction.user} is signing up for the league")
        # Check if not a league player?
        # User prompts
        signup_view = SignupView(interaction)
        await signup_view.prompt()
        await signup_view.wait()

        if signup_view.state == SignupState.CANCELLED:
            embed = ErrorEmbed(
                title="Signup Cancelled",
                description="You have cancelled signing up for RSC. Please try again if this was a mistake.",
            )
            await interaction.edit_original_response(embed=embed, view=None)
            return
        if signup_view.state != SignupState.FINISHED:
            embed = ErrorEmbed(
                title="Signup Failed",
                description=(
                    "Signup failed for an unknown reason."
                    " Please try again, if the issue persists contact a staff member."
                ),
            )
            await interaction.edit_original_response(embed=embed, view=None)
            return

        # Process signup if state is finished
        try:
            result = await self.signup(
                guild=guild,
                member=interaction.user,
                rsc_name=signup_view.rsc_name,
                trackers=signup_view.trackers,
                player_type=signup_view.player_type,
                platform=signup_view.platform,
                referrer=signup_view.referrer,
                region_preference=signup_view.region,
                accepted_rules=True,
                accepted_match_nights=True,
            )
            log.debug(f"Signup result: {result}")
        except RscException as exc:
            if exc.status == 405:
                await interaction.edit_original_response(
                    embed=YellowEmbed(title="RSC Signup", description=exc.reason),
                    view=None,
                )
                return

            await interaction.edit_original_response(
                embed=ApiExceptionErrorEmbed(exc),
                view=None,
            )
            return

        success_embed = SuccessEmbed(
            description=(
                "You have successfully signed up for the next season of RSC!\n\n"
                "Please keep up to date with league notices for information on the upcoming Draft and Combines."
            )
        )
        await interaction.edit_original_response(embed=success_embed, view=None)

    @app_commands.command(
        name="intenttoplay", description="Declare your intent for the next RSC season"
    )
    @app_commands.guild_only
    async def _member_intent_to_play(self, interaction: discord.Interaction):
        guild = interaction.guild
        if not guild or not isinstance(interaction.user, discord.Member):
            return

        log.debug(f"{interaction.user} is signing up for the league")
        # User prompts
        intent_view = IntentToPlayView(interaction)
        await intent_view.prompt()
        await intent_view.wait()

        if intent_view.state == IntentState.CANCELLED:
            return

        if intent_view.state != IntentState.FINISHED:
            await interaction.edit_original_response(
                embed=ErrorEmbed(
                    description="Something went wrong declaring your intent to play. Please reach out to an admin."
                ),
                view=None,
            )
            return

        # Process intent if state is finished
        try:
            result = await self.declare_intent(
                guild=guild,
                member=interaction.user,
                returning=intent_view.result,
            )
            log.debug(f"Intent Result: {result}")
        except RscException as exc:
            if exc.status == 409:
                await interaction.edit_original_response(
                    embed=YellowEmbed(title="Intent to Play", description=exc.reason),
                    view=None,
                )
                return

            await interaction.edit_original_response(
                embed=ApiExceptionErrorEmbed(exc),
                view=None,
            )
            return

        if intent_view.result:
            desc = (
                "You have successfully declared your intent."
                " We are excited to have you back next season!\n\n"
                "If your situation changes before next season, please redeclare your intent."
            )
        else:
            desc = (
                "You have successfully declared your intent."
                " We are sorry to see you go and hope you return to the league soon!\n\n"
                "If you change your mind, please redeclare your intent."
            )

        embed: discord.Embed = SuccessEmbed(
            title="Intent to Play Declared", description=desc
        )
        await interaction.edit_original_response(embed=embed, view=None)

    @app_commands.command(
        name="playerinfo", description="Display league information about a player"
    )
    @app_commands.describe(player="Player discord name to query")
    @app_commands.guild_only
    async def _playerinfo(
        self, interaction: discord.Interaction, player: discord.Member
    ):
        guild = interaction.guild
        if not guild:
            return

        players = await self.players(guild, discord_id=player.id, limit=1)
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
        tier_color = await utils.tier_color_by_name(guild, p.tier.name)

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

        frole = await utils.franchise_role_from_name(guild, p.team.franchise.name)
        f_fmt = frole.mention if frole else p.team.franchise.name

        embed.add_field(name="", value="", inline=False)  # Line Break
        embed.add_field(name="Team", value=p.team.name, inline=True)
        embed.add_field(name="Franchise", value=f_fmt, inline=True)
        await interaction.response.send_message(embed=embed, ephemeral=True)

    @app_commands.command(
        name="waivers", description="Display players currently on waivers"
    )
    @app_commands.describe(tier='Waiver tier name (Ex: "Elite")')
    @app_commands.autocomplete(tier=TierMixIn.tier_autocomplete)
    @app_commands.guild_only
    async def _waivers(self, interaction: discord.Interaction, tier: str):
        guild = interaction.guild
        if not guild:
            return

        await interaction.response.defer()
        players = await self.players(guild, status=Status.WAIVERS, tier_name=tier)

        tier_color = await utils.tier_color_by_name(guild, tier)
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
            m = guild.get_member(p.player.discord_id)
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
        embed.add_field(name="End Date", value="\n".join(waiver_dates), inline=True)

        await interaction.followup.send(embed=embed)

    @app_commands.command(
        name="playerstats", description="Display RSC stats for a player"
    )
    @app_commands.describe(player="RSC Discord Member")
    @app_commands.guild_only
    async def _player_stats(
        self, interaction: discord.Interaction, player: discord.Member
    ):
        await utils.not_implemented(interaction)

    @app_commands.command(name="staff", description="Display RSC Committees and Staff")
    @app_commands.guild_only
    async def _staff_cmd(self, interaction: discord.Interaction):
        await utils.not_implemented(interaction)

    # Helper Functions

    async def league_player_from_member(
        self, guild: discord.Guild, member: Member
    ) -> LeaguePlayer | None:
        """Return `LeaguePlayer` object for the guilds league from `Member`"""
        if not member.player_leagues:
            return None
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
        region_preference: RegionPreference | None = None,
        player_type: PlayerType | None = None,
        platform: Platform | None = None,
        referrer: Referrer | None = None,
        accepted_rules: bool = True,
        accepted_match_nights: bool = True,
        executor: discord.Member | None = None,
        override: bool = False,
    ) -> LeaguePlayer:
        async with ApiClient(self._api_conf[guild.id]) as client:
            api = MembersApi(client)
            data = PlayerSignupSchema(
                league=self._league[guild.id],
                rsc_name=rsc_name,
                tracker_links=trackers,
                new_or_returning=str(player_type),
                platform=str(platform),
                referrer=str(referrer),
                region_preference=str(region_preference),
                accepted_rules=accepted_rules,
                accepted_match_nights=accepted_match_nights,
                executor=executor.id if executor else None,
                admin_override=override,
            )
            try:
                log.debug(f"Signup Data: {data}")
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
                return await api.members_stats(
                    id, self._league[guild.id], season=season
                )
            except ApiException as exc:
                raise RscException(response=exc)

    async def declare_intent(
        self,
        guild: discord.Guild,
        member: discord.Member,
        returning: bool,
        executor: discord.Member | None = None,
        admin_overrride: bool = False,
    ) -> Deleted:
        async with ApiClient(self._api_conf[guild.id]) as client:
            api = MembersApi(client)
            data = IntentToPlaySchema(
                league=self._league[guild.id],
                returning=returning,
                executor=executor.id if executor else None,
                admin_override=admin_overrride,
            )
            try:
                log.debug(f"Intent Data: {data}")
                return await api.members_intent_to_play(member.id, data)
            except ApiException as exc:
                raise RscException(response=exc)
