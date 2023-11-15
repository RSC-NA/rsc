import discord
import logging
from datetime import datetime
from pytz import timezone

from redbot.core import app_commands, checks

from rscapi import ApiClient, LeaguesApi
from rscapi.models.league import League

from rsc.abc import RSCMixIn
from rsc.embeds import ErrorEmbed
from rsc.teams import TeamMixIn

from typing import List, Optional

log = logging.getLogger("red.rsc.matches")


class MatchMixIn(RSCMixIn):
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

    # Functions

    async def is_match_day(self, guild: discord.Guild) -> bool:
        season = await self.current_season(guild)
        if not season:
            return False
        if not season.season_tier_data:
            return False

        tz = await self.timezone(guild)
        today = datetime.now(tz).strftime("%A")
        if today in season.season_tier_data[0].schedule.match_nights:
            return True
        return False
        
