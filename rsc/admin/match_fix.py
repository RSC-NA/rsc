"""What `/admin matches fix` shows: what a corrected result changes, and the cards that say so."""

from dataclasses import dataclass
from typing import Any, TypeAlias
from zoneinfo import ZoneInfo

import discord
from discord import ui
from rscapi.models.match import Match
from rscapi.models.match_team import MatchTeam
from rscapi.models.pending_series import PendingSeries

from rsc.ballchasing.views import match_label, round_label, score, scoreline
from rsc.const import DEFAULT_TIMEOUT
from rsc.enums import MatchType
from rsc.matches.series import is_final, series_winner
from rsc.views import AuthorOnlyLayoutView

Items: TypeAlias = list[ui.Item[Any]]


def _md(text: str) -> str:
    return discord.utils.escape_markdown(text)


def _possessive(name: str) -> str:
    return f"{_md(name)}'" if name.endswith("s") else f"{_md(name)}'s"


@dataclass(frozen=True)
class Fix:
    """A reported match, the result it was recorded with, and the result it is being changed to."""

    match: Match
    old: tuple[int, int]
    new: tuple[int, int]
    # The logo of the team ahead at the new score, or the server icon
    logo_url: str | None


@dataclass(frozen=True)
class Reseed:
    """A regular season result: standings, and so playoff seeds, follow it."""

    tier: str | None


@dataclass(frozen=True)
class NoSeriesWinner:
    pass


@dataclass(frozen=True)
class SameWinner:
    winner: MatchTeam


@dataclass(frozen=True)
class WonFinals:
    winner: MatchTeam


@dataclass(frozen=True)
class NewWinner:
    """A playoff series now won by a different team, who should take the old winner's place in the next round."""

    winner: MatchTeam
    # None when nobody had clinched the series at the recorded score
    old_winner: MatchTeam | None
    next_round: str


Change: TypeAlias = Reseed | NoSeriesWinner | SameWinner | WonFinals | NewWinner | None


def fix_change(fix: Fix) -> Change:
    """What correcting the result changes beyond the match itself. None for a preseason match."""
    match = fix.match
    match match.match_type:
        case MatchType.PRESEASON:
            return None
        case MatchType.POSTSEASON | MatchType.FINALS:
            old, new = series_winner(match, *fix.old), series_winner(match, *fix.new)
            if new is None:
                return NoSeriesWinner()
            if new == old:
                return SameWinner(new)
            if is_final(match):
                return WonFinals(new)
            return NewWinner(new, old, round_label((match.day or 0) + 1))
        case _:
            return Reseed(match.home_team.tier)


@dataclass(frozen=True)
class Takeover:
    """A new series winner, and the old winner's next-round match they take over.

    `next_match` is None when there is none yet (the opponent is still being decided) or it could not be looked up.
    """

    change: NewWinner
    next_match: Match | None


Preview: TypeAlias = Reseed | NoSeriesWinner | SameWinner | WonFinals | Takeover | None


@dataclass(frozen=True)
class Moved:
    next_match: Match


@dataclass(frozen=True)
class Waiting:
    winner: MatchTeam
    pending: PendingSeries


@dataclass(frozen=True)
class NotMoved:
    """The old winner already played the next round, so the API left it alone."""

    change: NewWinner


@dataclass(frozen=True)
class Unchecked:
    next_round: str
    reason: str


Outcome: TypeAlias = Reseed | NoSeriesWinner | SameWinner | WonFinals | Moved | Waiting | NotMoved | Unchecked | None


def _played(match: Match) -> bool:
    return bool(match.results and (match.results.home_wins or match.results.away_wins))


def _opponent(match: Match, team: MatchTeam) -> MatchTeam:
    return match.away_team if match.home_team.name == team.name else match.home_team


def consequence(preview: Preview) -> str | None:
    """The confirm card's line on what saving changes. None when there is nothing to say."""
    match preview:
        case Takeover(NewWinner(winner, None, rnd), _):
            return f"**{_md(winner.name)}** win the series and move on to the **{rnd}**."
        case Takeover(NewWinner(winner, old, rnd), None) if old:
            return f"**{_md(winner.name)}** win the series instead and take {_possessive(old.name)} place in the **{rnd}**."
        case Takeover(NewWinner(winner, old, rnd), nxt) if old and nxt and _played(nxt):
            new_name, old_name = _md(winner.name), _md(old.name)
            return (
                f"**{new_name}** win the series instead. {old_name} already played the {rnd},"
                f" so the API can't move {new_name} into it. Fix the {rnd} by hand."
            )
        case Takeover(NewWinner(winner, old, rnd), nxt) if old and nxt:
            return (
                f"**{_md(winner.name)}** win the series instead. They take {_possessive(old.name)} place in the **{rnd}**"
                f" against **{_md(_opponent(nxt, old).name)}**, unless the {rnd} have been played."
            )
        case WonFinals(winner):
            return f"**{_md(winner.name)}** win the Finals instead."
        case SameWinner(winner):
            return f"**{_md(winner.name)}** still win the series, so the bracket doesn't change."
        case NoSeriesWinner():
            return "No team has won the series at this score, so the next series stays as it was."
        case Reseed(tier):
            whose = f"{tier}'s" if tier else "this tier's"
            return (
                f"-# Standings update from this result. If {whose} playoffs are already seeded,"
                " the seeds can change and unplayed playoff matches move to follow."
            )
        case _:
            return None


def _headline(fix: Fix, suffix: str, *extra: str) -> Items:
    """The scoreboard at the top of every fix card: tier, round and the new score, beside the winner's logo."""
    label = " · ".join(filter(None, [fix.match.home_team.tier, match_label(fix.match), suffix]))
    texts = [ui.TextDisplay(f"-# {label}"), ui.TextDisplay(scoreline(fix.match, *fix.new)), *map(ui.TextDisplay, extra)]
    if not fix.logo_url:
        return texts
    return [ui.Section(*texts, accessory=ui.Thumbnail(fix.logo_url))]


def confirm_body(fix: Fix, preview: Preview) -> Items:
    """The confirm card above its buttons."""
    items = _headline(fix, "Fixing the result", f"Recorded as ~~{score(*fix.old)}~~")
    if text := consequence(preview):
        items += [ui.Separator(), ui.TextDisplay(text)]
    return items


def _next_series(outcome: Outcome) -> tuple[Items, discord.Colour]:
    """The result card's block on the next round, and the card's accent colour."""
    green, yellow = discord.Colour.green(), discord.Colour.yellow()
    match outcome:
        case Moved(nxt):
            when = f"\n<t:{int(nxt.var_date.timestamp())}:F>" if nxt.var_date else ""
            text = f"**{match_label(nxt)}** · {_md(nxt.home_team.name)} vs {_md(nxt.away_team.name)}{when}"
            return [ui.Separator(), ui.TextDisplay("### Next series"), ui.TextDisplay(text)], green
        case Waiting(winner, pending):
            feeder = pending.feeder_match
            text = (
                f"**{_md(winner.name)}** wait on the winner of **{_md(feeder.home_team.name)}**"
                f" vs **{_md(feeder.away_team.name)}** for the **{pending.round_label}**."
            )
            return [ui.Separator(), ui.TextDisplay("### Next series"), ui.TextDisplay(text)], green
        case NotMoved(NewWinner(_, old, rnd)):
            who = _md(old.name) if old else "Another team"
            text = f"{who} already played the {rnd}, so the API left it as it was. Fix the {rnd} by hand."
            return [ui.Separator(), ui.TextDisplay(f"### {rnd} not moved"), ui.TextDisplay(text)], yellow
        case Unchecked(rnd, reason):
            text = f"The score was saved, but the next round could not be checked: {reason}"
            return [ui.Separator(), ui.TextDisplay(f"### {rnd} not checked"), ui.TextDisplay(text)], yellow
        case NoSeriesWinner():
            return [ui.TextDisplay("-# No team has won the series at this score, so the next series stays as it was.")], green
        case Reseed():
            return [ui.TextDisplay("-# Standings and playoff seeds update from this result.")], green
        case _:
            return [], green


def result_view(fix: Fix, outcome: Outcome, match_url: str | None) -> ui.LayoutView:
    """The card that replaces the confirm once the corrected result is saved."""
    block, colour = _next_series(outcome)
    container = ui.Container(*_headline(fix, "Corrected"), *block, accent_colour=colour)
    if match_url:
        container.add_item(ui.Separator())
        container.add_item(ui.ActionRow(ui.Button(label="Match page", url=match_url)))
    view = ui.LayoutView(timeout=None)
    view.add_item(container)
    return view


def state_view(title: str, text: str, colour: discord.Colour) -> ui.LayoutView:
    """A one-line card for a fix that stopped short: nothing to change, a bad score, or an API refusal."""
    view = ui.LayoutView(timeout=None)
    view.add_item(ui.Container(ui.TextDisplay(f"### {title}"), ui.TextDisplay(text), accent_colour=colour))
    return view


class _MeetingSelect(ui.Select["MeetingPickerView"]):
    def __init__(self, meetings: list[Match], tz: ZoneInfo):
        super().__init__(placeholder="Choose a match")
        newest_first = sorted(meetings, key=lambda m: m.var_date.timestamp() if m.var_date else 0, reverse=True)
        self.meetings = {str(m.id): m for m in newest_first[:25]}
        for value, m in self.meetings.items():
            h, a = (m.results.home_wins or 0, m.results.away_wins or 0) if m.results else (0, 0)
            parts = [f"{m.home_team.name} {h}\N{EN DASH}{a} {m.away_team.name}"]
            if m.var_date:
                day = m.var_date.astimezone(tz)
                parts.append(f"{day:%b} {day.day}")
            self.add_option(label=match_label(m)[:100], description=" · ".join(parts)[:100], value=value)

    async def callback(self, interaction: discord.Interaction):
        if self.view is None:
            return
        self.view.choice = self.meetings[self.values[0]]
        self.view.stop()
        await interaction.response.defer()


class MeetingPickerView(AuthorOnlyLayoutView):
    """Asks which of two teams' meetings `/admin matches fix` should correct. `choice` stays None on a timeout."""

    def __init__(
        self,
        interaction: discord.Interaction,
        meetings: list[Match],
        *,
        home: str,
        away: str,
        tz: ZoneInfo,
        timeout: float = DEFAULT_TIMEOUT,
    ):
        super().__init__(interaction=interaction, timeout=timeout)
        self.choice: Match | None = None
        times = "twice" if len(meetings) == 2 else f"{len(meetings)} times"
        self.add_item(
            ui.Container(
                ui.TextDisplay("-# Fix a result"),
                ui.TextDisplay(f"## {_md(home)} vs {_md(away)}"),
                ui.TextDisplay(f"They met {times} this season. Pick the match to fix."),
                ui.ActionRow(_MeetingSelect(meetings, tz)),
                accent_colour=discord.Colour.orange(),
            )
        )
