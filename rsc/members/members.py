import logging
from typing import cast

import discord
from redbot.core import app_commands, commands
from rscapi import ApiClient, MembersApi
from rscapi.exceptions import ApiException
from rscapi.models.activity_check import ActivityCheck
from rscapi.models.deleted import Deleted
from rscapi.models.intent_to_play_schema import IntentToPlaySchema
from rscapi.models.league_player import LeaguePlayer
from rscapi.models.member import Member
from rscapi.models.member_transfer_schema import MemberTransferSchema
from rscapi.models.name_change_history import NameChangeHistory
from rscapi.models.player_activity_check_schema import PlayerActivityCheckSchema
from rscapi.models.player_season_stats import PlayerSeasonStats
from rscapi.models.player_signup_schema import PlayerSignupSchema
from rscapi.models.update_member_rsc_name import UpdateMemberRSCName

from rsc.abc import RSCMixIn
from rsc.embeds import (
    ApiExceptionErrorEmbed,
    BlueEmbed,
    ErrorEmbed,
    GreenEmbed,
    OrangeEmbed,
    SuccessEmbed,
    YellowEmbed,
)
from rsc.enums import Platform, PlayerType, Referrer, RegionPreference, Status
from rsc.exceptions import LeagueNotConfigured, RscException
from rsc.franchises import FranchiseMixIn
from rsc.logs import GuildLogAdapter
from rsc.members.views import (
    IntentState,
    IntentToPlayView,
    PlayerInfoView,
    SignupState,
    SignupView,
)
from rsc.teams import TeamMixIn
from rsc.tiers import TierMixIn
from rsc.utils import utils

logger = logging.getLogger("red.rsc.freeagents")
log = GuildLogAdapter(logger)


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

    # App Groups

    _intent = app_commands.Group(
        name="intent",
        description="Declare or check status of player intent to play",
        guild_only=True,
    )

    # App Commands

    @app_commands.command(name="signupstatus", description="Check your status for the next RSC season")  # type: ignore
    @app_commands.guild_only
    async def _member_signup_status(self, interaction: discord.Interaction):
        guild = interaction.guild
        if not guild:
            return

        if not isinstance(interaction.user, discord.Member):
            return

        player = interaction.user

        await interaction.response.defer(ephemeral=True)

        try:
            next_season = await self.next_season(guild)
        except LeagueNotConfigured:
            return await interaction.followup.send(
                embed=YellowEmbed(
                    title="Not Configured",
                    description="League ID has not been configured for this guild.",
                )
            )
        except RscException as exc:
            return await interaction.followup.send(embed=ApiExceptionErrorEmbed(exc))

        if not next_season:
            return await interaction.followup.send(
                embed=YellowEmbed(
                    title="Intent To Play Status",
                    description="The next season of RSC has not started yet.",
                )
            )

        if not next_season.id:
            return await interaction.followup.send(
                embed=ErrorEmbed(
                    description="API returned a Season without an ID. Please open a modmail ticket."
                )
            )

        log.debug(f"Player: {player.display_name} Discord ID: {player.id}")
        lp_list = await self.players(
            guild=guild, season=next_season.id, discord_id=player.id, limit=1
        )
        if not lp_list:
            return await interaction.followup.send(
                embed=YellowEmbed(
                    title="Sign-up Status",
                    description="You are currently **not** signed up for the league.",
                )
            )

        lp = lp_list.pop(0)

        log.debug(f"Player Status: {lp.status}")

        if lp.status in (
            Status.FREE_AGENT,
            Status.ROSTERED,
            Status.UNSIGNED_GM,
            Status.IR,
            Status.AGMIR,
            Status.RENEWED,
        ):
            return await interaction.followup.send(
                embed=YellowEmbed(
                    title="Sign-up Status",
                    description="You are already in the league. Please declare your intent to play instead.",
                )
            )

        if lp.status != Status.DRAFT_ELIGIBLE:
            return await interaction.followup.send(
                embed=YellowEmbed(
                    title="Sign-up Status",
                    description="You are currently **not** signed up for the league.",
                )
            )

        await interaction.followup.send(
            embed=GreenEmbed(
                title="Sign-up Status",
                description="You are **signed up** for the next season of RSC.",
            )
        )

    @_intent.command(name="status", description="Display intent to play status for next season")  # type: ignore
    @app_commands.guild_only
    async def _intents_status_cmd(self, interaction: discord.Interaction):
        guild = interaction.guild
        if not guild:
            return
        if not isinstance(interaction.user, discord.Member):
            return

        await interaction.response.defer(ephemeral=True)

        try:
            next_season = await self.next_season(guild)
        except LeagueNotConfigured:
            return await interaction.followup.send(
                embed=YellowEmbed(
                    title="Not Configured",
                    description="League ID has not been configured for this guild.",
                )
            )
        except RscException as exc:
            return await interaction.followup.send(embed=ApiExceptionErrorEmbed(exc))

        if not next_season:
            return await interaction.followup.send(
                embed=YellowEmbed(
                    title="Intent To Play Status",
                    description="The next season of RSC has not started yet.",
                )
            )

        if not next_season.id:
            return await interaction.followup.send(
                embed=ErrorEmbed(
                    description="API returned a Season without an ID. Please open a modmail ticket."
                )
            )

        intent_list = await self.player_intents(
            guild, season_id=next_season.id, player=interaction.user
        )

        if not intent_list:
            return await interaction.followup.send(
                embed=OrangeEmbed(
                    title="Intent Not Found",
                    description="You are not currently a league player or no intent information was found. Did you mean to sign up instead?",
                )
            )

        intent = intent_list.pop(0)

        embed = BlueEmbed(title="Intent to Play Status")
        if intent.returning:
            embed.description = "You are **returning** to the league next season"
        elif not intent.returning and not intent.missing:
            embed.description = "You are **not returning** to the league next season"
        else:
            embed.description = (
                "You have **not submitted** your intent status for next season"
            )
            embed.colour = discord.Color.yellow()

        await interaction.followup.send(embed=embed)

    @_intent.command(name="search", description="Search for intent to play status (Limit: 50)")  # type: ignore
    @app_commands.autocomplete(
        franchise=FranchiseMixIn.franchise_autocomplete,
        team=TeamMixIn.teams_autocomplete,
    )
    @app_commands.describe(
        player="Discord member to search",
        missing="Display missing intents",
        returning="Display returning or not intents",
        franchise="Filter by franchise name",
        team="Filter by team name",
    )
    @app_commands.guild_only
    async def _intents_search_cmd(
        self,
        interaction: discord.Interaction,
        player: discord.Member | None = None,
        missing: bool | None = None,
        returning: bool | None = None,
        franchise: str | None = None,
        team: str | None = None,
    ):
        guild = interaction.guild
        if not guild:
            return
        if not isinstance(interaction.user, discord.Member):
            return

        if not (player or missing is None or returning is None or franchise or team):
            return await interaction.response.send_message(
                embed=ErrorEmbed(description="You must provide one search option."),
                ephemeral=True,
            )

        await interaction.response.defer(ephemeral=True)

        try:
            next_season = await self.next_season(guild)
            log.debug(f"Next Season: {next_season}")
        except LeagueNotConfigured:
            return await interaction.followup.send(
                embed=YellowEmbed(
                    title="Not Configured",
                    description="League ID has not been configured for this guild.",
                )
            )
        except RscException as exc:
            return await interaction.followup.send(embed=ApiExceptionErrorEmbed(exc))

        if not next_season:
            return await interaction.followup.send(
                embed=YellowEmbed(
                    title="Intent To Play Results",
                    description="The next season of RSC has not started yet.",
                )
            )

        if not next_season.id:
            return await interaction.followup.send(
                embed=ErrorEmbed(
                    description="API returned a Season without an ID. Please open a modmail ticket."
                )
            )

        if not next_season.number:
            return await interaction.followup.send(
                embed=ErrorEmbed(
                    description="API returned a Season without a season number. Please open a modmail ticket."
                )
            )

        intent_list = await self.player_intents(
            guild,
            season_id=next_season.id,
            player=player,
            returning=returning,
            missing=missing,
        )
        log.debug(f"Intent Length: {len(intent_list)}")

        if not intent_list:
            return await interaction.followup.send(
                embed=YellowEmbed(
                    title="Intent to Play Results",
                    description="No intent to play data found for criteria.",
                )
            )

        # Get last season
        last_season = next_season.number - 1
        log.debug(f"Last Season: {last_season}")

        # Filter by season responded in
        intents = [i for i in intent_list if i.season and i.season >= last_season]

        # Filter by franchise
        if franchise:
            intents = [
                i
                for i in intents
                if i.player
                and i.player.franchise
                and i.player.franchise.lower() == franchise.lower()
            ]

        # Filter by team
        if team:
            intents = [
                i
                for i in intents
                if i.player and i.player.team and i.player.team.lower() == team.lower()
            ]

        # Filter by returning value
        if returning is True or returning is False:
            intents = [i for i in intents if i.returning == returning]

        # Filter by missing value
        if missing is True or missing is False:
            intents = [i for i in intents if i.missing == missing]

        if not intents:
            return await interaction.followup.send(
                embed=YellowEmbed(
                    title="Intent to Play Results",
                    description="No intent to play data found for criteria.",
                )
            )

        # Limit to max of 50
        total_results = len(intents)
        intents = intents[:50]
        log.debug(f"Filtered Intent Length: {len(intents)}")

        intent_dict = {}
        for i in intents:
            # Fetch member
            if not (i.player and i.player.player.discord_id):
                log.debug("Player has no name or discord ID")
                continue
            m = guild.get_member(i.player.player.discord_id)
            if not m:
                log.debug(
                    f"Couldn't find member in guild: {i.player.player.rsc_name} ({i.player.player.discord_id})"
                )
                continue

            if i.returning:
                intent_dict[m.mention] = "Returning"
            elif not i.returning and not i.missing:
                intent_dict[m.mention] = "Not Returning"
            elif i.missing:
                intent_dict[m.mention] = "Missing"
            else:
                log.warning(
                    f"Unknown intent status for player: {i.player.player.discord_id}"
                )

        embed = BlueEmbed(
            title="Intent to Play Results",
            description="Displaying intent to play status for specified criteria.",
        )

        embed.add_field(name="Player", value="\n".join(intent_dict.keys()), inline=True)
        embed.add_field(
            name="Status",
            value="\n".join(intent_dict.values()),
            inline=True,
        )

        embed.set_footer(text=f"Displaying {len(intents)}/{total_results} results")

        await interaction.followup.send(embed=embed)

    @_intent.command(name="declare", description="Declare your intent to play next season of RSC")  # type: ignore
    @app_commands.guild_only
    async def _intents_declare_cmd(self, interaction: discord.Interaction):
        guild = interaction.guild
        if not guild or not isinstance(interaction.user, discord.Member):
            return

        log.debug(f"{interaction.user} is signing up for the league")
        # User prompts
        intent_view = IntentToPlayView(interaction)
        await intent_view.prompt()
        await intent_view.wait()

        match intent_view.state:
            case IntentState.CANCELLED:
                return
            case IntentState.FINISHED:
                log.debug("Intent view is in finished state.")
            case _:
                await interaction.edit_original_response(
                    embed=ErrorEmbed(
                        description="Something went wrong declaring your intent to play. Please submit a modmail for assistance."
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

    @app_commands.command(name="signup", description="Sign up for the next RSC season")  # type: ignore
    @app_commands.guild_only
    async def _member_signup(self, interaction: discord.Interaction):
        guild = interaction.guild
        if not guild or not isinstance(interaction.user, discord.Member):
            return

        log.debug(f"{interaction.user} is signing up for the league")

        # User prompts
        signup_view = SignupView(interaction)
        await signup_view.prompt()

        # Create a member just in case
        try:
            await self.create_member(
                guild, interaction.user, rsc_name=interaction.user.display_name
            )
        except RscException as exc:
            log.warning(f"MemberCreate exception during sign-up: {exc.response.body}")
            pass

        # Wait for embed finish.
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

        # Filter empty new lines
        tracker_list = list(filter(None, signup_view.trackers))

        # Process signup if state is finished
        try:
            result = await self.signup(
                guild=guild,
                member=interaction.user,
                rsc_name=signup_view.rsc_name,
                trackers=tracker_list,
                player_type=signup_view.player_type,
                platform=signup_view.platform,
                referrer=signup_view.referrer,
                region_preference=signup_view.region,
                accepted_rules=True,
                accepted_match_nights=True,
            )
            log.debug(f"Signup result: {result}")
        except RscException as exc:
            match exc.status:
                case 409:
                    return await interaction.edit_original_response(
                        embed=YellowEmbed(
                            title="RSC Sign-up",
                            description="You are already signed up for the league. Please use `/intent declare` to declare your intent for next season.",
                        ),
                        view=None,
                    )
                case 405:
                    return await interaction.edit_original_response(
                        embed=YellowEmbed(title="RSC Sign-up", description=exc.reason),
                        view=None,
                    )
                case _:
                    return await interaction.edit_original_response(
                        embed=ApiExceptionErrorEmbed(exc),
                        view=None,
                    )

        success_embed = SuccessEmbed(
            description=(
                "You have successfully signed up for the next season of RSC!\n\n"
                "Please keep up to date with league notices for information on the upcoming Draft and Combines."
            )
        )
        await interaction.edit_original_response(embed=success_embed, view=None)

    @app_commands.command(name="permfa", description="Sign up as an permanent free agent")  # type: ignore
    @app_commands.guild_only
    async def _member_permfa_signup(self, interaction: discord.Interaction):
        guild = interaction.guild
        if not guild or not isinstance(interaction.user, discord.Member):
            return

        log.debug(f"{interaction.user} is signing up as PermFA")

        # User prompts
        signup_view = SignupView(interaction)
        await signup_view.prompt()

        # Create a member just in case
        try:
            await self.create_member(
                guild, interaction.user, rsc_name=interaction.user.display_name
            )
        except RscException as exc:
            log.warning(
                f"MemberCreate exception during PermFA sign-up: {exc.response.body}"
            )

        # Wait for embed finish.
        await signup_view.wait()

        if signup_view.state == SignupState.CANCELLED:
            embed = ErrorEmbed(
                title="Signup Cancelled",
                description="You have cancelled signing up for RSC. Please try again if this was a mistake.",
            )
            return await interaction.edit_original_response(embed=embed, view=None)
        if signup_view.state != SignupState.FINISHED:
            embed = ErrorEmbed(
                title="Signup Failed",
                description=(
                    "Signup failed for an unknown reason."
                    " Please try again, if the issue persists contact a staff member."
                ),
            )
            return await interaction.edit_original_response(embed=embed, view=None)

        # Filter empty new lines
        tracker_list = list(filter(None, signup_view.trackers))

        # Process signup if state is finished
        try:
            result = await self.permfa_signup(
                guild=guild,
                member=interaction.user,
                rsc_name=signup_view.rsc_name,
                trackers=tracker_list,
                player_type=signup_view.player_type,
                platform=signup_view.platform,
                referrer=signup_view.referrer,
                region_preference=signup_view.region,
                accepted_rules=True,
                accepted_match_nights=True,
            )
            log.debug(f"Signup result: {result}")
        except RscException as exc:
            match exc.status:
                case 409:
                    return await interaction.edit_original_response(
                        embed=YellowEmbed(
                            title="RSC PermFA Sign-up",
                            description="You are already signed up as a permanent free agent.",
                        ),
                        view=None,
                    )
                case 405:
                    return await interaction.edit_original_response(
                        embed=YellowEmbed(
                            title="RSC PermFA Sign-up", description=exc.reason
                        ),
                        view=None,
                    )
                case _:
                    return await interaction.edit_original_response(
                        embed=ApiExceptionErrorEmbed(exc),
                        view=None,
                    )

        success_embed = SuccessEmbed(
            description=(
                "You have successfully signed up as a permenent free agent in RSC!\n\n"
                "Please be patient while we process your request."
            )
        )
        await interaction.edit_original_response(embed=success_embed, view=None)

    @app_commands.command(  # type: ignore
        name="playerinfo", description="Display league information about a player"
    )
    @app_commands.describe(player="Player discord name to query")
    @app_commands.guild_only
    async def _playerinfo_cmd(
        self, interaction: discord.Interaction, player: discord.Member
    ):
        guild = interaction.guild
        if not guild:
            return

        await interaction.response.defer(ephemeral=True)
        players = await self.players(guild, discord_id=player.id, limit=1)
        if not players:
            await interaction.followup.send(
                embed=YellowEmbed(
                    title="Player Info",
                    description=f"{player.mention} is not currently playing in the league.",
                )
            )
            return

        p = players.pop()

        if not p.status:
            await interaction.followup.send(
                embed=YellowEmbed(
                    title="Player Info",
                    description=f"{player.mention} has unknown or no league status. Please submit a modmail.",
                )
            )
            return

        embed = BlueEmbed(title=f"Player Info: {p.player.name}")
        embed.add_field(name="Player", value=player.mention, inline=True)

        if p.tier and p.tier.name:
            tier_color = await utils.tier_color_by_name(guild, p.tier.name)
            embed.colour = tier_color
            embed.add_field(name="Tier", value=p.tier.name, inline=True)

        embed.add_field(name="Status", value=Status(p.status).full_name, inline=True)

        embed.add_field(name="", value="", inline=False)  # Line Break

        if p.team:
            embed.add_field(name="Team", value=p.team.name, inline=True)

        if (
            p.team
            and p.team.franchise
            and p.team.franchise.name
            and p.team.franchise.id
        ):
            frole = await utils.franchise_role_from_name(guild, p.team.franchise.name)
            f_fmt = frole.mention if frole else p.team.franchise.name
            embed.add_field(name="Franchise", value=f_fmt, inline=True)

            flogo = await self.franchise_logo(guild, p.team.franchise.id)
            if flogo:
                embed.set_thumbnail(url=flogo)

        if not embed.thumbnail.url and player.avatar:
            embed.set_thumbnail(url=player.avatar.url)

        if p.team and p.team.name and p.team.franchise and p.team.franchise.name:
            playerinfo_view = PlayerInfoView(
                mixin=self,
                player=player,
                team=p.team.name,
                franchise=p.team.franchise.name,
            )
            await interaction.followup.send(embed=embed, view=playerinfo_view)
        else:
            await interaction.followup.send(embed=embed)

    @app_commands.command(  # type: ignore
        name="waivers", description="Display players currently on waivers"
    )
    @app_commands.describe(tier='Waiver tier name (Ex: "Elite")')
    @app_commands.autocomplete(tier=TierMixIn.tier_autocomplete)  # type: ignore
    @app_commands.guild_only
    async def _waivers(self, interaction: discord.Interaction, tier: str):
        guild = interaction.guild
        if not guild:
            return

        await interaction.response.defer()

        tier = tier.capitalize()
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

        players.sort(key=lambda x: cast(str, x.player.name), reverse=True)

        waiver_dates = []
        members = []
        for p in players:
            m = None
            if p.player.discord_id:
                m = guild.get_member(p.player.discord_id)
            pstr = m.mention if m else p.player.name
            members.append(pstr)
            if p.waiver_period_end_date:
                waiver_dates.append(str(p.waiver_period_end_date.date()))
            else:
                waiver_dates.append("Unknown")

        embed.add_field(name="Player", value="\n".join(members), inline=True)
        embed.add_field(name="End Date", value="\n".join(waiver_dates), inline=True)

        await interaction.followup.send(embed=embed)

    @app_commands.command(name="staff", description="Display RSC Committees and Staff")  # type: ignore
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
            try:
                members = await api.members_list(
                    rsc_name=rsc_name,
                    discord_username=discord_username,
                    discord_id=discord_id,
                    limit=limit,
                    offset=offset,
                )
                return members.results
            except ApiException as exc:
                raise RscException(exc)

    async def paged_members(
        self,
        guild: discord.Guild,
        rsc_name: str | None = None,
        discord_username: str | None = None,
        discord_id: int | None = None,
        per_page: int = 100,
    ):
        offset = 0
        while True:
            async with ApiClient(self._api_conf[guild.id]) as client:
                api = MembersApi(client)
                try:
                    members = await api.members_list(
                        rsc_name=rsc_name,
                        discord_username=discord_username,
                        discord_id=discord_id,
                        limit=per_page,
                        offset=offset,
                    )

                    if not members:
                        break

                    if not members.results:
                        break

                    for member in members.results:
                        yield member

                    if not members.next:
                        break

                    offset += per_page
                except ApiException as exc:
                    raise RscException(exc)

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
        player: discord.Member,
        season: int | None = None,
        postseason: bool = False,
    ) -> PlayerSeasonStats:
        async with ApiClient(self._api_conf[guild.id]) as client:
            api = MembersApi(client)
            try:
                if postseason:
                    return await api.members_postseason_stats(
                        player.id, self._league[guild.id], season=season
                    )
                else:
                    return await api.members_stats(
                        player.id, self._league[guild.id], season=season
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

    async def permfa_signup(
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
                log.debug(f"PermFA Signup Data: {data}")
                return await api.members_permfa_signup(member.id, data)
            except ApiException as exc:
                raise RscException(response=exc)

    async def activity_check(
        self,
        guild: discord.Guild,
        player: discord.Member,
        returning_status: bool,
        executor: discord.Member,
        override: bool = False,
    ) -> ActivityCheck:
        async with ApiClient(self._api_conf[guild.id]) as client:
            api = MembersApi(client)
            data = PlayerActivityCheckSchema(
                league=self._league[guild.id],
                returning_status=returning_status,
                executor=executor.id,
                admin_override=override,
            )
            try:
                log.debug(f"[{player.id}] Activity Check: {data}")
                return await api.members_activity_check(player.id, data)
            except ApiException as exc:
                raise RscException(response=exc)

    async def transfer_membership(
        self, guild: discord.Guild, old: int, new: discord.Member
    ) -> Member:
        async with ApiClient(self._api_conf[guild.id]) as client:
            api = MembersApi(client)
            data = MemberTransferSchema(new_account=new.id)
            try:
                log.debug(f"Transferring {old} membership to {new.id}", guild=guild)
                return await api.members_transfer_account(id=old, data=data)
            except ApiException as exc:
                raise RscException(response=exc)

    async def name_history(
        self, guild: discord.Guild, member: discord.Member
    ) -> list[NameChangeHistory]:
        async with ApiClient(self._api_conf[guild.id]) as client:
            api = MembersApi(client)
            try:
                log.debug(f"Fetching name history for {member.id}", guild=guild)
                return await api.members_name_changes(member.id)
            except ApiException as exc:
                raise RscException(response=exc)
