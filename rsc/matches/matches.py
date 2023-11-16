import discord
import logging
from datetime import datetime

from redbot.core import app_commands, checks

from rscapi import ApiClient, MatchesApi
from rscapi.models.league import League
from rscapi.models.matches_list200_response import MatchesList200Response
from rscapi.models.match_list import MatchList
from rscapi.models.match import Match

from rsc.abc import RSCMixIn
from rsc.enums import MatchType, MatchFormat
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

    async def matches_from_match_list(self, match_list: List[MatchList]):
        pass

    # Api

    async def matches(
        self,
        guild: discord.Guild,
        date__lt: Optional[datetime]=None,
        date__gt: Optional[datetime]=None,
        season: Optional[str]=None,
        season_number: Optional[str]=None,
        home_team: Optional[str]=None,
        away_team: Optional[str]=None,
        day: Optional[str]=None,
        match_type: Optional[MatchType]=None,
        match_format: Optional[MatchFormat]=None,
        limit: int=0,
        offset: int=0,
    ) -> List[MatchList]:
        async with ApiClient(self._api_conf[guild.id]) as client:
            api = MatchesApi(client)
            matches: MatchesList200Response = await api.matches_list(
                date__lt=date__lt.isoformat() if date__lt else None,
                date__gt=date__gt.isoformat() if date__gt else None,
                season=season,
                season_number=season_number,
                home_team=home_team,
                away_team=away_team,
                day=day,
                match_type=str(match_type) if match_type else None,
                match_format=str(match_format) if match_format else None,
                league=str(self._league[guild.id]),
                limit=limit,
                offset=offset
            )
            return matches.results
        
    async def match_by_id(
        self,
        guild: discord.Guild,
        id: int 
    ) -> Match:
        async with ApiClient(self._api_conf[guild.id]) as client:
            api = MatchesApi(client)
            return await api.matches_read(id)