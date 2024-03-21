import logging

import discord
from rscapi import ApiClient, SeasonsApi
from rscapi.exceptions import ApiException
from rscapi.models.franchise_standings import FranchiseStandings
from rscapi.models.intent_to_play import IntentToPlay
from rscapi.models.season import Season

from rsc.abc import RSCMixIn
from rsc.exceptions import RscException

log = logging.getLogger("red.rsc.seasons")


class SeasonsMixIn(RSCMixIn):
    def __init__(self):
        log.debug("Initializing SeasonsMixIn")
        super().__init__()

    # API Commands

    async def seasons(self, guild: discord.Guild) -> list[Season]:
        async with ApiClient(self._api_conf[guild.id]) as client:
            api = SeasonsApi(client)
            try:
                season_list = await api.seasons_list()
                seasons = [
                    x for x in season_list if x.league.id == self._league[guild.id]
                ]
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
        self, guild: discord.Guild, season_id: int
    ) -> IntentToPlay:
        async with ApiClient(self._api_conf[guild.id]) as client:
            api = SeasonsApi(client)
            try:
                return await api.seasons_player_intents(season_id)
            except ApiException as exc:
                raise RscException(response=exc)

    async def franchise_standings(
        self, guild: discord.Guild, season_id: int
    ) -> list[FranchiseStandings]:
        async with ApiClient(self._api_conf[guild.id]) as client:
            api = SeasonsApi(client)
            try:
                return await api.seasons_franchise_standings(season_id)
            except ApiException as exc:
                raise RscException(response=exc)
