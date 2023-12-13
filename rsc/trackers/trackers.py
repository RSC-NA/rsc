import discord
import logging

from discord.ext import tasks
from datetime import datetime, time, timedelta
from urllib.parse import urljoin

from redbot.core import Config, app_commands, commands, checks

from rscapi import ApiClient, TransactionsApi, LeaguePlayersApi, TrackerLinksApi
from rscapi.exceptions import ApiException
from rscapi.models.cut_a_player_from_a_league import CutAPlayerFromALeague
from rscapi.models.re_sign_player import ReSignPlayer
from rscapi.models.sign_a_player_to_a_team_in_a_league import (
    SignAPlayerToATeamInALeague,
)
from rscapi.models.tracker_link import TrackerLink
from rscapi.models.tracker_link_stats import TrackerLinkStats
from rscapi.models.temporary_fa_sub import TemporaryFASub
from rscapi.models.player_transaction_updates import PlayerTransactionUpdates
from rscapi.models.expire_a_player_sub import ExpireAPlayerSub
from rscapi.models.league_player import LeaguePlayer

from rsc.abc import RSCMixIn
from rsc.enums import TrackerLinksStatus, Status
from rsc.const import CAPTAIN_ROLE, DEV_LEAGUE_ROLE, FREE_AGENT_ROLE, RSC_TRACKER_URL
from rsc.embeds import (
    ErrorEmbed,
    SuccessEmbed,
    YellowEmbed,
    WarningEmbed,
    BlueEmbed,
    OrangeEmbed,
    ExceptionErrorEmbed,
    ApiExceptionErrorEmbed,
)
from rsc.exceptions import RscException, translate_api_error
from rsc.teams import TeamMixIn
from rsc.transactions.views import TradeAnnouncementModal, TradeAnnouncementView
from rsc.types import Substitute
from rsc.utils import utils
from rsc.views import LinkButton


from typing import Optional, TypedDict, List

log = logging.getLogger("red.rsc.trackers")


class TrackerMixIn(RSCMixIn):
    def __init__(self):
        log.debug("Initializing TrackersMixIn")
        super().__init__()

    # Tasks

    # Top Level Groups

    _trackers = app_commands.Group(
        name="trackers", description="RSC Player Tracker Links", guild_only=True
    )

    # App Commands

    @_trackers.command(name="testscraper", description="Testing things")
    async def _trackers_testscraper(
        self, interaction: discord.Interaction, member: discord.Member
    ):
        await interaction.response.defer(thinking=False, ephemeral=True)
        from rsc.trackers.scraper import TrackerScraper

        t = TrackerScraper()

    @_trackers.command(name="list", description="List the trackers")
    @app_commands.describe(player="RSC Discord Member")
    async def _trackers_list(self, interaction: discord.Interaction, player: discord.Member):
        await interaction.response.defer(ephemeral=True)
        trackers = await self.trackers(interaction.guild, player=player.id)

        embed = YellowEmbed(title=f"{player.display_name} Trackers")
        if not trackers:
            embed.description = "This user has no RSC trackers on record."
        else:
            tdata = []
            for t in trackers:
                tdata.append(
                    (t.name or t.platform_id, t.status, str(t.last_updated.date()))
                )
            tdata.sort(key=lambda x: x[1])
            embed.description = "List of associated RSC trackers. Account is tracker name or platform id."
            embed.add_field(
                name="Account", value="\n".join([x[0] for x in tdata]), inline=True
            )
            embed.add_field(
                name="Status", value="\n".join([x[1] for x in tdata]), inline=True
            )
            embed.add_field(
                name="Last Pull", value="\n".join([x[2] for x in tdata]), inline=True
            )
        await interaction.followup.send(embed=embed, ephemeral=True)

    @_trackers.command(name="recent", description="Show most recent RL tracker pulls")
    @app_commands.describe(status="Tracker status to query (Default: Pulled)")
    async def _trackers_recent_pull(
        self,
        interaction: discord.Interaction,
        status: TrackerLinksStatus = TrackerLinksStatus.PULLED,
    ):
        await interaction.response.defer()
        trackers = await self.trackers(interaction.guild, status)
        trackers.sort(key=lambda x: x.last_updated, reverse=True)

        embed = YellowEmbed(
            title="Recent Trackers",
            description=f"List of most recent tracker updates.\n\nStatus: **{status}**",
        )
        embed.add_field(
            name="RSC ID",
            value="\n".join([x.rscid for x in trackers[:25]]),
            inline=True,
        )
        embed.add_field(
            name="Name",
            value="\n".join([x.member_name for x in trackers[:25]]),
            inline=True,
        )
        embed.add_field(
            name="Date",
            value="\n".join([str(x.last_updated.date()) for x in trackers[:25]]),
            inline=True,
        )
        await interaction.followup.send(embed=embed)

    @_trackers.command(name="stats", description="Display RSC tracker link stats")
    async def _trackers_stats(
        self,
        interaction: discord.Interaction,
    ):
        await interaction.response.defer()
        stats = await self.tracker_stats(interaction.guild)

        embed = YellowEmbed(
            title="RSC Tracker Stats",
        )
        embed.add_field(
            name="New",
            value=str(stats.new),
            inline=True,
        )
        embed.add_field(
            name="Stale",
            value=str(stats.stale),
            inline=True,
        )
        await interaction.followup.send(embed=embed)

    @_trackers.command(
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
        await interaction.response.defer()

        tz = await self.timezone(interaction.guild)
        date_cutoff = datetime.now(tz) - timedelta(days=days)

        log.debug(f"Getting tracker data older than {date_cutoff.date()}")
        trackers = await self.trackers(interaction.guild, status)

        log.debug(f"Removing recently updated trackers")
        old_trackers = []
        for t in trackers:
            if not t.last_updated:
                old_trackers.append(t)
            if t.last_updated.date() < date_cutoff.date():
                old_trackers.append(t)
        log.debug(f"Finished iterating tracker list")

        embed = YellowEmbed(
            title="Outdated RSC Trackers",
            description=f"Found **{len(old_trackers)}/{len(trackers)} {status.name}** trackers have not been updated since **{date_cutoff.date()}**",
        )
        await interaction.followup.send(embed=embed)

    # Non-Group Commands

    @app_commands.command(
        name="accounts",
        description="Display rocket league accounts associated with a player",
    )
    @app_commands.describe(player="RSC Discord Member")
    async def _accounts(self, interaction: discord.Interaction, player: discord.Member):
        await interaction.response.defer()

        try:
            trackers = await self.trackers(interaction.guild, player=player.id)
        except RscException as exc:
            await interaction.followup.send(embed=ApiExceptionErrorEmbed(exc))

        if not trackers:
            await interaction.followup.send(
                embed=YellowEmbed(
                    description=f"{player.display_name} does not have any registered RL trackers."
                ),
                ephemeral=True,
            )
            return

        frole = await utils.franchise_role_from_disord_member(player)

        desc = ""
        for t in trackers:
            url = await utils.fix_tracker_url(t.link)
            desc += f" - [{t.platform} - {t.platform_id or t.name}]({t.link})"

        embed = BlueEmbed(title=f"{player.display_name} Accounts", description=desc)

        if frole and frole.display_icon:
            embed.set_thumbnail(url=frole.display_icon.url)

        link_button = LinkButton(label="RSC Tracker Links", url=RSC_TRACKER_URL)
        account_view = discord.ui.View()
        account_view.add_item(link_button)

        await interaction.followup.send(embed=embed, view=account_view)

    # Functions

    # API

    async def trackers(
        self,
        guild: discord.Guild,
        status: TrackerLinksStatus | None = None,
        player: discord.Member | None = None,
        name: str | None = None,
    ) -> list[TrackerLink]:
        """Fetch RSC tracker data"""
        async with ApiClient(self._api_conf[guild.id]) as client:
            api = TrackerLinksApi(client)
            try:
                return await api.tracker_links_list(
                    status=str(status) if status else None,
                    discord_id=player.id if player else None,
                    member_name=name,
                )
            except ApiException as exc:
                raise RscException(repsonse=exc)

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
                raise RscException(repsonse=exc)

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
                raise RscException(repsonse=exc)
