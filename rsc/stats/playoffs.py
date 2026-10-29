"""Where each team stands in its playoff group, worked out from the API's playoff hunt.

The API ranks each group, draws the cut line (`cutline_rank`), says who qualifies and how
(`playoff_qualifier_reason`), how far an outside team trails the last team in (`playoff_delta_label`)
and how many more wins guarantee a spot (`playoff_magic_number`, 0 once clinched). It has no
"eliminated" flag, and a `playoff_magic_number` of None only means a spot can't be guaranteed yet,
so elimination is worked out here, in `is_eliminated`.
"""

from collections.abc import Sequence
from dataclasses import dataclass
from enum import StrEnum

from rscapi.models.playoff_group import PlayoffGroup
from rscapi.models.playoff_qualifier_reason_enum import PlayoffQualifierReasonEnum
from rscapi.models.playoff_team import PlayoffTeam
from rscapi.models.tier_playoff_hunt import TierPlayoffHunt


# How many wins behind the team it's chasing a team can be and still be on the bubble
BUBBLE_WINS = 2


class RaceStatus(StrEnum):
    # In, whatever happens: the magic number is 0, or the regular season is over
    CLINCHED = "clinched"
    # In a spot today, not safe yet
    IN = "in"
    # The last team in and the teams chasing it, a win or less apart
    BUBBLE = "bubble"
    # Outside, more than a win back, still alive
    OUT = "out"
    # Can't reach a spot even by winning every game left, or the regular season is over
    ELIMINATED = "eliminated"


def is_eliminated(team: PlayoffTeam, group: PlayoffGroup) -> bool:
    """True when `team` can't reach a playoff spot, even by winning every game it has left.

    A team is out once its `max_possible_games_won` is below the current wins of the last team in a
    playoff spot, the team at `cutline_rank`: everyone above the line then finishes above it. (The
    fewest wins above the line, in case the teams have played different numbers of games.)

    A division tier also lets a team in by winning its division, so there it's only out once it
    can't catch its division leader either. Every wildcard sits above the line, so a team that
    can't win its division can't get past them. Level wins leave a team alive: a tiebreaker could
    still go its way.
    """
    if team.playoff_qualified or group.cutline_rank <= 0:
        return False
    above = [t.games_won for t in group.teams if t.playoff_rank <= group.cutline_rank]
    if not above or team.max_possible_games_won >= min(above):
        return False
    if _has_division(team, group):
        leader_wins = max((t.games_won for t in group.teams if t.division == team.division and t.team_id != team.team_id), default=0)
        if team.max_possible_games_won >= leader_wins:
            return False
    return True


def _has_division(team: PlayoffTeam, group: PlayoffGroup) -> bool:
    return any(d.division == team.division for d in group.divisions)


def _measured_against(team: PlayoffTeam, group: PlayoffGroup) -> PlayoffTeam | None:
    """The qualifier an outside team chases, as the API picks it for `playoff_delta_label`.

    The team at the cutoff, or in a division tier the last wildcard. A division tier with no
    wildcards has each outside team chasing its own division leader.
    """
    if not group.divisions:
        return next((t for t in group.teams if t.playoff_rank == group.cutoff), None)
    wildcards = [t for t in group.teams if t.playoff_qualifier_reason == PlayoffQualifierReasonEnum.WILDCARD]
    if wildcards:
        return wildcards[-1]
    return next(
        (t for t in group.teams if t.playoff_qualifier_reason == PlayoffQualifierReasonEnum.DIVISION and t.division == team.division),
        None,
    )


def _close_behind(team: PlayoffTeam, target: PlayoffTeam) -> bool:
    """Level on the tiebreaker or a random draw, or up to BUBBLE_WINS back."""
    delta = team.playoff_delta_label
    return delta == "Tiebreaker" or delta.startswith("Random draw") or target.games_won - team.games_won <= BUBBLE_WINS


def race_statuses(group: PlayoffGroup, *, complete: bool = False) -> dict[int, RaceStatus]:
    """Each team's status by team ID. Once the regular season is `complete`, everyone is in or out for good."""
    statuses: dict[int, RaceStatus] = {}
    if complete:
        for team in group.teams:
            statuses[team.team_id] = RaceStatus.CLINCHED if team.playoff_qualified else RaceStatus.ELIMINATED
        return statuses

    # The qualifiers with a team close behind them, so they're on the bubble too
    threatened: set[int] = set()
    for team in group.teams:
        if team.playoff_qualified:
            continue
        if is_eliminated(team, group):
            statuses[team.team_id] = RaceStatus.ELIMINATED
            continue
        target = _measured_against(team, group)
        if target is not None and _close_behind(team, target):
            statuses[team.team_id] = RaceStatus.BUBBLE
            threatened.add(target.team_id)
        else:
            statuses[team.team_id] = RaceStatus.OUT

    for team in group.teams:
        if not team.playoff_qualified:
            continue
        if team.playoff_magic_number == 0:
            statuses[team.team_id] = RaceStatus.CLINCHED
        elif team.team_id in threatened:
            statuses[team.team_id] = RaceStatus.BUBBLE
        else:
            statuses[team.team_id] = RaceStatus.IN
    return statuses


@dataclass(frozen=True)
class RaceTeam:
    team: PlayoffTeam
    status: RaceStatus

    @property
    def rank(self) -> int:
        return self.team.playoff_rank

    @property
    def name(self) -> str:
        return self.team.team_name

    @property
    def record(self) -> str:
        return f"{self.team.games_won}-{self.team.games_lost}"

    @property
    def qualified(self) -> bool:
        return self.team.playoff_qualified


@dataclass(frozen=True)
class Race:
    """One playoff group's teams in standings order, each with its status."""

    label: str
    cutoff: int
    # The line sits under this rank; 0 when there's no line
    cut: int
    # Division labels, in a division tier
    divisions: tuple[str, ...]
    teams: tuple[RaceTeam, ...]
    complete: bool

    @property
    def above(self) -> tuple[RaceTeam, ...]:
        """The teams above the cut line, or every team when there's no line."""
        if not self.cut:
            return self.teams
        return tuple(t for t in self.teams if t.rank <= self.cut)

    @property
    def below(self) -> tuple[RaceTeam, ...]:
        """The teams below the line still shown one per row: everyone but the eliminated run at the bottom."""
        if not self.cut:
            return ()
        folded = {t.team.team_id for t in self.folded}
        return tuple(t for t in self.teams if t.rank > self.cut and t.team.team_id not in folded)

    @property
    def folded(self) -> tuple[RaceTeam, ...]:
        """The eliminated teams at the bottom, folded into one line.

        Only the run at the very bottom: an eliminated team above a live one keeps its row, so the
        numbered rows never skip a rank.
        """
        if not self.cut:
            return ()
        run: list[RaceTeam] = []
        for team in reversed(self.teams):
            if team.rank <= self.cut or team.status is not RaceStatus.ELIMINATED:
                break
            run.append(team)
        return tuple(reversed(run))

    def with_status(self, *statuses: RaceStatus) -> list[RaceTeam]:
        return [t for t in self.teams if t.status in statuses]

    @property
    def remaining_games(self) -> tuple[int, int]:
        """The fewest and most games any team has left."""
        left = [t.team.remaining_games for t in self.teams]
        return min(left, default=0), max(left, default=0)


def build_races(hunt: TierPlayoffHunt) -> list[Race]:
    """One Race per playoff group that has teams."""
    races = []
    for group in hunt.groups:
        if not group.teams:
            continue
        statuses = race_statuses(group, complete=hunt.regular_season_complete)
        teams = sorted(group.teams, key=lambda t: t.playoff_rank)
        races.append(
            Race(
                label=group.label,
                cutoff=group.cutoff,
                # A line under the last team would have nobody below it
                cut=group.cutline_rank if group.cutline_rank < len(teams) else 0,
                divisions=tuple(d.label for d in group.divisions),
                teams=tuple(RaceTeam(t, statuses[t.team_id]) for t in teams),
                complete=hunt.regular_season_complete,
            )
        )
    return races


# Wording shared by the graphic and the text race board


def plural(count: int, word: str) -> str:
    return f"{count} {word}{'' if count == 1 else 's'}"


def names(items: Sequence[str]) -> str:
    """'A', 'A and B', 'A, B and C'."""
    if len(items) <= 1:
        return "".join(items)
    return f"{', '.join(items[:-1])} and {items[-1]}"


def route(team: RaceTeam) -> str:
    """How a qualifier holds its spot in a division tier: 'Leads Mountain', 'Won Mountain' or 'Wildcard'."""
    match team.team.playoff_qualifier_reason:
        case PlayoffQualifierReasonEnum.DIVISION:
            # The API says "Division winner" once nobody can catch the leader
            won = team.team.playoff_delta_label == "Division winner"
            return f"{'Won' if won else 'Leads'} {team.team.division_label}"
        case PlayoffQualifierReasonEnum.WILDCARD:
            return "Wildcard"
        case _:
            return ""


def to_clinch(team: RaceTeam) -> str:
    """'Clinched', '2 to clinch', or '' when the spot can't be guaranteed yet."""
    if team.status is RaceStatus.CLINCHED:
        return "Clinched"
    magic = team.team.playoff_magic_number
    return f"{magic} to clinch" if magic else ""


def chase(team: RaceTeam) -> str:
    """How far an outside team trails: '2 back', 'Tiebreaker', 'Random draw' or 'Eliminated'."""
    if team.status is RaceStatus.ELIMINATED:
        return "Eliminated"
    delta = team.team.playoff_delta_label
    if delta.endswith(" back"):
        return delta.replace(" wins back", " back").replace(" win back", " back")
    if delta == "Outside cut":
        return "Outside"
    return delta


def games_left(race: Race) -> str:
    """'4 games left', 'Up to 4 games left' or 'Regular season complete'."""
    fewest, most = race.remaining_games
    if race.complete or most == 0:
        return "Regular season complete"
    if fewest == most:
        return f"{plural(most, 'game')} left"
    return f"Up to {plural(most, 'game')} left"


def spots(race: Race) -> str:
    """'2 division winners + 2 wildcards', or 'Top 8 make it'."""
    if race.cutoff <= 0:
        return "No playoff spots"
    if race.divisions:
        winners = len(race.divisions)
        wildcards = race.cutoff - winners
        text = plural(winners, "division winner")
        return f"{text} + {plural(wildcards, 'wildcard')}" if wildcards > 0 else text
    return f"Top {race.cutoff} make it"
