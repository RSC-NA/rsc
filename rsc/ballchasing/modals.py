import logging
import math

import discord
from discord.ui import FileUpload, Label, TextDisplay, TextInput
from rscapi.models.match import Match

from rsc.ballchasing.views import match_label
from rsc.enums import MatchFormat

log = logging.getLogger("red.rsc.ballchasing.modals")

# Discord's limits for a modal title and a label
TITLE_MAX = 45
LABEL_MAX = 45
_GAMES_WON = " games won"

_BEST_OF = (MatchFormat.BEST_OF_THREE, MatchFormat.BEST_OF_FIVE, MatchFormat.BEST_OF_SEVEN)


def report_title(home: str, away: str) -> str:
    """'Report Quantum vs Voltage', or just the matchup cut to fit."""
    title = f"Report {home} vs {away}"
    return title if len(title) <= TITLE_MAX else f"{home} vs {away}"[:TITLE_MAX]


def is_best_of(match: Match) -> bool:
    return match.match_format in _BEST_OF


def score_error(home_wins: int, away_wins: int, match: Match) -> str | None:
    """Why the entered wins don't fit the series, or None when they do."""
    games = match.num_games
    if not games:
        return None
    total = home_wins + away_wins
    entered = f"You entered {home_wins}\N{EN DASH}{away_wins}, which is {total} game{'' if total == 1 else 's'}."
    if is_best_of(match):
        needed = math.ceil(games / 2)
        if needed <= total <= games:
            return None
        return f"{entered} This is a best of {games}, so the wins must add up to {needed}\N{EN DASH}{games}."
    if total == games:
        return None
    return f"{entered} This series has {games}, so the wins must add up to {games}."


class ReportMatchModal(discord.ui.Modal):
    def __init__(self, home_team: str, away_team: str, *args, match: Match | None = None, day: int | None = None, **kwargs):
        super().__init__(*args, title=report_title(home_team, away_team), **kwargs)
        self.home_team = home_team
        self.away_team = away_team
        # Found before the modal opened, so the copy can name the tier and format.
        # None when the lookup was slow, which leaves the teams-only copy.
        self.match = match
        self.day = day
        self.home_wins = 0
        self.away_wins = 0
        self.replays: list[discord.Attachment] = []
        # discord.py stops the modal after any clean on_submit, rejected or not,
        # so the caller needs this to tell a usable submission from a rejected one.
        self.valid = False
        self.add_components()

    def _summary(self) -> str:
        if not self.match:
            label = f"Match Day {self.day}" if self.day else None
            lines = [f"**{label}**" if label else None, "Enter each team's wins and attach one replay per game."]
        else:
            games = self.match.num_games
            fmt = (f"Best of {games}" if is_best_of(self.match) else f"{games}-game series") if games else None
            tier = f"**{discord.utils.escape_markdown(self.match.home_team.tier)}**" if self.match.home_team.tier else None
            header = " · ".join(filter(None, [tier, match_label(self.match), fmt]))
            if games and is_best_of(self.match):
                rule = f"First to {math.ceil(games / 2)} wins. Attach one replay per game."
            elif games:
                rule = f"Wins must add up to {games}. Attach one replay per game."
            else:
                rule = "Attach one replay per game."
            lines = [header, rule]
        lines.append("-# Something wrong? DM the ModMail bot.")
        return "\n".join(filter(None, lines))

    def _side(self, team: str, entered_as: str) -> str:
        """Which side `team` really is. Reporters sometimes swap them, and the scores are normalized later."""
        if not (self.match and self.match.home_team.name):
            return entered_as
        return "Home team" if team.casefold() == self.match.home_team.name.casefold() else "Away team"

    def add_components(self) -> None:
        self.add_item(TextDisplay(content=self._summary()))

        games = self.match.num_games if self.match else None
        placeholder = f"Number from 0 to {games}" if games else "Number of games won"
        team_max = LABEL_MAX - len(_GAMES_WON)
        self.home_score = Label(
            text=f"{self.home_team[:team_max]}{_GAMES_WON}",
            description=self._side(self.home_team, "Home team"),
            component=TextInput(style=discord.TextStyle.short, placeholder=placeholder, max_length=1, required=True),
        )
        self.away_score = Label(
            text=f"{self.away_team[:team_max]}{_GAMES_WON}",
            description=self._side(self.away_team, "Away team"),
            component=TextInput(style=discord.TextStyle.short, placeholder=placeholder, max_length=1, required=True),
        )
        self.add_item(self.home_score)
        self.add_item(self.away_score)

        if games and not (self.match and is_best_of(self.match)):
            upload_hint = f"All {games} .replay files from this series"
        else:
            upload_hint = "One .replay file per game played"
        self.upload_replays = Label(
            text="Replay files",
            description=upload_hint,
            component=FileUpload(required=True, min_values=1, max_values=10),
        )
        self.add_item(self.upload_replays)

    async def on_submit(self, interaction: discord.Interaction) -> None:
        if not (
            isinstance(self.home_score.component, TextInput)
            and isinstance(self.away_score.component, TextInput)
            and isinstance(self.upload_replays.component, FileUpload)
        ):
            await interaction.response.send_message(
                "An unknown error occurred while processing the scores. Please try again.", ephemeral=True
            )
            return

        # Parse score
        try:
            self.home_wins = int(self.home_score.component.value)
            self.away_wins = int(self.away_score.component.value)
        except ValueError:
            await interaction.response.send_message("Wins must be whole numbers, like 2.", ephemeral=True)
            return

        if self.home_wins < 0 or self.away_wins < 0:
            await interaction.response.send_message("Wins can't be negative.", ephemeral=True)
            return

        # Fetch replays
        self.replays = self.upload_replays.component.values
        self.valid = True

        await interaction.response.defer(ephemeral=True)
