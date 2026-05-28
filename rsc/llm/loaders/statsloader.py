import logging
from collections.abc import AsyncIterator, Iterator

from langchain_core.document_loaders import BaseLoader
from langchain_core.documents import Document
from rscapi.models.franchise_standings import FranchiseStandings
from rscapi.models.player_season_stats import PlayerSeasonStats
from rscapi.models.team_season_stats import TeamSeasonStats
from rscapi.models.team_standings import TeamStandings

log = logging.getLogger("red.rsc.llm.loaders.statsloader")


PLAYER_STATS_INPUT = """
{player} has RSC player stats for Season {season} ({stats_type}).

Record: {games_won} wins and {games_lost} losses in {games_played} games played.
Scoring: {goals} goals, {assists} assists, {saves} saves, {shots} shots, {points} points, {mvps} MVPs.
Rates: {goals_per_game} goals per game, {points_per_game} points per game, {shooting_percentage}% shooting percentage.
Advanced stats: {avg_speed} average speed, {bpm} boost per minute, {bcpm} boost collected per minute.
Demos: {demos_inflicted} demos inflicted, {demos_taken} demos taken.
""".strip()

TEAM_STATS_INPUT = """
{team} has RSC team stats{season_context} ({stats_type}).

Record: {games_won} wins and {games_lost} losses in {games_played} games played with a {win_percentage}% win percentage.
Scoring: {goals} goals, {assists} assists, {saves} saves, {shots} shots, {points} points.
Opponent stats: {opponent_goals} goals allowed, {opponent_assists} assists allowed, {opponent_saves} saves allowed.
Opponent shots and points: {opponent_shots} shots allowed, {opponent_points} opponent points.
Rates: {goals_per_game} goals per game, {points_per_game} points per game, {shooting_percentage}% shooting percentage.
Opponent rate: {opponent_shooting_percentage}% opponent shooting percentage.
Differential: {goal_differential} goal differential. Physical play: {demos_inflicted} demos inflicted, {demos_taken} demos taken.
""".strip()

FRANCHISE_STANDINGS_INPUT = """
{franchise} is ranked #{rank} in Season {season} franchise standings.

General Manager: {gm}.
Record: {wins} wins and {losses} losses with a {win_percentage}% win percentage.
""".strip()

TEAM_STANDINGS_INPUT = """
{team} is ranked #{rank} in Season {season} {tier} tier standings.

{team} belongs to the {franchise} franchise.
Record: {games_won} wins and {games_lost} losses in {games_played} games played.
""".strip()


def _value(value: object | None, default: str = "unknown") -> object:
    return default if value is None else value


def _numeric(value: object | None) -> int | float:
    return value if isinstance(value, int | float) else 0


def _stat_number(value: object | None) -> str:
    number = _numeric(value)
    if isinstance(number, float):
        return f"{number:.2f}"
    return str(number)


def _ratio(numerator: object | None, denominator: object | None) -> str:
    denominator_value = _numeric(denominator)
    if not denominator_value:
        return "0.00"
    return f"{_numeric(numerator) / denominator_value:.2f}"


def _percentage(value: object | None) -> str:
    if value is None:
        return "unknown"
    if isinstance(value, int | float):
        return f"{value:.2f}"
    return str(value)


def _stats_type(stats: object) -> str:
    stats_type = getattr(stats, "stats_type", None) or getattr(stats, "type", None)
    if hasattr(stats_type, "value"):
        return str(stats_type.value)
    return str(_value(stats_type, "regular season"))


class PlayerStatsDocumentLoader(BaseLoader):
    """RSC player stats document loader."""

    def __init__(self, stats: list[PlayerSeasonStats]) -> None:
        self.stats = stats

    def _process_stats(self) -> Iterator[Document]:
        for idx, stats in enumerate(self.stats):
            player = getattr(stats, "player", None)
            stats_id = getattr(stats, "id", None)
            season = getattr(stats, "season", None)
            if not (stats_id and player and season):
                log.warning("Skipping player stats with missing identity data: %s", stats)
                continue

            games_played = getattr(stats, "games_played", None)
            goals = getattr(stats, "goals", None)
            points = getattr(stats, "points", None)
            yield Document(
                page_content=PLAYER_STATS_INPUT.format(
                    player=player,
                    season=season,
                    stats_type=_stats_type(stats),
                    games_played=_stat_number(games_played),
                    games_won=_stat_number(getattr(stats, "games_won", None)),
                    games_lost=_stat_number(getattr(stats, "games_lost", None)),
                    goals=_stat_number(goals),
                    assists=_stat_number(getattr(stats, "assists", None)),
                    saves=_stat_number(getattr(stats, "saves", None)),
                    shots=_stat_number(getattr(stats, "shots", None)),
                    points=_stat_number(points),
                    mvps=_stat_number(getattr(stats, "mvps", None)),
                    goals_per_game=_ratio(goals, games_played),
                    points_per_game=_ratio(points, games_played),
                    shooting_percentage=_percentage(getattr(stats, "shooting_percentage", None)),
                    avg_speed=_stat_number(getattr(stats, "avg_speed", None)),
                    bpm=_stat_number(getattr(stats, "bpm", None)),
                    bcpm=_stat_number(getattr(stats, "bcpm", None)),
                    demos_inflicted=_stat_number(getattr(stats, "demos_inflicted", None)),
                    demos_taken=_stat_number(getattr(stats, "demos_taken", None)),
                ),
                metadata={
                    "source": "Player Stats API",
                    "id": str(stats_id),
                    "chunk_index": idx,
                    "entity_name": player,
                    "player": player,
                    "season_number": season,
                    "stats_type": _stats_type(stats),
                },
            )

    def lazy_load(self) -> Iterator[Document]:
        yield from self._process_stats()

    async def alazy_load(self) -> AsyncIterator[Document]:
        for doc in self._process_stats():
            yield doc


class TeamStatsDocumentLoader(BaseLoader):
    """RSC team stats document loader."""

    def __init__(self, stats: list[TeamSeasonStats], season_number: int | None = None) -> None:
        self.stats = stats
        self.season_number = season_number

    @property
    def season_context(self) -> str:
        if not self.season_number:
            return " for the current season"
        return f" for Season {self.season_number}"

    def _process_stats(self) -> Iterator[Document]:
        for idx, stats in enumerate(self.stats):
            team = getattr(stats, "team", None)
            stats_id = getattr(stats, "id", None)
            if not (stats_id and team):
                log.warning("Skipping team stats with missing identity data: %s", stats)
                continue

            games_played = getattr(stats, "games_played", None)
            goals = getattr(stats, "goals", None)
            points = getattr(stats, "points", None)
            metadata: dict[str, object] = {
                "source": "Team Stats API",
                "id": str(stats_id),
                "chunk_index": idx,
                "entity_name": team,
                "team": team,
                "stats_type": _stats_type(stats),
            }
            if self.season_number:
                metadata["season_number"] = self.season_number

            yield Document(
                page_content=TEAM_STATS_INPUT.format(
                    team=team,
                    season_context=self.season_context,
                    stats_type=_stats_type(stats),
                    games_played=_stat_number(games_played),
                    games_won=_stat_number(getattr(stats, "games_won", None)),
                    games_lost=_stat_number(getattr(stats, "games_lost", None)),
                    win_percentage=_percentage(getattr(stats, "win_percentage", None)),
                    goals=_stat_number(goals),
                    assists=_stat_number(getattr(stats, "assists", None)),
                    saves=_stat_number(getattr(stats, "saves", None)),
                    shots=_stat_number(getattr(stats, "shots", None)),
                    points=_stat_number(points),
                    opponent_goals=_stat_number(getattr(stats, "opponent_goals", None)),
                    opponent_assists=_stat_number(getattr(stats, "opponent_assists", None)),
                    opponent_saves=_stat_number(getattr(stats, "opponent_saves", None)),
                    opponent_shots=_stat_number(getattr(stats, "opponent_shots", None)),
                    opponent_points=_stat_number(getattr(stats, "opponent_points", None)),
                    goals_per_game=_ratio(goals, games_played),
                    points_per_game=_ratio(points, games_played),
                    shooting_percentage=_percentage(getattr(stats, "shooting_percentage", None)),
                    opponent_shooting_percentage=_percentage(getattr(stats, "opponent_shooting_percentage", None)),
                    goal_differential=_stat_number(getattr(stats, "goal_differential", None)),
                    demos_inflicted=_stat_number(getattr(stats, "demos_inflicted", None)),
                    demos_taken=_stat_number(getattr(stats, "demos_taken", None)),
                ),
                metadata=metadata,
            )

    def lazy_load(self) -> Iterator[Document]:
        yield from self._process_stats()

    async def alazy_load(self) -> AsyncIterator[Document]:
        for doc in self._process_stats():
            yield doc


class StandingsDocumentLoader(BaseLoader):
    """RSC franchise and team standings document loader."""

    def __init__(
        self,
        franchise_standings: list[FranchiseStandings] | None = None,
        team_standings: list[TeamStandings] | None = None,
        season_number: int | None = None,
    ) -> None:
        self.franchise_standings = franchise_standings or []
        self.team_standings = team_standings or []
        self.season_number = season_number

    def _process_franchise_standings(self) -> Iterator[Document]:
        for idx, standing in enumerate(self.franchise_standings):
            franchise = getattr(standing, "franchise", None)
            rank = getattr(standing, "franchise_standings_rank", None)
            if not (franchise and rank):
                log.warning("Skipping franchise standing with missing identity data: %s", standing)
                continue

            yield Document(
                page_content=FRANCHISE_STANDINGS_INPUT.format(
                    franchise=franchise,
                    rank=rank,
                    season=_value(self.season_number, "current"),
                    gm=_value(getattr(standing, "gm", None)),
                    wins=_stat_number(getattr(standing, "wins", None)),
                    losses=_stat_number(getattr(standing, "losses", None)),
                    win_percentage=_percentage(getattr(standing, "win_percentage", None)),
                ),
                metadata={
                    "source": "Franchise Standings API",
                    "id": f"franchise:{franchise}",
                    "chunk_index": idx,
                    "entity_name": franchise,
                    "franchise": franchise,
                    "standings_scope": "franchise",
                    "rank": rank,
                    "season_number": self.season_number,
                },
            )

    def _process_team_standings(self, chunk_offset: int) -> Iterator[Document]:
        for idx, standing in enumerate(self.team_standings, start=chunk_offset):
            team = getattr(standing, "team", None)
            tier = getattr(standing, "tier", None)
            rank = getattr(standing, "rank", None)
            if not (team and tier and rank):
                log.warning("Skipping team standing with missing identity data: %s", standing)
                continue

            yield Document(
                page_content=TEAM_STANDINGS_INPUT.format(
                    team=team,
                    rank=rank,
                    season=_value(self.season_number, "current"),
                    tier=tier,
                    franchise=_value(getattr(standing, "franchise", None)),
                    games_played=_stat_number(getattr(standing, "games_played", None)),
                    games_won=_stat_number(getattr(standing, "games_won", None)),
                    games_lost=_stat_number(getattr(standing, "games_lost", None)),
                ),
                metadata={
                    "source": "Tier Standings API",
                    "id": f"team:{team}:{tier}",
                    "chunk_index": idx,
                    "entity_name": team,
                    "team": team,
                    "franchise": getattr(standing, "franchise", None),
                    "tier": tier,
                    "standings_scope": "team",
                    "rank": rank,
                    "season_number": self.season_number,
                },
            )

    def _process_standings(self) -> Iterator[Document]:
        franchise_docs = list(self._process_franchise_standings())
        yield from franchise_docs
        yield from self._process_team_standings(len(franchise_docs))

    def lazy_load(self) -> Iterator[Document]:
        yield from self._process_standings()

    async def alazy_load(self) -> AsyncIterator[Document]:
        for doc in self._process_standings():
            yield doc
