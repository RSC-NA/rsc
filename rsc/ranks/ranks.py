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
from rsc.enums import TrackerLinksStatus, Status, RLStatType, RLChallengeType, AnsiColor, RankedPlaylist
from rsc.const import CAPTAIN_ROLE, DEV_LEAGUE_ROLE, FREE_AGENT_ROLE, RSC_TRACKER_URL, SEASON_TITLE_REGEX
from rsc.embeds import (
    ErrorEmbed,
    SuccessEmbed,
    YellowEmbed,
    WarningEmbed,
    RapidQuotaEmbed,
    RapidTimeOutEmbed,
    CooldownEmbed,
    BlueEmbed,
    OrangeEmbed,
    ExceptionErrorEmbed,
    ApiExceptionErrorEmbed,
)
from rsc.exceptions import RscException, RapidQuotaExceeded, RapidApiTimeOut
from rsc.teams import TeamMixIn
from rsc.transactions.views import TradeAnnouncementModal, TradeAnnouncementView
from rsc.types import Substitute
from rsc.utils import utils
from rsc.views import LinkButton


from typing import Optional, TypedDict, List

log = logging.getLogger("red.rsc.ranks")


class RankMixIn(RSCMixIn):
    def __init__(self):
        log.debug("Initializing RankMixIn")
        super().__init__()

    _rl = app_commands.Group(
        name="rl",
        description="Display Rocket League related information",
        guild_only=True,
    )

    # RL Group Commands

    @_rl.command(name="ranks", description="Display rocket league rank (Epic Only)")
    @app_commands.describe(player="RSC Discord Member")
    # @app_commands.checks.cooldown(1, 60.0, key=lambda i: (i.guild_id, i.user.id))
    async def _rl_ranks(self, interaction: discord.Interaction, player: discord.Member):
        api = await self.rapid_connector(interaction.guild)
        if not api:
            await interaction.response.send_message(
                embed=WarningEmbed(
                    description=f"RapidAPI is not currently configured."
                ),
                ephemeral=True,
            )
            return

        await interaction.response.defer()
        trackers = await self.trackers(interaction.guild, player=player)

        embed = BlueEmbed(
            title=f"{player.display_name} Ranks",
            description="Rocket League rank by playlist. Only displays known **Epic** accounts.",
        )

        try:
            for t in trackers:
                log.debug(f"Tracker: {t}")
                if t.platform != "EPIC":
                    continue
                data = await api.ranks(t.name)
                if not data:
                    continue

                embed.add_field(name="Epic", value=t.name, inline=False)
                for r in data.ranks:
                    match r.playlist:
                        case RankedPlaylist.DUEL:
                            embed.add_field(name="Duel", value=r.mmr, inline=True)
                        case RankedPlaylist.DOUBLES:
                            embed.add_field(name="Doubles", value=r.mmr, inline=True)
                        case RankedPlaylist.STANDARD:
                            embed.add_field(name="Standard", value=r.mmr, inline=True)
        except RapidQuotaExceeded:
            await interaction.followup.send(embed=RapidQuotaEmbed(), ephemeral=True)
            return
        except RapidApiTimeOut:
            await interaction.followup.send(embed=RapidTimeOutEmbed(), ephemeral=True)
            return

        await interaction.followup.send(embed=embed)

    @_rl.command(
        name="stats", description="Display rocket league stats for Epic accounts"
    )
    @app_commands.describe(stat="Stat type to query", player="RSC Discord Member")
    # @app_commands.checks.cooldown(1, 60.0, key=lambda i: (i.guild_id, i.user.id))
    async def _rl_stats(
        self, interaction: discord.Interaction, stat: RLStatType, player: discord.Member
    ):
        api = await self.rapid_connector(interaction.guild)
        if not api:
            await interaction.response.send_message(
                embed=WarningEmbed(
                    description=f"RapidAPI is not currently configured."
                ),
                ephemeral=True,
            )
            return

        await interaction.response.defer()
        members = await self.members(interaction.guild, discord_id=player.id, limit=1)
        if not members:
            await interaction.followup.send(
                embed=OrangeEmbed(
                    title="Player Ranks",
                    description=f"{player.mention} is not an RSC member.",
                ),
                ephemeral=True,
            )
            return

        trackers = await self.trackers(interaction.guild, name=members[0].rsc_name)

        embed = BlueEmbed(
            title=f"{members[0].rsc_name.title()} RL {stat}",
            description=f"Displaying {stat.name.lower()} statistics. Only displays known **Epic** accounts.",
        )

        stats = {}
        try:
            for t in trackers:
                if t.platform != "EPIC":
                    continue
                data = await api.stat(stat, t.name)
                if data:
                    stats[t.name] = data.value
        except RapidQuotaExceeded:
            await interaction.followup.send(embed=RapidQuotaEmbed(), ephemeral=True)
            return
        except RapidApiTimeOut:
            await interaction.followup.send(embed=RapidTimeOutEmbed(), ephemeral=True)
            return

        embed.add_field(
            name="Account", value="\n".join([k for k in stats.keys()]), inline=True
        )
        embed.add_field(
            name="Stat Count", value="\n".join([str(v) for v in stats.values()]), inline=True
        )

        await interaction.followup.send(embed=embed)

    @_rl.command(
        name="status", description="Display rocket league status for Epic accounts"
    )
    @app_commands.describe(player="RSC Discord Member")
    # @app_commands.checks.cooldown(1, 60.0, key=lambda i: (i.guild_id, i.user.id))
    async def _rl_status(
        self, interaction: discord.Interaction, player: discord.Member
    ):
        api = await self.rapid_connector(interaction.guild)
        if not api:
            await interaction.response.send_message(
                embed=WarningEmbed(
                    description=f"RapidAPI is not currently configured."
                ),
                ephemeral=True,
            )
            return

        await interaction.response.defer()
        members = await self.members(interaction.guild, discord_id=player.id, limit=1)
        if not members:
            await interaction.followup.send(
                embed=OrangeEmbed(
                    title="Player RL Status",
                    description=f"{player.mention} is not an RSC member.",
                ),
                ephemeral=True,
            )
            return

        trackers = await self.trackers(interaction.guild, name=members[0].rsc_name)

        embed = BlueEmbed(
            title=f"{members[0].rsc_name} RL Status".title(),
            description=f"Displaying Rocket League status for player. Only displays known **Epic** accounts.",
        )

        profiles = []
        try:
            for t in trackers:
                if t.platform != "EPIC":
                    continue
                data = await api.profile(t.name)
                if data:
                    profiles.append(data)
        except RapidQuotaExceeded:
            await interaction.followup.send(embed=RapidQuotaEmbed(), ephemeral=True)
            return
        except RapidApiTimeOut:
            await interaction.followup.send(embed=RapidTimeOutEmbed(), ephemeral=True)
            return

        embed.add_field(
            name="Account", value="\n".join([p.name for p in profiles]), inline=True
        )
        embed.add_field(
            name="Status", value="\n".join([p.presence for p in profiles]), inline=True
        )

        await interaction.followup.send(embed=embed)


    @_rl.command(
        name="titles", description="Display rocket league titles for Epic account"
    )
    @app_commands.describe(player="Rocket League Epic Account name or Epic ID")
    # @app_commands.checks.cooldown(1, 60.0, key=lambda i: (i.guild_id, i.user.id))
    async def _rl_status(
        self, interaction: discord.Interaction, player: str 
    ):
        api = await self.rapid_connector(interaction.guild)
        if not api:
            await interaction.response.send_message(
                embed=WarningEmbed(
                    description=f"RapidAPI is not currently configured."
                ),
                ephemeral=True,
            )
            return

        await interaction.response.defer()
        try:
            titles = await api.titles(player)
        except RapidQuotaExceeded:
            await interaction.followup.send(embed=RapidQuotaEmbed(), ephemeral=True)
            return
        except RapidApiTimeOut:
            await interaction.followup.send(embed=RapidTimeOutEmbed(), ephemeral=True)
            return

        if not titles:
            await interaction.followup.send(embed=OrangeEmbed(title=f"{player} RL Titles", description=f"No data found for **{player}**"), ephemeral=True)
            return

        desc = "Displaying Rocket League titles for Epic account.\n\n```ansi\n"

        for t in titles:
            # Only display season titles (List would be too large otherwise)
            if SEASON_TITLE_REGEX.match(t.name):
                # Actual conversion isn't working in discord
                # c = AnsiColor.RED.from_rgb_hex(t.color, bold=True)
                # log.debug(f"Ansi Repr: {repr(c)}")
                # desc += f" - {c}{t.name}\u001b[0m\n"
                if t.color == "#ff2800":
                    desc += f" - {AnsiColor.RED.bold_colored_text(t.name)}\n"
                else:
                    desc += f" - **{t.name}**\n"
        desc += "```"

        embed = BlueEmbed(
            title=f"{player.title()} RL Titles",
            description=desc,
        )

        await interaction.followup.send(embed=embed)