import json
import logging

import discord
from pydantic import ValidationError
from redbot.core import app_commands

from rsc.admin import AdminMixIn
from rsc.admin.modals import BulkMatchModal
from rsc.admin.models import CreateMatchData
from rsc.embeds import (
    ApiExceptionErrorEmbed,
    BlueEmbed,
    ErrorEmbed,
    ExceptionErrorEmbed,
    RedEmbed,
    YellowEmbed,
)
from rsc.enums import MatchFormat, MatchType, PostSeasonType
from rsc.exceptions import RscException
from rsc.logs import GuildLogAdapter
from rsc.teams import TeamMixIn

logger = logging.getLogger("red.rsc.admin.match")
log = GuildLogAdapter(logger)


class AdminMatchMixIn(AdminMixIn):
    def __init__(self):
        log.debug("Initializing AdminMixIn:Match")

        super().__init__()

    _matches = app_commands.Group(
        name="matches",
        description="Manage RSC matches",
        parent=AdminMixIn._admin,
        guild_only=True,
        default_permissions=discord.Permissions(manage_guild=True),
    )

    @_matches.command(name="create", description="Create a regular season RSC match")  # type: ignore
    @app_commands.autocomplete(
        home_team=TeamMixIn.teams_autocomplete, away_team=TeamMixIn.teams_autocomplete
    )  # type: ignore
    async def _matches_create_cmd(
        self,
        interaction: discord.Interaction,
        match_type: MatchType,
        format: MatchFormat,
        home_team: str,
        away_team: str,
        day: app_commands.Range[int, 0, 20] = 0,
    ):
        guild = interaction.guild
        if not guild:
            return

        await interaction.response.defer()
        # Get team information
        try:
            log.debug(f"Searching for home team: {home_team}")
            hlist = await self.teams(guild, name=home_team)
            log.debug(f"Home Team Search: {hlist}")
            log.debug(f"Searching for away team:{away_team}")
            alist = await self.teams(guild, name=away_team)
            log.debug(f"Away Team Search: {alist}")
        except RscException as exc:
            return await interaction.followup.send(
                embed=ApiExceptionErrorEmbed(exc), ephemeral=True
            )

        # Validate results
        hteam = None
        if len(hlist) > 1:
            for h in hlist:
                if h.name == home_team:
                    hteam = h
                    break
        elif hlist:
            hteam = hlist.pop(0)

        # Home team not found
        if not hteam:
            return await interaction.followup.send(
                embed=ErrorEmbed(
                    f"No teams found or more than one result for **{home_team}**"
                )
            )

        ateam = None
        if len(alist) > 1:
            for a in alist:
                if a.name == away_team:
                    ateam = a
                    break
        elif alist:
            ateam = alist.pop(0)

        # Away team not found
        if not ateam:
            return await interaction.followup.send(
                embed=ErrorEmbed(
                    description=f"No teams found or more than one result for **{away_team}**"
                )
            )

        # Validate teams have an ID
        if not hteam.id:
            return await interaction.followup.send(
                embed=ErrorEmbed(
                    description=f"**{home_team}** has no team ID in the API."
                )
            )

        if not ateam.id:
            return await interaction.followup.send(
                embed=ErrorEmbed(
                    description=f"**{away_team}** has no team ID in the API."
                )
            )

        # Teams must be in the same tier
        try:
            if not await self.teams_in_same_tier(teams=[hteam, ateam]):
                return await interaction.followup.send(
                    embed=ErrorEmbed(
                        description=f"**{home_team}** and **{away_team}** are not in the same tier."
                    )
                )
        except ValueError as exc:
            return await interaction.followup.send(content=str(exc), ephemeral=True)

        # Create Match
        try:
            result = await self.create_match(
                guild,
                match_type=match_type,
                match_format=format,
                home_team_id=hteam.id,
                away_team_id=ateam.id,
                day=day,
            )
            log.debug(f"Match Creation Result: {result}")
        except RscException as exc:
            return await interaction.followup.send(
                embed=ApiExceptionErrorEmbed(exc), ephemeral=True
            )

        embed = BlueEmbed(title="Match Created")
        embed.add_field(name="Match Type", value=str(match_type), inline=True)
        embed.add_field(name="Format", value=str(format), inline=True)
        embed.add_field(name="Day", value=str(day), inline=True)
        embed.add_field(name="", value="", inline=False)
        embed.add_field(name="Home Team", value=hteam.name, inline=True)
        embed.add_field(name="Away Team", value=ateam.name, inline=True)
        await interaction.followup.send(embed=embed)

    # Matches Group Commands
    @_matches.command(name="playoff", description="Create an RSC playoff match")  # type: ignore
    @app_commands.autocomplete(
        home_team=TeamMixIn.teams_autocomplete, away_team=TeamMixIn.teams_autocomplete
    )  # type: ignore
    async def _matches_playoff_cmd(
        self,
        interaction: discord.Interaction,
        round: PostSeasonType,
        format: MatchFormat,
        home_team: str,
        away_team: str,
    ):
        guild = interaction.guild
        if not guild:
            return

        await interaction.response.defer()
        # Get team information
        try:
            log.debug(f"Searching for home team: {home_team}")
            hlist = await self.teams(guild, name=home_team)
            log.debug(f"Home Team Search: {hlist}")
            log.debug(f"Searching for away team:{away_team}")
            alist = await self.teams(guild, name=away_team)
            log.debug(f"Away Team Search: {alist}")
        except RscException as exc:
            return await interaction.followup.send(
                embed=ApiExceptionErrorEmbed(exc), ephemeral=True
            )

        # Validate results
        hteam = None
        if len(hlist) > 1:
            for h in hlist:
                if h.name == home_team:
                    hteam = h
                    break
        elif hlist:
            hteam = hlist.pop(0)

        # Home team not found
        if not hteam:
            return await interaction.followup.send(
                embed=ErrorEmbed(
                    f"No teams found or more than one result for **{home_team}**"
                )
            )

        ateam = None
        if len(alist) > 1:
            for a in alist:
                if a.name == away_team:
                    ateam = a
                    break
        elif alist:
            ateam = alist.pop(0)

        # Away team not found
        if not ateam:
            return await interaction.followup.send(
                embed=ErrorEmbed(
                    description=f"No teams found or more than one result for **{away_team}**"
                )
            )

        # Validate teams have an ID
        if not hteam.id:
            return await interaction.followup.send(
                embed=ErrorEmbed(
                    description=f"**{home_team}** has no team ID in the API."
                )
            )

        if not ateam.id:
            return await interaction.followup.send(
                embed=ErrorEmbed(
                    description=f"**{away_team}** has no team ID in the API."
                )
            )

        # Teams must be in the same tier
        try:
            if not await self.teams_in_same_tier(teams=[hteam, ateam]):
                return await interaction.followup.send(
                    embed=ErrorEmbed(
                        description=f"**{home_team}** and **{away_team}** are not in the same tier."
                    )
                )
        except ValueError as exc:
            return await interaction.followup.send(content=str(exc), ephemeral=True)

        # Create Match
        try:
            result = await self.create_match(
                guild,
                match_type=MatchType.POSTSEASON,
                match_format=format,
                home_team_id=hteam.id,
                away_team_id=ateam.id,
                day=round.value,
            )
            log.debug(f"Match Creation Result: {result}")
        except RscException as exc:
            return await interaction.followup.send(
                embed=ApiExceptionErrorEmbed(exc), ephemeral=True
            )

        embed = BlueEmbed(title="Playoff Match Created")
        embed.add_field(name="Match Type", value=str(MatchType.POSTSEASON), inline=True)
        embed.add_field(name="Format", value=str(format), inline=True)
        embed.add_field(name="Round", value=round.name, inline=True)
        embed.add_field(name="", value="", inline=False)
        embed.add_field(name="Home Team", value=hteam.name, inline=True)
        embed.add_field(name="Away Team", value=ateam.name, inline=True)
        await interaction.followup.send(embed=embed)

    # Matches Group Commands
    @_matches.command(name="bulk", description="Create bulk RSC matches")  # type: ignore
    async def _matches_bulk_create_cmd(self, interaction: discord.Interaction):
        guild = interaction.guild
        if not guild:
            return

        bulk_modal = BulkMatchModal()
        await interaction.response.send_modal(bulk_modal)
        await bulk_modal.wait()
        log.debug("Modal finished.")

        # Loading embed
        await bulk_modal.interaction.response.send_message(
            embed=YellowEmbed(
                title="Bulk Match Creation", description="Processing match data..."
            )
        )

        # Parse JSON
        try:
            log.debug("Parsing match JSON")
            matches = await bulk_modal.parse_matches()
        except (json.JSONDecodeError, ValidationError) as exc:
            return await bulk_modal.interaction.edit_original_response(
                embed=ExceptionErrorEmbed(exc_message=str(exc))
            )

        # Create Match
        success: list[CreateMatchData] = []
        for m in matches:
            log.debug(f"MD: {m.day} Home: {m.home_team} Away: {m.away_team}")
            try:
                # Get team IDs
                log.debug(f"Searching for home team: {m.home_team}")
                home_id = await self.team_id_by_name(guild, name=m.home_team)
                log.debug(f"Home Team ID: {home_id}")
                log.debug(f"Searching for away team:{m.away_team}")
                away_id = await self.team_id_by_name(guild, name=m.away_team)
                log.debug(f"Away Team ID: {away_id}")
                result = await self.create_match(
                    guild,
                    match_type=m.match_type,
                    match_format=m.match_format,
                    home_team_id=home_id,
                    away_team_id=away_id,
                    day=m.day,
                )
                log.debug(f"Match Creation Result: {result}")
                success.append(m)
            except (RscException, ValidationError) as exc:
                failembed = RedEmbed(
                    title="Bulk Match Error",
                    description=f"Exception:\n```{str(exc)}```\n\nThe following matches succeeded.",
                )
                failembed.add_field(
                    name="Day",
                    value="\n".join([str(s.day) for s in success]),
                    inline=True,
                )
                failembed.add_field(
                    name="Home",
                    value="\n".join([s.home_team for s in success]),
                    inline=True,
                )
                failembed.add_field(
                    name="Away",
                    value="\n".join([s.away_team for s in success]),
                    inline=True,
                )
                return await bulk_modal.interaction.edit_original_response(
                    embed=failembed
                )

        embed = BlueEmbed(
            title="Bulk Matches Added",
            description=f"**{len(success)}** matches have been created in the API.",
        )
        await bulk_modal.interaction.edit_original_response(embed=embed)
