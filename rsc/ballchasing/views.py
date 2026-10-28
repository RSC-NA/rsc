"""The match result card posted after a match is reported (Components V2)."""

from collections.abc import Sequence
from dataclasses import dataclass
from pathlib import Path

import discord
from discord import ui
from rscapi.models.match import Match
from rscapi.models.match_results import MatchResults

from rsc.enums import MatchType, PostSeasonType

# Shown when there's no winning franchise logo (e.g. a tied series) and no server icon
FALLBACK_LOGO = Path(__file__).parent.parent / "resources" / "rsc_logo.png"

_PLAYOFF_ROUNDS = {
    PostSeasonType.PLAYOFF: "Playoffs",
    PostSeasonType.WILDCARD: "Wildcard",
    PostSeasonType.QUARTERFINALS: "Quarterfinals",
    PostSeasonType.SEMIFINALS: "Semifinals",
    PostSeasonType.FINALS: "Finals",
}


def match_label(match: Match) -> str:
    """'Match Day 7', 'Preseason 2', or the playoff round."""
    day = match.day or 0
    match match.match_type:
        case MatchType.PRESEASON:
            return f"Preseason {day}"
        case MatchType.POSTSEASON:
            try:
                return _PLAYOFF_ROUNDS[PostSeasonType(day)]
            except ValueError:
                return "Playoffs"
        case MatchType.FINALS:
            return "Finals"
        case _:
            return f"Match Day {day}"


@dataclass(frozen=True)
class MatchResultCard:
    """Everything the card shows, gathered once so the channel post and the
    reporter's copy render the same thing."""

    match: Match
    result: MatchResults
    colour: discord.Colour
    # Winning franchise logo or server icon. None falls back to the bundled RSC logo.
    logo_url: str | None
    gm_mentions: Sequence[str]
    match_url: str | None
    ballchasing_url: str | None

    def render(self, *, replays: str | None = None) -> tuple[ui.LayoutView, list[discord.File]]:
        """The card, plus any file it references. A fresh File each call, since a send consumes it.

        `replays` adds the upload summary for the reporter's private copy.
        """
        home, away = self.match.home_team, self.match.away_team
        home_wins, away_wins = self.result.home_wins or 0, self.result.away_wins or 0
        label = " · ".join(filter(None, [home.tier, match_label(self.match), "Final"]))
        # No-break spaces around the dash, and a word joiner after it, keep the score on one line on phones
        score = f"{home_wins}\N{NO-BREAK SPACE}\N{EN DASH}\N{WORD JOINER}\N{NO-BREAK SPACE}{away_wins}"
        headline = f"## {discord.utils.escape_markdown(home.name)} {score} {discord.utils.escape_markdown(away.name)}"

        files: list[discord.File] = []
        if self.logo_url:
            thumbnail = ui.Thumbnail(self.logo_url)
        else:
            logo = discord.File(FALLBACK_LOGO, filename=FALLBACK_LOGO.name)
            files.append(logo)
            thumbnail = ui.Thumbnail(logo)

        # The label and the score are separate TextDisplays: a heading after other text in the same
        # TextDisplay gets extra space above it, which pushed the score away from its label
        section = ui.Section(ui.TextDisplay(f"-# {label}"), ui.TextDisplay(headline), accessory=thumbnail)
        if self.gm_mentions:
            # Its own line, and a TextDisplay: mentions here ping, embed mentions never do
            section.add_item(ui.TextDisplay(f"GMs {' · '.join(self.gm_mentions)}"))

        container = ui.Container(section, accent_colour=self.colour)

        # Link buttons only, so there's nothing for the view to listen for
        links = ui.ActionRow()
        if self.match_url:
            links.add_item(ui.Button(label="Match page", url=self.match_url))
        if self.ballchasing_url:
            links.add_item(ui.Button(label="Ballchasing", url=self.ballchasing_url))
        if links.children:
            # A thin line, so the buttons don't crowd the GMs line
            container.add_item(ui.Separator())
            container.add_item(links)

        if replays:
            container.add_item(ui.TextDisplay(f"-# Replays: {replays}"))

        view = ui.LayoutView(timeout=None)
        view.add_item(container)
        return view, files
