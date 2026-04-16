import logging
from operator import attrgetter

import discord
from rscapi import ApiClient, SeasonsApi
from rscapi.exceptions import ApiException
from rscapi.models import ActivityCheck
from rscapi.models.franchise_standings import FranchiseStandings
from rscapi.models.intent_to_play import IntentToPlay
from rscapi.models.season import Season

from rsc.abc import RSCMixIn
from rsc.exceptions import LeagueNotConfigured, RscException

log = logging.getLogger("red.rsc.seasons")


class SeasonsMixIn(RSCMixIn):
    def __init__(self):
        log.debug("Initializing SeasonsMixIn")
        super().__init__()

    # Helper Functions

    async def next_season(self, guild: discord.Guild) -> Season | None:
        league_id = self._league[guild.id]
        if not league_id:
            raise LeagueNotConfigured("Guild does not have a league configured.")

        seasons: list[Season] = await self.seasons(guild)
        if not seasons:
            return None

        league_seasons = list(filter(lambda league: league.league.id == league_id, seasons))
        log.debug(f"league_seasons: {league_seasons}")
        if not league_seasons:
            return None

        next_season = max(league_seasons, key=attrgetter("number"))
        log.debug(f"Newest Season. ID: {next_season.id} Season Number: {next_season.number}")

        return next_season

    # API Commands

    async def seasons(self, guild: discord.Guild, number: int | None = None, current: bool | None = None) -> list[Season]:
        async with ApiClient(self._api_conf[guild.id]) as client:
            api = SeasonsApi(client)
            league_id = self._league[guild.id]
            try:
                season_list = await api.seasons_list(league=league_id, number=number, current=current)
                return season_list
            except ApiException as exc:
                raise RscException(response=exc)

    async def season_by_id(self, guild: discord.Guild, season_id: int) -> Season:
        async with ApiClient(self._api_conf[guild.id]) as client:
            api = SeasonsApi(client)
            try:
                return await api.seasons_read(season_id)
            except ApiException as exc:
                raise RscException(response=exc)

    async def next_signup_season(self, guild: discord.Guild) -> Season | None:
        """Query to API to find out if signups are open for any season"""
        async with ApiClient(self._api_conf[guild.id]) as client:
            api = SeasonsApi(client)
            league_id = self._league[guild.id]
            try:
                signup_season = await api.seasons_signup_season(league=league_id)
                log.debug("Signup Season Number: %d", signup_season.number if signup_season else None)
                return signup_season
            except ApiException as exc:
                raise RscException(response=exc)

    async def player_intents(
        self,
        guild: discord.Guild,
        season_id: int,
        player: discord.Member | None = None,
        returning: bool | None = None,
        missing: bool | None = None,
    ) -> list[IntentToPlay]:
        async with ApiClient(self._api_conf[guild.id]) as client:
            api = SeasonsApi(client)
            try:
                discord_id = player.id if player else None
                log.debug(f"Season Intent Data. Season: {season_id} Discord: {discord_id} Returning: {returning} Missing: {missing}")
                return await api.seasons_player_intents(
                    season_id,
                    discord_id=discord_id,
                    returning=returning,
                    missing=missing,
                )
            except ApiException as exc:
                raise RscException(response=exc)

    async def franchise_standings(self, guild: discord.Guild, season_id: int) -> list[FranchiseStandings]:
        async with ApiClient(self._api_conf[guild.id]) as client:
            api = SeasonsApi(client)
            try:
                return await api.seasons_franchise_standings(season_id)
            except ApiException as exc:
                raise RscException(response=exc)

    async def season_activity_checks(
        self,
        guild: discord.Guild,
        season_id: int | None = None,
        season_number: int | None = None,
        discord_id: int | None = None,
        completed: bool | None = None,
        returning: bool | None = None,
        missing: bool | None = None,
        limit: int = 50,
        offset: int = 0,
    ) -> list[ActivityCheck]:
        async with ApiClient(self._api_conf[guild.id]) as client:
            api = SeasonsApi(client)
            try:
                resp = await api.seasons_activity_check_list(
                    season=season_id,
                    season_number=season_number,
                    discord_id=discord_id,
                    completed=completed,
                    returning_status=returning,
                    missing=missing,
                    limit=limit,
                    offset=offset,
                )
                return resp.results
            except ApiException as exc:
                raise RscException(response=exc)
