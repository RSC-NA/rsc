from dataclasses import dataclass

from rscapi.models.match import Match
from rscapi.models.match_team import MatchTeam

from rsc.enums import MatchType, PostSeasonType


def is_final(match: Match) -> bool:
    """Whether the match is a tier's final, whichever way the API marks it."""
    return match.match_type == MatchType.FINALS or (match.match_type == MatchType.POSTSEASON and match.day == PostSeasonType.FINALS)


def series_winner(match: Match, home_wins: int, away_wins: int) -> MatchTeam | None:
    """The team that has clinched the series at this score, decided as the API's `series_winner` does."""
    if not match.num_games:
        return None
    needed = match.num_games // 2 + 1
    if home_wins >= needed:
        return match.home_team
    if away_wins >= needed:
        return match.away_team
    return None


@dataclass(frozen=True)
class FinalWin:
    winner: MatchTeam
    runner_up: MatchTeam
    winner_wins: int
    runner_up_wins: int


def final_win(match: Match, home_wins: int, away_wins: int) -> FinalWin | None:
    """The championship this score decides, or None when the match isn't a final or nobody has clinched it."""
    if not is_final(match):
        return None
    winner = series_winner(match, home_wins, away_wins)
    if winner is None:
        return None
    if winner is match.home_team:
        return FinalWin(match.home_team, match.away_team, home_wins, away_wins)
    return FinalWin(match.away_team, match.home_team, away_wins, home_wins)
