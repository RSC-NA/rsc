import logging
from operator import attrgetter

import discord
from rscapi import ApiClient, SeasonsApi
from rscapi.exceptions import ApiException
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

    async def seasons(self, guild: discord.Guild) -> list[Season]:
        async with ApiClient(self._api_conf[guild.id]) as client:
            api = SeasonsApi(client)
            try:
                season_list = await api.seasons_list()
                seasons = [x for x in season_list if x.league.id == self._league[guild.id]]
                return seasons
            except ApiException as exc:
                raise RscException(response=exc)

    async def season_by_id(self, guild: discord.Guild, season_id: int) -> Season:
        async with ApiClient(self._api_conf[guild.id]) as client:
            api = SeasonsApi(client)
            try:
                return await api.seasons_read(season_id)
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
