import logging
import random

# import statistics
import string
from datetime import datetime, timedelta
from pathlib import Path
from urllib.parse import urljoin

import ballchasing
import discord
from redbot.core import app_commands
from rscapi.models.match import Match
from rscapi.models.match_results import MatchResults

from rsc.abc import RSCMixIn
from rsc.ballchasing import groups, process, validation
from rsc.embeds import (
    ApiExceptionErrorEmbed,
    ErrorEmbed,
    ExceptionErrorEmbed,
    SuccessEmbed,
    YellowEmbed,
)
from rsc.enums import MatchType
from rsc.exceptions import RscException
from rsc.logs import GuildLogAdapter
from rsc.teams import TeamMixIn
from rsc.utils import utils
from rsc.views import LinkButton

# from rsc.views import LinkButton

logger = logging.getLogger("red.rsc.ballchasing")
log = GuildLogAdapter(logger)

defaults_guild = {
    "AuthToken": None,
    "TopLevelGroup": None,
    "LogChannel": None,
    "ManagerRole": None,
    "RscSteamId": None,
    "ReportCategory": None,
}

verify_timeout = 30
BALLCHASING_URL = "https://ballchasing.com"
DONE = "Done"
WHITE_X_REACT = "\U0000274E"  # :negative_squared_cross_mark:
WHITE_CHECK_REACT = "\U00002705"  # :white_check_mark:
# RSC_STEAM_ID = 76561199096013422  # RSC Steam ID
# RSC_STEAM_ID = 76561197960409023  # REMOVEME - my steam id for development

LARGE_BATCH_SIZE = 10
SMALL_BATCH_SIZE = 5


class BallchasingMixIn(RSCMixIn):
    def __init__(self):
        log.debug("Initializing BallchasingMixIn")

        self.config.init_custom("Ballchasing", 1)
        self.config.register_custom("Ballchasing", **defaults_guild)
        self._ballchasing_api: dict[int, ballchasing.Api] = {}
        super().__init__()

    # Setup

    async def prepare_ballchasing(self, guild: discord.Guild):
        token = await self._get_bc_auth_token(guild)
        if token:
            self._ballchasing_api[guild.id] = ballchasing.Api(auth_key=token)
            await self._ballchasing_api[guild.id].ping()

    # Settings
    _ballchasing: app_commands.Group = app_commands.Group(
        name="ballchasing",
        description="Ballchasing commands and configuration",
        guild_only=True,
        default_permissions=discord.Permissions(manage_guild=True),
    )

    @_ballchasing.command(  # type: ignore
        name="settings",
        description="Display settings for ballchasing replay management",
    )
    @app_commands.checks.has_permissions(manage_guild=True)
    async def _bc_settings(self, interaction: discord.Interaction):
        """Show transactions settings"""
        guild = interaction.guild
        if not guild:
            return

        url = BALLCHASING_URL
        token = (
            "Configured" if await self._get_bc_auth_token(guild) else "Not Configured"
        )
        log_channel = await self._get_bc_log_channel(guild)
        score_category = await self._get_score_reporting_category(guild)
        role = await self._get_bc_manager_role(guild)
        tlg = await self._get_top_level_group(guild)

        if tlg:
            tlg_url = await self.bc_group_full_url(tlg)
        else:
            tlg_url = "None"

        embed = discord.Embed(
            title="Ballchasing Settings",
            description="Current configuration for Ballchasing replay management",
            color=discord.Color.blue(),
        )

        embed.add_field(name="Ballchasing URL", value=url, inline=False)
        embed.add_field(name="Ballchasing API Token", value=token, inline=False)
        embed.add_field(
            name="Management Role", value=role.mention if role else "None", inline=False
        )
        embed.add_field(
            name="Log Channel",
            value=log_channel.mention if log_channel else "None",
            inline=False,
        )
        embed.add_field(
            name="Report Category",
            value=score_category,
            inline=False,
        )
        embed.add_field(
            name="Top Level Ballchasing Group",
            value=tlg_url,
            inline=False,
        )

        await interaction.response.send_message(embed=embed, ephemeral=True)

    @_ballchasing.command(  # type: ignore
        name="key", description="Configure the Ballchasing API key for the server"
    )
    @app_commands.checks.has_permissions(manage_guild=True)
    async def _bc_key(self, interaction: discord.Interaction, key: str):
        if not interaction.guild:
            return
        await self._save_bc_auth_token(interaction.guild, key)
        await interaction.response.send_message(
            embed=SuccessEmbed(
                description="Ballchasing API key have been successfully configured"
            ),
            ephemeral=True,
        )

    @_ballchasing.command(  # type: ignore
        name="manager",
        description="Configure the ballchasing management role (Ex: @Stats Committee)",
    )
    @app_commands.checks.has_permissions(manage_guild=True)
    async def _bc_management_role(
        self, interaction: discord.Interaction, role: discord.Role
    ):
        if not interaction.guild:
            return
        await self._save_bc_manager_role(interaction.guild, role)
        await interaction.response.send_message(
            embed=SuccessEmbed(
                description=f"Ballchasing management role set to {role.mention}"
            ),
            ephemeral=True,
        )

    @_ballchasing.command(  # type: ignore
        name="log",
        description="Configure the logging channel for Ballchasing commands (Ex: #stats-committee)",
    )
    @app_commands.checks.has_permissions(manage_guild=True)
    async def _bc_log_channel(
        self, interaction: discord.Interaction, channel: discord.TextChannel
    ):
        if not interaction.guild:
            return
        await self._save_bc_log_channel(interaction.guild, channel)
        await interaction.response.send_message(
            embed=SuccessEmbed(
                description=f"Ballchasing log channel set to {channel.mention}"
            ),
            ephemeral=True,
        )

    @_ballchasing.command(  # type: ignore
        name="category",
        description="Configure the score reporting category for the server",
    )
    @app_commands.checks.has_permissions(manage_guild=True)
    async def _bc_score_category(
        self, interaction: discord.Interaction, category: discord.CategoryChannel
    ):
        if not interaction.guild:
            return

        await self._save_score_reporting_category(interaction.guild, category)
        await interaction.response.send_message(
            embed=SuccessEmbed(
                description=f"Score reporting category set to **{category.name}**"
            ),
            ephemeral=True,
        )

    @_ballchasing.command(  # type: ignore
        name="toplevelgroup",
        description="Configure the top level ballchasing group for RSC",
    )
    @app_commands.describe(group='Ballchasing group string (Ex: "rsc-v4rxmuxj6o")')
    @app_commands.checks.has_permissions(manage_guild=True)
    async def _bc_top_level_group_cmd(
        self, interaction: discord.Interaction, group: str
    ):
        if not interaction.guild:
            return
        await self._save_top_level_group(interaction.guild, group)
        full_url = await self.bc_group_full_url(group)
        await interaction.response.send_message(
            embed=SuccessEmbed(
                title="Ballchasing Group",
                description=f"Ballchasing top level group set to **{group}**",
                url=full_url,
            ),
            ephemeral=True,
        )

    # Commands

    @_ballchasing.command(  # type: ignore
        name="scanmissing",
        description="Find missing matches in ballchasing",
    )
    @app_commands.describe(
        matchday="Match day to report (Optional: Defaults to current match day)",
        matchtype="Match type to find. (Default: Regular Season)",
    )
    async def _bc_scan_missing_matches(
        self,
        interaction: discord.Interaction,
        matchday: int | None = None,
        matchtype: MatchType = MatchType.REGULAR,
    ):
        await utils.not_implemented(interaction)

    @app_commands.command(  # type: ignore
        name="reportmatch",
        description="Report the results of your RSC match",
    )
    @app_commands.autocomplete(
        home=TeamMixIn.teams_autocomplete,
        away=TeamMixIn.teams_autocomplete,
    )  # type: ignore
    @app_commands.describe(
        home="Home team name",
        away="Away team name",
        replay1="Rocket League replay file",
        replay2="Rocket League replay file",
        replay3="Rocket League replay file",
        replay4="Rocket League replay file",
        replay5="Rocket League replay file",
        replay6="Rocket League replay file",
        replay7="Rocket League replay file",
        replay8="Rocket League replay file",
        override="Admin or stats only override",
    )
    async def _reportmatch_cmd(
        self,
        interaction: discord.Interaction,
        home: str,
        home_wins: int,
        away: str,
        away_wins: int,
        replay1: discord.Attachment,
        replay2: discord.Attachment | None = None,
        replay3: discord.Attachment | None = None,
        replay4: discord.Attachment | None = None,
        replay5: discord.Attachment | None = None,
        replay6: discord.Attachment | None = None,
        replay7: discord.Attachment | None = None,
        replay8: discord.Attachment | None = None,
        override: bool = False,
    ):
        guild = interaction.guild
        member = interaction.user
        if not (guild and isinstance(member, discord.Member)):
            return

        # Check if override is allowed
        if override and not self.has_bc_permissions(member):
            return await interaction.response.send_message(
                embed=ErrorEmbed(
                    description="You do not have permission to override a match result."
                )
            )

        await interaction.response.defer(ephemeral=True)

        # Aggregate replays into list
        argv = locals()
        replay_files: list[discord.Attachment] = []
        for k, v in argv.items():
            if v and k.startswith("replay"):
                if not await validation.is_replay_file(v):
                    return await interaction.followup.send(
                        embed=ErrorEmbed(
                            description=f"`{v.filename}` is not a valid replay file."
                        ),
                        ephemeral=True,
                    )
                replay_files.append(v)
        log.debug(f"Replay Count: {len(replay_files)}")

        # Check for duplicates
        log.debug("Checking for duplicate replays")
        if await validation.duplicate_replay_hashes(replay_files):
            return await interaction.followup.send(
                embed=ErrorEmbed(
                    title="Duplicate Replays Found",
                    description="Duplicate replays found. Please make sure you hvae to right files attached.",
                ),
                ephemeral=True,
            )

        # Get match search window
        tz = await self.timezone(guild)
        today = datetime.now(tz=tz)
        start_date = today - timedelta(days=7)
        end_date = today + timedelta(days=7)

        log.debug(
            f"Searching for match: {home} vs {away}. Start: {start_date}, End: {end_date}"
        )
        mlist: list[Match] = await self.find_match(
            guild,
            date_gt=start_date,
            date_lt=end_date,
            teams=[home, away],
        )

        # No match found
        if not mlist:
            return await interaction.followup.send(
                embed=ErrorEmbed(
                    description=f"No matches found for **{home}** vs **{away}**."
                ),
                ephemeral=True,
            )

        log.debug("Searching for valid teams in match data")
        log.debug(f"Home Team: {home}")
        log.debug(f"Away Team: {away}")

        # Check if we got a match with matching home/away team names
        match = await self.get_match_from_list(home=home, away=away, matches=mlist)

        if not match:
            return await interaction.followup.send(
                embed=ErrorEmbed(
                    description=f"No matches found for **{home}** vs **{away}**."
                ),
                ephemeral=True,
            )

        # Make sure we have the match ID
        if not match.id:
            return await interaction.followup.send(
                embed=ErrorEmbed(
                    description=f"Found match for **{home}** vs **{away}** but it has no match ID in the API."
                ),
                ephemeral=True,
            )

        log.debug(f"Found match: {match}")

        # Send "working" message
        embed = YellowEmbed(
            title="Processing Match",
            description=f"Processing replays for match **{home}** vs **{away}**.",
        )
        await interaction.followup.send(embed=embed, ephemeral=True)

        try:
            bc_group = await self.process_match_replays(
                guild, match=match, replays=replay_files
            )
        except (TypeError, ValueError, RuntimeError) as exc:
            return await interaction.edit_original_response(
                embed=ExceptionErrorEmbed(exc_message=str(exc))
            )

        try:
            match_result = await self.report_match(
                guild,
                match_id=match.id,
                ballchasing_group=bc_group,
                home_score=home_wins,
                away_score=away_wins,
                executor=member,
                override=override,
            )
            log.debug(f"Match Result: {match_result}")
        except RscException as exc:
            if hasattr(exc, "status") and exc.status == 400:
                # Match already reported
                return await interaction.edit_original_response(
                    embed=YellowEmbed(
                        title="Match Reported",
                        description="This match has already been reported but all additional replays have been uploaded.",
                    )
                )
            else:
                return await interaction.edit_original_response(
                    embed=ApiExceptionErrorEmbed(exc)
                )

        # Final embed
        result_embed, result_view = await self.build_match_result_embed(
            guild,
            match=match,
            result=match_result,
            link=await self.bc_group_full_url(bc_group),
        )

        # Announce to score reporting
        await self.announce_to_score_reporting(
            guild, tier=match.home_team.tier, embed=result_embed, view=result_view
        )

        # Send to user
        await interaction.edit_original_response(embed=result_embed, view=result_view)

    # Functions

    async def process_match_replays(
        self, guild: discord.Guild, match: Match, replays=list[discord.Attachment]
    ):
        log.debug(
            f"Processing match: {match.home_team.name} vs {match.away_team.name}",
            guild=guild,
        )
        # Get BC top level group
        tlg = await self._get_top_level_group(guild)
        if not tlg:
            raise ValueError("Top level ballchasing group is not configured in guild.")

        # Get ballchasing API
        bapi = self._ballchasing_api.get(guild.id)
        if not bapi:
            raise ValueError("Ballchasing API is not configured in guild.")

        # Create or find RSC match group ID
        match_group_id = await groups.rsc_match_bc_group(
            bapi=bapi, guild=guild, tlg=tlg, match=match
        )
        log.debug(f"Match Group ID: {match_group_id}", guild=guild)
        if not match_group_id:
            raise RuntimeError("Unable to find or create ballchasing match group.")

        # Get replays from group if any
        log.debug(f"Getting existing replays from {match_group_id}", guild=guild)
        bc_replays: list[ballchasing.models.Replay] = await utils.async_iter_gather(
            bapi.get_group_replays(group_id=match_group_id, deep=True)
        )
        log.debug(f"Existing Replay Count: {len(bc_replays)}", guild=guild)

        # Check for collisions in ballchasing (duplicate replays)
        collisions = await process.replay_group_collisions(
            replay_files=replays, bc_replays=bc_replays
        )
        log.debug(f"Replay Collisions: {collisions}", guild=guild)

        # Remove collisions from upload list
        for c in collisions:
            replays.remove(c)

        # Upload replays (only if we need to)
        if replays:
            await self.upload_replays(guild, group=match_group_id, replays=replays)

        return match_group_id

    async def upload_replays(
        self,
        guild: discord.Guild,
        group: str,
        replays: list[discord.Attachment | str | bytes],
    ) -> list[str]:
        if not replays:
            raise ValueError("No replays provided for upload to ballchasing.")

        # Get ballchasing API
        bapi = self._ballchasing_api.get(guild.id)
        if not bapi:
            raise ValueError("Ballchasing API is not configured in guild.")

        # Upload replays
        log.debug(f"Uploading replays to group: {group}", guild=guild)
        replay_ids = []
        for replay in replays:
            generated_name = "".join(
                random.choices(string.ascii_letters + string.digits, k=64)
            )
            rname = f"{generated_name}.replay"
            try:
                if isinstance(replay, discord.Attachment):
                    rdata = await replay.read()
                elif isinstance(replay, bytes):
                    rdata = replay
                elif isinstance(replay, str):
                    # Read bytes from file
                    fdata = Path(replay).read_bytes()
                    rdata = fdata

                # Upload to ballchasing group
                resp = await bapi.upload_replay_from_bytes(
                    name=rname,
                    replay_data=rdata,
                    visibility=ballchasing.Visibility.PUBLIC,
                    group=group,
                )
                if resp:
                    replay_ids.append(resp.id)
            except ValueError as exc:
                log.debug(exc)
                err = exc.args[0]
                if err.status == 409:
                    # duplicate replay. patch it under the BC group
                    err_info = await err.json()
                    log.debug(
                        f"Error uploading replay. {err.status} -- {err_info}",
                        guild=guild,
                    )
                    r_id = err_info.get("id")
                    if r_id:
                        log.debug("Patching replay under correct group", guild=guild)
                        await bapi.patch_replay(r_id, group=group)
                        replay_ids.append(r_id)
        log.debug(f"Ballchasing IDs: {replay_ids}", guild=guild)
        return replay_ids

    async def build_match_result_embed(
        self,
        guild: discord.Guild,
        match: Match,
        result: MatchResults,
        link: str | None = None,
    ) -> tuple[discord.Embed, discord.ui.View | None]:
        tier_color = await utils.tier_color_by_name(guild, match.home_team.tier)

        embed = discord.Embed(
            title=f"MD {match.day}: {match.home_team.name} vs {match.away_team.name}",
            description=(
                "Match Summary:\n"
                f"**{match.home_team.name}** {result.home_wins} - {result.away_wins} **{match.away_team.name}**"
            ),
            color=tier_color,
        )
        # Ballchasing group link button
        bc_view = None
        if link:
            bc_view = discord.ui.View()
            bcbutton = LinkButton(label="Ballchasing Group", url=link)
            bc_view.add_item(bcbutton)

        # Get franchise logo
        if (
            result.home_wins is not None
            and result.away_wins is not None
            and result.home_wins > result.away_wins
        ):
            winning_franchise = match.home_team.franchise
        else:
            winning_franchise = match.away_team.franchise

        flogo = None
        fsearch = await self.franchises(guild, name=winning_franchise)
        if fsearch:
            f = fsearch.pop()
            if f.id:
                flogo = await self.franchise_logo(guild=guild, id=f.id)

        if flogo:
            embed.set_thumbnail(url=flogo)
        elif guild.icon:
            embed.set_thumbnail(url=guild.icon.url)

        return embed, bc_view

    async def announce_to_stats_committee(
        self,
        guild: discord.Guild,
        embed: discord.Embed,
        view: discord.ui.View | None = None,
        content: str | None = None,
        files: list[discord.File] | None = None,
    ) -> discord.Message | None:
        if files is None:
            files = []
        log_channel = await self._get_bc_log_channel(guild)
        if not log_channel:
            return None

        return await log_channel.send(content=content, embed=embed, files=files)

    async def announce_to_score_reporting(
        self,
        guild: discord.Guild,
        tier: str,
        embed: discord.Embed,
        view: discord.ui.View | None = None,
        content: str | None = None,
        files: list[discord.File] | None = None,
    ) -> discord.Message | None:
        if files is None:
            files = []

        category = await self._get_score_reporting_category(guild)
        if not category:
            log.warning(
                f"[{guild.name}] Ballchasing score report category is not configured"
            )
            return None

        cname = f"{tier.lower()}-score-reporting"

        score_channel = discord.utils.get(category.channels, name=cname)
        if not score_channel:
            log.warning(
                f"[{guild.name}] Unable to find tier score report channel: {cname}"
            )
            return None

        if not isinstance(score_channel, discord.TextChannel):
            return None

        if view:
            return await score_channel.send(
                content=content, embed=embed, view=view, files=files
            )
        else:
            return await score_channel.send(content=content, embed=embed, files=files)

    async def has_bc_permissions(self, member: discord.Member) -> bool:
        """Determine if member is able to manage guild or part of manager role"""
        # Guild Manager
        if member.guild_permissions.manage_guild:
            return True

        # BC Manager Role
        manager_role = await self._get_bc_manager_role(member.guild)
        if manager_role in member.roles:
            return True
        return False

    @staticmethod
    async def bc_group_full_url(group: str) -> str:
        return urljoin(BALLCHASING_URL, f"/group/{group}")

    @staticmethod
    async def bc_replay_full_url(replay: str) -> str:
        return urljoin(BALLCHASING_URL, f"/replay/{replay}")

    async def close_ballchasing_sessions(self):
        log.info("Closing ballchasing sessions")
        for bapi in self._ballchasing_api.values():
            await bapi.close()

    # Config

    async def _get_bc_auth_token(self, guild: discord.Guild) -> str:
        return await self.config.custom("Ballchasing", str(guild.id)).AuthToken()

    async def _save_bc_auth_token(self, guild: discord.Guild, key: str):
        await self.config.custom("Ballchasing", str(guild.id)).AuthToken.set(key)

    async def _save_top_level_group(self, guild: discord.Guild, group_id):
        await self.config.custom("Ballchasing", str(guild.id)).TopLevelGroup.set(
            group_id
        )

    async def _get_top_level_group(self, guild: discord.Guild) -> str | None:
        return await self.config.custom("Ballchasing", str(guild.id)).TopLevelGroup()

    async def _get_bc_log_channel(
        self, guild: discord.Guild
    ) -> discord.TextChannel | None:
        id = await self.config.custom("Ballchasing", str(guild.id)).LogChannel()
        if not id:
            return None
        c = guild.get_channel(id)
        if not isinstance(c, discord.TextChannel):
            return None
        return c

    async def _save_bc_log_channel(
        self, guild: discord.Guild, channel: discord.TextChannel
    ):
        await self.config.custom("Ballchasing", str(guild.id)).LogChannel.set(
            channel.id
        )

    async def _get_bc_manager_role(self, guild: discord.Guild) -> discord.Role | None:
        r = await self.config.custom("Ballchasing", str(guild.id)).ManagerRole()
        if not r:
            return None
        return guild.get_role(r)

    async def _save_bc_manager_role(self, guild: discord.Guild, role: discord.Role):
        await self.config.custom("Ballchasing", str(guild.id)).ManagerRole.set(role.id)

    async def _save_score_reporting_category(
        self, guild: discord.Guild, category: discord.CategoryChannel
    ):
        await self.config.custom("Ballchasing", str(guild.id)).ReportCategory.set(
            category.id
        )

    async def _get_score_reporting_category(
        self, guild: discord.Guild
    ) -> discord.CategoryChannel | None:
        c = await self.config.custom("Ballchasing", str(guild.id)).ReportCategory()
        if not c:
            return None

        category = guild.get_channel(c)
        if not isinstance(category, discord.CategoryChannel):
            log.warning(
                f"[{guild.name}] Score report channel is not a category channel."
            )
            return None
        return category
