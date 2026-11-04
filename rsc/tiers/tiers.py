import logging
from datetime import datetime, time
from zoneinfo import ZoneInfo

import discord
from pydantic import ValidationError
from redbot.core import app_commands
from rscapi import TiersApi
from rscapi.models.player_season_stats_in_depth import PlayerSeasonStatsInDepth
from rscapi.models.season import Season
from rscapi.models.tier import Tier
from rscapi.models.tier_playoff_hunt import TierPlayoffHunt
from rscapi.models.team_season_stats import TeamSeasonStats
from rscapi.models.team_standings import TeamStandings

from rsc.abc import RSCMixIn
from rsc.const import API_TIMEOUT
from rsc.exceptions import RscException
from rsc.tiers.views import TierRow, TiersCard
from rsc.utils.cache import merge_name_cache

log = logging.getLogger("red.rsc.tiers")


def _league_schedule(season: Season) -> tuple[tuple[str, ...], str | None] | None:
    """The match nights and start time, when every tier plays on the same schedule."""
    schedules = {(tuple(d.schedule.match_nights), d.schedule.match_start_time) if d.schedule else None for d in season.season_tier_data}
    return schedules.pop() if len(schedules) == 1 else None


def _match_time(start: str, tz: ZoneInfo) -> datetime | None:
    """Today's match start in the guild's timezone. `start` is the API's "HH:MM:SS"."""
    try:
        return datetime.combine(datetime.now(tz).date(), time.fromisoformat(start), tzinfo=tz)
    except ValueError:
        return None


class TierMixIn(RSCMixIn):
    def __init__(self):
        log.debug("Initializing TierMixIn")
        self._tier_cache: dict[int, list[str]] = {}
        super().__init__()

    # Autocomplete

    async def tier_autocomplete(self, interaction: discord.Interaction, current: str) -> list[app_commands.Choice[str]]:
        if not interaction.guild_id:
            return []

        # Return nothing if cache does not exist.
        if not self._tier_cache.get(interaction.guild_id):
            return []

        choices = []
        for t in self._tier_cache[interaction.guild_id]:
            if current.lower() in t.lower():
                choices.append(app_commands.Choice(name=t, value=t))
            if len(choices) == 25:
                return choices
        return choices

    # Commands

    @app_commands.command(name="tiers", description="Get a list of all league tiers")
    @app_commands.guild_only
    async def _tiers(self, interaction: discord.Interaction):
        """Get a list of all league tiers"""
        guild = interaction.guild
        if not guild:
            return

        await interaction.response.defer()
        card = await self.build_tiers_card(guild)
        await interaction.followup.send(view=card.render(), allowed_mentions=discord.AllowedMentions.none())

    # Functions

    async def build_tiers_card(self, guild: discord.Guild) -> TiersCard:
        tiers = await self.tiers(guild)
        try:
            season = await self.current_season(guild)
        except RscException as exc:
            log.warning(f"/tiers is showing tier names only, because the current season fetch failed: {exc}")
            season = None

        data = {d.tier: d for d in season.season_tier_data} if season else {}
        rows = []
        for t in tiers:
            role = discord.utils.get(guild.roles, name=t.name)
            d = data.get(t.name)
            rows.append(
                TierRow(
                    name=t.name,
                    role_id=role.id if role else None,
                    mmr_min=d.mmr_min if d else None,
                    mmr_max=d.mmr_max if d else None,
                    teams=d.team_number if d else None,
                    team_cap=d.team_cap if d else None,
                )
            )

        heading = guild.name
        if season and season.league.name and season.number is not None:
            heading = f"{season.league.name} · Season {season.number}"

        nights: tuple[str, ...] = ()
        match_time = None
        if season and (schedule := _league_schedule(season)):
            nights, start = schedule
            match_time = _match_time(start, await self.timezone(guild)) if start else None

        return TiersCard(
            heading=heading,
            rows=tuple(rows),
            icon_url=guild.icon.url if guild.icon else None,
            match_nights=nights,
            match_time=match_time,
        )

    async def is_valid_tier(self, guild: discord.Guild, name: str) -> bool:
        """Check if name is in the tier cache"""
        if not self._tier_cache.get(guild.id):
            return False

        return name in self._tier_cache[guild.id]

    async def tier_fa_roles(self, guild: discord.Guild) -> list[discord.Role]:
        """Return a list of tier free agent roles (Ex: ProspectFA)"""
        tiers = await self.tiers(guild)
        roles = []
        for t in tiers:
            r = discord.utils.get(guild.roles, name=f"{t.name}FA")
            if r:
                roles.append(r)
        return roles

    async def tier_id_by_name(self, guild: discord.Guild, tier: str) -> int:
        """Return a tier ID by its name"""
        tiers = await self.tiers(guild, name=tier)
        if not tiers:
            raise ValueError(f"Tier does not exist: **{tier}**")
        if len(tiers) > 1:
            raise ValueError(f"Found more than one tier matching: **{tier}**")

        t = tiers.pop(0)
        if t.id is None:
            raise ValueError("Found tier in API but it does not have an ID")

        return t.id

    # API

    async def tier_by_id(self, guild: discord.Guild, id: int) -> Tier:
        async with self.api_client(guild) as client:
            api = TiersApi(client)
            tier = await api.tiers_retrieve(id)
            return tier

    async def tiers(self, guild: discord.Guild, name: str | None = None) -> list[Tier]:
        """Fetch a list of tiers"""
        # An unfiltered query returns the authoritative full list, so the cache
        # is rebuilt from it. A filtered one can only add. Merging in both cases
        # meant a renamed or deleted tier lingered in autocomplete until restart.
        full_refresh = name is None

        async with self.api_client(guild) as client:
            api = TiersApi(client)
            tiers = await api.tiers_list(name=name, league=self._league[guild.id], _request_timeout=API_TIMEOUT)
            tiers.sort(key=lambda t: t.position, reverse=True)

            # Populate cache
            if tiers:
                if not all(t.name for t in tiers):
                    raise AttributeError("API returned a tier with no name.")

                self._tier_cache[guild.id] = merge_name_cache(
                    self._tier_cache.get(guild.id, []),
                    (t.name for t in tiers if t.name),
                    full_refresh=full_refresh,
                )
            return tiers

    async def tier_standings(self, guild: discord.Guild, tier_id: int, season: int) -> list[TeamStandings]:
        """Fetch a list of tiers"""
        async with self.api_client(guild) as client:
            api = TiersApi(client)
            standings: list[TeamStandings] = await api.tiers_standings_list(id=tier_id, season_number=season)
            standings.sort(key=lambda t: (t.rank, t.team))
            return standings

    async def tier_playoff_hunt(self, guild: discord.Guild, tier_id: int, season: int | None = None) -> TierPlayoffHunt:
        """The tier's playoff hunt: each playoff group's teams in standings order, with the cut line."""
        async with self.api_client(guild) as client:
            api = TiersApi(client)
            return await api.tiers_playoffs_retrieve(
                id=tier_id,
                league=self._league[guild.id],
                season_number=season,
                _request_timeout=API_TIMEOUT,
            )

    async def tier_player_stats(
        self,
        guild: discord.Guild,
        tier_id: int,
        season: int | None = None,
    ) -> list[PlayerSeasonStatsInDepth]:
        """Season stats for every player in a tier, in a single request.

        Each record carries server-computed ranks (`goals_rank`, `points_rank`,
        ...), so leaderboards need no client side sorting pass over the league.
        """
        async with self.api_client(guild) as client:
            api = TiersApi(client)
            return await api.tiers_player_stats_list(
                id=tier_id,
                league=self._league[guild.id],
                season_number=season,
                _request_timeout=API_TIMEOUT,
            )

    async def tier_team_stats(
        self,
        guild: discord.Guild,
        tier_id: int,
        season: int | None = None,
    ) -> list[TeamSeasonStats]:
        """Season stats for every team in a tier, in a single request."""
        async with self.api_client(guild) as client:
            api = TiersApi(client)
            return await api.tiers_team_stats_list(
                id=tier_id,
                league=self._league[guild.id],
                season_number=season,
                _request_timeout=API_TIMEOUT,
            )

    async def create_tier(self, guild: discord.Guild, name: str, color: int, position: int) -> Tier:
        async with self.api_client(guild) as client:
            api = TiersApi(client)
            try:
                data = Tier(name=name, color=color, position=position)
            except ValidationError as exc:
                raise RscException(message=f"Invalid tier data: {exc.errors()[0]['msg']}")

            log.debug(f"Create Tier Data: {data}")
            return await api.tiers_create(data)

    async def delete_tier(self, guild: discord.Guild, id: int) -> None:
        async with self.api_client(guild) as client:
            api = TiersApi(client)
            return await api.tiers_destroy(id)
