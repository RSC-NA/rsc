"""The lobby card posted when a combine or Dev League match starts (Components V2).

One builder serves both, and the same card is DM'd to each player with a line
telling them their team and job. The card is a pydantic model so it can be kept
in Config and redrawn as Final when the match ends, after the voice channels and
lobby details stop mattering.
"""

from datetime import datetime
from enum import StrEnum

import discord
from discord import ui
from pydantic import BaseModel, ConfigDict


LIVE_COLOUR = discord.Colour.green()
FINAL_COLOUR = discord.Colour.dark_grey()


class LobbyKind(StrEnum):
    COMBINE = "combine"
    DEV_LEAGUE = "devleague"


class LobbyTeam(StrEnum):
    HOME = "Home"
    AWAY = "Away"


class LobbyScore(BaseModel):
    home_wins: int
    away_wins: int


class LobbyCard(BaseModel):
    model_config = ConfigDict(frozen=True)

    kind: LobbyKind
    lobby_id: int
    # Combine tier name, or a Dev League letter grade (S+ to F)
    tier: str
    lobby_name: str
    lobby_pass: str
    # Each player as a mention, or their escaped name when they aren't in the server
    home: tuple[str, ...]
    away: tuple[str, ...]
    # The first home player hosts the lobby; their escaped name
    lobby_maker: str | None
    home_vc_url: str | None
    away_vc_url: str | None
    match_url: str
    started_at: datetime

    @property
    def name(self) -> str:
        if self.kind is LobbyKind.DEV_LEAGUE:
            return f"Dev League {discord.utils.escape_markdown(self.tier)} Match {self.lobby_id}"
        return f"Combine {self.lobby_id}"

    def render(
        self,
        *,
        live_emoji: str = "",
        viewer: LobbyTeam | None = None,
        viewer_makes_lobby: bool = False,
        final: bool = False,
        score: LobbyScore | None = None,
    ) -> ui.LayoutView:
        """The live card, or the Final one once the match is over.

        `viewer` adds the DM's personal line. `live_emoji` is the animated dot's markup,
        and a missing emoji leaves plain "LIVE".
        """
        container = ui.Container(accent_colour=FINAL_COLOUR if final else LIVE_COLOUR)
        state = "Final" if final else " ".join(filter(None, [live_emoji, "LIVE"]))
        title = f"## {state} · {self.name}"
        if viewer:
            title += f"\n{self._viewer_line(viewer, viewer_makes_lobby, final=final)}"
        # Discord pins a Section's button to its first line, so the Section holds only the title and the
        # details below get the full width
        container.add_item(ui.Section(ui.TextDisplay(title), accessory=ui.Button(label="Match", url=self.match_url)))
        if final:
            if score:
                # No-break spaces keep the score on one line on phones
                result = f"{score.home_wins}\N{NO-BREAK SPACE}\N{EN DASH}\N{NO-BREAK SPACE}{score.away_wins}"
                container.add_item(ui.TextDisplay(f"### Home {result} Away"))
        else:
            container.add_item(ui.TextDisplay(f"**Lobby** `{_code(self.lobby_name)}`\n**Password** `{_code(self.lobby_pass)}`"))

        # A line above each team, so the two rosters read as separate blocks
        for team in (LobbyTeam.HOME, LobbyTeam.AWAY):
            container.add_item(ui.Separator())
            for item in self._team(team, final=final):
                container.add_item(item)

        if not final:
            footer = [f"-# Started {discord.utils.format_dt(self.started_at, 'R')}"]
            if self.kind is LobbyKind.COMBINE:
                footer.append("-# Lost these details? Run `/combines lobbyinfo`.")
            container.add_item(ui.TextDisplay("\n".join(footer)))

        view = ui.LayoutView(timeout=None)
        view.add_item(container)
        return view

    def _viewer_line(self, team: LobbyTeam, makes_lobby: bool, *, final: bool) -> str:
        if final:
            return f"You were on **{team}**"
        if makes_lobby:
            return f"You're on **{team}** · you make the lobby"
        if team is LobbyTeam.AWAY and self.kind is LobbyKind.COMBINE:
            return f"You're on **{team}** · your team uploads the replays"
        return f"You're on **{team}**"

    def _team(self, team: LobbyTeam, *, final: bool) -> list[ui.Item]:
        players, vc_url = (self.home, self.home_vc_url) if team is LobbyTeam.HOME else (self.away, self.away_vc_url)
        header = [f"**{team}**"]
        if not final:
            if team is LobbyTeam.HOME and self.lobby_maker:
                header.append(f"-# {self.lobby_maker} makes the lobby")
            elif team is LobbyTeam.AWAY and self.kind is LobbyKind.COMBINE:
                header.append("-# Uploads the replays")
        # One player per line. A TextDisplay, so these mentions ping.
        roster = ui.TextDisplay("\n".join(players) or "No players")

        if final or not vc_url:
            # The voice channels are gone once the match is over, so no Join button
            return [ui.TextDisplay("\n".join(header)), roster]
        # The Join button sits beside the team name (Discord pins it to the Section's first line), and the
        # roster runs full width below so long names don't wrap on phones.
        # Link buttons can only be grey, so the label alone tells Home from Away.
        button = ui.Button(label=f"Join {team} VC", url=vc_url)
        return [ui.Section(*(ui.TextDisplay(t) for t in header), accessory=button), roster]


def _code(text: str) -> str:
    """Text for an inline code span. Backticks would end the span early."""
    return text.replace("`", "'")
