import logging
from collections.abc import AsyncIterator
from operator import attrgetter

import discord
from rscapi import SeasonsApi
from rscapi.exceptions import ApiException
from rscapi.models import ActivityCheck
from rscapi.models.franchise_standings import FranchiseStandings
from rscapi.models.intent_to_play import IntentToPlay
from rscapi.models.paginated_activity_check_list import PaginatedActivityCheckList
from rscapi.models.season import Season

from rsc.abc import RSCMixIn
from rsc.exceptions import LeagueNotConfigured, RscException
from rsc.pagination import API_MAX_PAGE_SIZE, check_page_limit, iter_pages

log = logging.getLogger("red.rsc.seasons")


class SeasonsMixIn(RSCMixIn):
    def __init__(self):
        log.debug("Initializing SeasonsMixIn")
        # guild.id -> season number -> season ID, for the guild's league
        self._season_cache: dict[int, dict[int, int]] = {}
        super().__init__()

    # Season ID cache
    #
    # The API identifies seasons by ID while most payloads (e.g. a Match) carry only
    # the season number, and website links take the ID. Seasons change a few times a
    # year, so the map is built once at startup and refetched once on a miss, which
    # covers a season created while the bot is running.

    async def prepare_season_cache(self, guild: discord.Guild) -> None:
        """Build the guild's season number -> ID map. Never raises: a stale map only costs a refetch."""
        try:
            seasons = await self.seasons(guild)
        except RscException as exc:
            log.warning(f"[{guild.name}] Unable to cache seasons: {exc.reason or exc}")
            return
        self._season_cache[guild.id] = {s.number: s.id for s in seasons if s.number is not None and s.id is not None}

    async def season_id_for_number(self, guild: discord.Guild, number: int) -> int | None:
        """The ID of season `number` in the guild's league, or None if it doesn't exist."""
        season_id = self._season_cache.get(guild.id, {}).get(number)
        if season_id is None:
            await self.prepare_season_cache(guild)
            season_id = self._season_cache.get(guild.id, {}).get(number)
        return season_id

    async def season_number_for_id(self, guild: discord.Guild, season_id: int) -> int | None:
        """The number of the season with `season_id` in the guild's league, or None if it isn't one."""
        number = self._season_number(guild, season_id)
        if number is None:
            await self.prepare_season_cache(guild)
            number = self._season_number(guild, season_id)
        return number

    def _season_number(self, guild: discord.Guild, season_id: int) -> int | None:
        return next((n for n, sid in self._season_cache.get(guild.id, {}).items() if sid == season_id), None)

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
        async with self.api_client(guild) as client:
            api = SeasonsApi(client)
            league_id = self._league[guild.id]
            try:
                season_list = await api.seasons_list(league=league_id, number=number, current=current)
                return season_list
            except ApiException as exc:
                raise RscException(response=exc)

    async def season_by_id(self, guild: discord.Guild, season_id: int) -> Season:
        async with self.api_client(guild) as client:
            api = SeasonsApi(client)
            try:
                return await api.seasons_retrieve(season_id)
            except ApiException as exc:
                raise RscException(response=exc)

    async def next_signup_season(self, guild: discord.Guild) -> Season | None:
        """Query to API to find out if signups are open for any season"""
        async with self.api_client(guild) as client:
            api = SeasonsApi(client)
            league_id = self._league[guild.id]
            try:
                signup_season = await api.seasons_signup_season_retrieve(league=league_id)
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
        async with self.api_client(guild) as client:
            api = SeasonsApi(client)
            try:
                discord_id = player.id if player else None
                log.debug(f"Season Intent Data. Season: {season_id} Discord: {discord_id} Returning: {returning} Missing: {missing}")
                return await api.seasons_player_intents_list(
                    season_id,
                    discord_id=discord_id,
                    returning=returning,
                    missing=missing,
                )
            except ApiException as exc:
                raise RscException(response=exc)

    async def franchise_standings(self, guild: discord.Guild, season_id: int) -> list[FranchiseStandings]:
        async with self.api_client(guild) as client:
            api = SeasonsApi(client)
            try:
                return await api.seasons_franchise_standings_list(season_id)
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
        check_page_limit(limit, caller="season_activity_checks()")
        async with self.api_client(guild) as client:
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

    async def paged_activity_checks(
        self,
        guild: discord.Guild,
        season_id: int | None = None,
        season_number: int | None = None,
        discord_id: int | None = None,
        completed: bool | None = None,
        returning: bool | None = None,
        missing: bool | None = None,
        per_page: int = API_MAX_PAGE_SIZE,
    ) -> AsyncIterator[ActivityCheck]:
        """Every activity check matching the filters. `season_activity_checks()` alone returns a single page."""
        async with self.api_client(guild) as client:
            api = SeasonsApi(client)

            async def fetch(limit: int, offset: int) -> PaginatedActivityCheckList:
                try:
                    return await api.seasons_activity_check_list(
                        season=season_id,
                        season_number=season_number,
                        discord_id=discord_id,
                        completed=completed,
                        returning_status=returning,
                        missing=missing,
                        limit=limit,
                        offset=offset,
                    )
                except ApiException as exc:
                    raise RscException(response=exc)

            async for check in iter_pages(fetch, per_page=per_page):
                yield check
