import logging
from datetime import datetime, timedelta
from typing import cast

import discord
from redbot.core import app_commands
from rscapi import ApiClient, TrackerLinksApi
from rscapi.exceptions import ApiException
from rscapi.models.tracker_link import TrackerLink
from rscapi.models.tracker_link_linking import TrackerLinkLinking
from rscapi.models.tracker_link_stats import TrackerLinkStats

from rsc.abc import RSCMixIn
from rsc.const import RSC_TRACKER_URL
from rsc.embeds import (
    ApiExceptionErrorEmbed,
    BlueEmbed,
    ErrorEmbed,
    SuccessEmbed,
    YellowEmbed,
)
from rsc.enums import TrackerLinksStatus
from rsc.exceptions import RscException
from rsc.utils import utils
from rsc.views import LinkButton

log = logging.getLogger("red.rsc.trackers")


class TrackerMixIn(RSCMixIn):
    def __init__(self):
        log.debug("Initializing TrackersMixIn")
        super().__init__()

    # Top Level Groups

    _trackers = app_commands.Group(name="trackers", description="RSC Player Tracker Links", guild_only=True)

    # App Commands

    @_trackers.command(name="add", description="Add a new player tracker")  # type: ignore[type-var]
    @app_commands.describe(player="RSC Discord Member", tracker="Rocket League tracker link")
    @app_commands.checks.has_permissions(manage_guild=True)
    async def _trackers_add_cmd(self, interaction: discord.Interaction, player: discord.Member, tracker: str):
        guild = interaction.guild
        if not guild:
            return

        await interaction.response.defer(ephemeral=False)

        try:
            await self.add_tracker(guild, player, tracker)
        except RscException as exc:
            return await interaction.followup.send(embed=ApiExceptionErrorEmbed(exc), ephemeral=False)

        tracker_view = discord.ui.View()
        tracker_view.add_item(LinkButton(label="Tracker Link", url=tracker))

        embed = BlueEmbed(
            title="Tracker Added",
            description=f"Added tracker link to {player.mention}",
        )

        embed.add_field(name="Tracker", value=tracker, inline=False)
        await interaction.followup.send(embed=embed, view=tracker_view, ephemeral=False)

    @_trackers.command(name="list", description="List the trackers")  # type: ignore[type-var]
    @app_commands.describe(player="RSC Discord Member", ids="Show tracker ids")
    async def _trackers_list(self, interaction: discord.Interaction, player: discord.Member, ids: bool = False):
        guild = interaction.guild
        if not guild:
            return

        await interaction.response.defer(ephemeral=False)
        try:
            trackers = await self.trackers(guild, player=player.id)
        except RscException as exc:
            return await interaction.followup.send(embed=ApiExceptionErrorEmbed(exc), ephemeral=False)

        embed = YellowEmbed(title=f"{player.display_name} Trackers")
        if not trackers:
            embed.description = "This user has no RSC trackers on record."
        else:
            tdata = []
            for t in trackers:
                date = t.last_updated.date() if t.last_updated else "None"
                status = None
                if t.status:
                    status = TrackerLinksStatus(t.status).full_name
                tdata.append((t.name or t.platform_id, status, date, t.id))
            tdata.sort(key=lambda x: cast(int, x[1]))
            embed.description = "List of associated RSC trackers. Account is tracker name or platform id."
            if ids:
                embed.add_field(name="ID", value="\n".join([str(x[3]) for x in tdata]), inline=True)
            embed.add_field(name="Account", value="\n".join([str(x[0]) for x in tdata]), inline=True)
            embed.add_field(name="Status", value="\n".join([str(x[1]) for x in tdata]), inline=True)
            embed.add_field(
                name="Last Pull",
                value="\n".join([str(x[2]) for x in tdata]),
                inline=True,
            )
        await interaction.followup.send(embed=embed, ephemeral=False)

    @_trackers.command(name="link", description="Link a tracker from player")  # type: ignore[type-var]
    @app_commands.describe(tracker_id="Tracker API ID", player="RSC Discord Member")
    async def _trackers_unlink_cmd(self, interaction: discord.Interaction, tracker_id: int, player: discord.Member):
        guild = interaction.guild
        if not (guild and isinstance(interaction.user, discord.Member)):
            return

        await interaction.response.defer(ephemeral=False)
        try:
            tracker = await self.fetch_tracker_by_id(guild, tracker_id)
        except RscException as exc:
            return await interaction.followup.send(embed=ApiExceptionErrorEmbed(exc), ephemeral=False)

        # Verify tracker exists
        if not tracker:
            return await interaction.followup.send(embed=ErrorEmbed(description=f"Tracker {tracker_id} does not exist."), ephemeral=False)

        try:
            tracker = await self.link_tracker(guild, tracker_id, player, interaction.user)
        except RscException as exc:
            return await interaction.followup.send(embed=ApiExceptionErrorEmbed(exc), ephemeral=False)

        embed = SuccessEmbed(title="Tracker Linked", description=f"Linked tracker {tracker_id} from {player.mention}")
        await interaction.followup.send(embed=embed, ephemeral=False)

    @_trackers.command(name="unlink", description="Unlink a tracker from player")  # type: ignore[type-var]
    @app_commands.describe(tracker_id="Tracker API ID", player="RSC Discord Member")
    async def _trackers_unlink_cmd(self, interaction: discord.Interaction, tracker_id: int, player: discord.Member):
        guild = interaction.guild
        if not (guild and isinstance(interaction.user, discord.Member)):
            return

        await interaction.response.defer(ephemeral=False)
        try:
            tracker = await self.fetch_tracker_by_id(guild, tracker_id)
        except RscException as exc:
            return await interaction.followup.send(embed=ApiExceptionErrorEmbed(exc), ephemeral=False)

        # Verify tracker exists
        if not tracker:
            return await interaction.followup.send(embed=ErrorEmbed(description=f"Tracker {tracker_id} does not exist."), ephemeral=False)

        try:
            tracker = await self.unlink_tracker(guild, tracker_id, player, interaction.user)
        except RscException as exc:
            return await interaction.followup.send(embed=ApiExceptionErrorEmbed(exc), ephemeral=False)

        embed = SuccessEmbed(title="Tracker Unlinked", description=f"Unlinked tracker {tracker_id} from {player.mention}")
        await interaction.followup.send(embed=embed, ephemeral=False)

    @_trackers.command(name="delete", description="Delete a tracker (Must have zero MMR pulls)")  # type: ignore[type-var]
    @app_commands.describe(tracker_id="Tracker API ID")
    async def _trackers_delete_cmd(self, interaction: discord.Interaction, tracker_id: int):
        guild = interaction.guild
        if not (guild and isinstance(interaction.user, discord.Member)):
            return

        await interaction.response.defer(ephemeral=False)
        try:
            tracker = await self.fetch_tracker_by_id(guild, tracker_id)
        except RscException as exc:
            return await interaction.followup.send(embed=ApiExceptionErrorEmbed(exc), ephemeral=False)

        # Verify tracker exists
        if not tracker:
            return await interaction.followup.send(embed=ErrorEmbed(description=f"Tracker {tracker_id} does not exist."), ephemeral=False)

        # Prevent deleting tracker with pulls
        if tracker.pulls and tracker.pulls > 0:
            return await interaction.followup.send(
                embed=ErrorEmbed(description=f"Tracker {tracker_id} has {tracker.pulls} pulls. Must unlink instead."),
                ephemeral=False,
            )

        try:
            await self.rm_tracker(guild, tracker_id)
        except RscException as exc:
            return await interaction.followup.send(embed=ApiExceptionErrorEmbed(exc), ephemeral=False)

        embed = SuccessEmbed(title="Tracker Deleted", description=f"Deleted tracker ID {tracker_id}.")
        await interaction.followup.send(embed=embed, ephemeral=False)

    @_trackers.command(name="recent", description="Show most recent RL tracker pulls")  # type: ignore[type-var]
    @app_commands.describe(status="Tracker status to query (Default: Pulled)")
    async def _trackers_recent_pull(
        self,
        interaction: discord.Interaction,
        status: TrackerLinksStatus = TrackerLinksStatus.PULLED,
    ):
        guild = interaction.guild
        if not guild:
            return

        await interaction.response.defer(ephemeral=False)
        try:
            trackers = await self.trackers(guild, status)
        except RscException as exc:
            return await interaction.followup.send(embed=ApiExceptionErrorEmbed(exc), ephemeral=False)

        trackers.sort(key=lambda x: cast(datetime, x.last_updated), reverse=True)

        dates = []
        for x in trackers:
            date_fmt = str(x.last_updated.date()) if x.last_updated else "None"
            dates.append(date_fmt)

        embed = YellowEmbed(
            title="Recent Trackers",
            description=f"List of most recent tracker updates.\n\nStatus: **{status}**",
        )
        embed.add_field(
            name="RSC ID",
            value="\n".join([str(x.rscid) for x in trackers[:25]]),
            inline=True,
        )
        embed.add_field(
            name="Name",
            value="\n".join([str(x.member_name) for x in trackers[:25]]),
            inline=True,
        )
        embed.add_field(
            name="Date",
            value="\n".join(dates[:25]),
            inline=True,
        )
        await interaction.followup.send(embed=embed, ephemeral=False)

    @_trackers.command(name="stats", description="Display RSC tracker link stats")  # type: ignore[type-var]
    async def _trackers_stats(
        self,
        interaction: discord.Interaction,
    ):
        guild = interaction.guild
        if not guild:
            return

        await interaction.response.defer(ephemeral=False)
        try:
            stats = await self.tracker_stats(guild)
        except RscException as exc:
            return await interaction.followup.send(embed=ApiExceptionErrorEmbed(exc), ephemeral=False)

        embed = YellowEmbed(
            title="RSC Tracker Stats",
        )
        embed.add_field(
            name="Status",
            value="\n".join(str(s.status) for s in stats),
            inline=True,
        )
        embed.add_field(
            name="Count",
            value="\n".join(str(s.count) for s in stats),
            inline=True,
        )
        await interaction.followup.send(embed=embed, ephemeral=False)

    @_trackers.command(  # type: ignore[type-var]
        name="old", description="Display number of outdated RSC tracker links"
    )
    @app_commands.describe(
        status="Tracker status to query (Default: Pulled)",
        days="Number of days since last update (Default: 90)",
    )
    async def _trackers_old(
        self,
        interaction: discord.Interaction,
        status: TrackerLinksStatus = TrackerLinksStatus.PULLED,
        days: int = 90,
    ):
        guild = interaction.guild
        if not guild:
            return

        await interaction.response.defer()

        tz = await self.timezone(guild)
        date_cutoff = datetime.now(tz) - timedelta(days=days)

        log.debug(f"Getting tracker data older than {date_cutoff.date()}")
        try:
            trackers = await self.trackers(guild, status)
        except RscException as exc:
            return await interaction.followup.send(embed=ApiExceptionErrorEmbed(exc), ephemeral=False)

        log.debug("Removing recently updated trackers")
        old_trackers = []
        for t in trackers:
            if not t.last_updated:
                old_trackers.append(t)
                continue

            if t.last_updated.date() < date_cutoff.date():
                old_trackers.append(t)
        log.debug("Finished iterating tracker list")

        embed = YellowEmbed(
            title="Outdated RSC Trackers",
            description=(
                f"Found **{len(old_trackers)}/{len(trackers)} {status.name}** trackers have not been updated since **{date_cutoff.date()}**"
            ),
        )
        await interaction.followup.send(embed=embed)

    # Non-Group Commands

    @app_commands.command(  # type: ignore[type-var]
        name="accounts",
        description="Display rocket league accounts associated with a player",
    )
    @app_commands.describe(player="RSC Discord Member")
    @app_commands.guild_only
    async def _accounts(self, interaction: discord.Interaction, player: discord.Member):
        if not interaction.guild:
            return

        await interaction.response.defer(ephemeral=False)
        try:
            trackers = await self.trackers(interaction.guild, player=player.id)
        except RscException as exc:
            await interaction.followup.send(embed=ApiExceptionErrorEmbed(exc))

        if not trackers:
            await interaction.followup.send(
                embed=YellowEmbed(description=f"{player.mention} does not have any registered RL trackers."),
                ephemeral=False,
            )
            return

        desc = ""
        for t in trackers:
            url = await utils.fix_tracker_url(t.link)
            if t.platform == "STEAM":
                desc += f"- [{t.platform} - {t.platform_id}]({url})\n"
            else:
                desc += f"- [{t.platform} - {t.name}]({url})\n"

        embed = BlueEmbed(title=f"{player.display_name} Accounts", description=desc)

        if player.avatar:
            embed.set_thumbnail(url=player.avatar.url)
        elif interaction.guild.icon:
            embed.set_thumbnail(url=interaction.guild.icon.url)

        link_button = LinkButton(label="RSC Tracker Links", url=RSC_TRACKER_URL)
        account_view = discord.ui.View()
        account_view.add_item(link_button)

        await interaction.followup.send(embed=embed, view=account_view, ephemeral=False)

    # Functions

    # API

    async def trackers(
        self,
        guild: discord.Guild,
        status: TrackerLinksStatus | None = None,
        player: discord.Member | int | None = None,
        name: str | None = None,
        limit: int = 0,
        offset: int = 0,
    ) -> list[TrackerLink]:
        """Fetch RSC tracker data"""
        player_id = None
        if isinstance(player, discord.Member):
            player_id = player.id
        elif isinstance(player, int):
            player_id = player

        async with ApiClient(self._api_conf[guild.id]) as client:
            api = TrackerLinksApi(client)
            try:
                trackers = await api.tracker_links_list(
                    status=str(status) if status else None,
                    discord_id=player_id,
                    member_name=name,
                    limit=limit,
                    offset=offset,
                )
                return trackers.results
            except ApiException as exc:
                raise RscException(response=exc)

    async def tracker_stats(
        self,
        guild: discord.Guild,
    ) -> TrackerLinkStats:
        """Fetch RSC Tracker Stats"""
        async with ApiClient(self._api_conf[guild.id]) as client:
            api = TrackerLinksApi(client)
            try:
                return await api.tracker_links_links_stats()
            except ApiException as exc:
                raise RscException(response=exc)

    async def next_tracker(
        self,
        guild: discord.Guild,
        limit: int = 25,
    ) -> list[TrackerLink]:
        """Get list of trackers ready to be updated"""
        async with ApiClient(self._api_conf[guild.id]) as client:
            api = TrackerLinksApi(client)
            try:
                return await api.tracker_links_next(limit=limit)
            except ApiException as exc:
                raise RscException(response=exc)

    async def add_tracker(
        self,
        guild: discord.Guild,
        player: discord.Member,
        tracker: str,
    ):
        """Add a tracker to a user"""
        async with ApiClient(self._api_conf[guild.id]) as client:
            api = TrackerLinksApi(client)
            data = TrackerLink(link=tracker, discord_id=player.id)
            log.debug(f"Tracker Create: {data}")
            try:
                return await api.tracker_links_create(data)
            except ApiException as exc:
                raise RscException(response=exc)

    async def rm_tracker(
        self,
        guild: discord.Guild,
        tracker_id: int,
    ) -> None:
        """Delete a tracker"""
        async with ApiClient(self._api_conf[guild.id]) as client:
            api = TrackerLinksApi(client)
            log.debug(f"Tracker Delete: {tracker_id}")
            try:
                return await api.tracker_links_delete(tracker_id)
            except ApiException as exc:
                raise RscException(response=exc)

    async def unlink_tracker(
        self,
        guild: discord.Guild,
        tracker_id: int,
        player: discord.Member,
        executor: discord.Member,
    ) -> TrackerLink:
        """Unlink a tracker from a user"""
        async with ApiClient(self._api_conf[guild.id]) as client:
            api = TrackerLinksApi(client)
            data = TrackerLinkLinking(member=player.id, executor=executor.id)
            log.debug(f"Tracker Unlink: {tracker_id} (Member: {player})")
            try:
                return await api.tracker_links_unlink(tracker_id, data)
            except ApiException as exc:
                raise RscException(response=exc)

    async def link_tracker(
        self,
        guild: discord.Guild,
        tracker_id: int,
        player: discord.Member,
        executor: discord.Member,
    ) -> TrackerLink:
        """Unlink a tracker from a user"""
        async with ApiClient(self._api_conf[guild.id]) as client:
            api = TrackerLinksApi(client)
            data = TrackerLinkLinking(member=player.id, executor=executor.id)
            log.debug(f"Tracker Link: {tracker_id} (Member: {player})")
            try:
                return await api.tracker_links_link(tracker_id, data)
            except ApiException as exc:
                raise RscException(response=exc)

    async def fetch_tracker_by_id(
        self,
        guild: discord.Guild,
        tracker_id: int,
    ) -> TrackerLink:
        """Fetch a Tracker Link by API ID"""
        async with ApiClient(self._api_conf[guild.id]) as client:
            api = TrackerLinksApi(client)
            log.debug(f"Fetch Tracker ID: {tracker_id}")
            try:
                return await api.tracker_links_read(tracker_id)
            except ApiException as exc:
                raise RscException(response=exc)
