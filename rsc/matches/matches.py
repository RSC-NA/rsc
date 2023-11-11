import discord
import logging
from pydantic import parse_obj_as

from redbot.core import app_commands, checks

from rscapi import ApiClient, LeaguesApi
from rscapi.models.league import League

from rsc.abc import RSCMeta
from rsc.embeds import ErrorEmbed
from rsc.teams import TeamMixIn

from typing import List, Optional

log = logging.getLogger("red.rsc.matches")


class MatchMixIn(metaclass=RSCMeta):
    # App Commands

    @app_commands.command(
        name="schedule", description="Display your team or another teams schedule"
    )
    @app_commands.autocomplete(team=TeamMixIn.teams_autocomplete)
    @app_commands.guild_only()
    async def _schedule(
        self, interaction: discord.Interaction, team: Optional[str] = None
    ):
        pass

    # Functionality
