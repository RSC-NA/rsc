import discord
import logging

from discord.ext import tasks
from datetime import datetime, time, timedelta

from redbot.core import Config, app_commands, commands, checks

from rscapi import ApiClient, TransactionsApi, LeaguePlayersApi
from rscapi.exceptions import ApiException
from rscapi.models.cut_a_player_from_a_league import CutAPlayerFromALeague
from rscapi.models.re_sign_player import ReSignPlayer
from rscapi.models.sign_a_player_to_a_team_in_a_league import (
    SignAPlayerToATeamInALeague,
)
from rscapi.models.transaction_response import TransactionResponse
from rscapi.models.player_transaction_updates import PlayerTransactionUpdates
from rscapi.models.temporary_fa_sub import TemporaryFASub
from rscapi.models.player_transaction_updates import PlayerTransactionUpdates
from rscapi.models.expire_a_player_sub import ExpireAPlayerSub
from rscapi.models.league_player import LeaguePlayer

from rsc.abc import RSCMixIn
from rsc.enums import Status
from rsc.const import CAPTAIN_ROLE, DEV_LEAGUE_ROLE, FREE_AGENT_ROLE
from rsc.embeds import (
    ErrorEmbed,
    SuccessEmbed,
    BlueEmbed,
    ExceptionErrorEmbed,
    ApiExceptionErrorEmbed,
)
from rsc.exceptions import RscException, translate_api_error
from rsc.teams import TeamMixIn
from rsc.transactions.views import TradeAnnouncementModal, TradeAnnouncementView
from rsc.types import Substitute
from rsc.utils import utils


from typing import Optional, TypedDict, List

log = logging.getLogger("red.rsc.trackers")


class TrackerMixIn(RSCMixIn):
    def __init__(self):
        log.debug("Initializing TrackersMixIn")
        super().__init__()

    # Top Level Groups

    _trackers = app_commands.Group(
        name="trackers", description="RSC Player Tracker Links", guild_only=True
    )

    # App Commands
    
    @_trackers.command(name="list", description="List the trackers")
    async def _trackers_list(self, interaction: discord.Interaction, member: discord.Member):
        pass

    # API

