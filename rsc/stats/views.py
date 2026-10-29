"""The /playoffs message (Components V2): the standings graphic, or the text race board."""

import io
from dataclasses import dataclass

import discord
from discord import ui

from rsc.stats.graphic import GRAPHIC_FORMAT
from rsc.stats.playoffs import Race, RaceTeam, chase, games_left, route, spots, to_clinch

NBSP = "\N{NO-BREAK SPACE}"
WJ = "\N{WORD JOINER}"

# Discord's limit for a media item's alt text
ALT_TEXT_MAX = 256


def keep_together(text: str) -> str:
    """No-break spaces, and a word joiner after each hyphen, so a phone never splits "8-10" or "2 to clinch"."""
    return text.replace(" ", NBSP).replace("-", f"-{WJ}")


def board_row(team: RaceTeam, *, divisions: bool) -> str:
    """One team on one line, numbered with its playoff rank: '5. **Kestrel** 10-8 · Tiebreaker'.

    The parts after the name are joined with no-break spaces, so a narrow screen wraps inside the
    team name and never starts a line with "·". The division only shows where it decides the spot.
    """
    parts = [team.record]
    if team.qualified:
        way_in = route(team) if divisions else ""
        parts += [way_in, to_clinch(team) or ("" if way_in else "Holding")]
    else:
        parts.append(chase(team))
    tail = f"{NBSP}·{NBSP}".join(keep_together(p) for p in parts if p)
    return f"{team.rank}. **{discord.utils.escape_markdown(team.name)}**{NBSP}{tail}"


def eliminated_line(teams: tuple[RaceTeam, ...]) -> str:
    entries = (f"{discord.utils.escape_markdown(t.name)}{NBSP}{keep_together(t.record)}" for t in teams)
    return f"-# Eliminated: {', '.join(entries)}"


def alt_text(race: Race, *, whole_tier: bool) -> str:
    """The graphic's alt text: who's above the cut line, who's below and who's out, within Discord's 256 characters."""
    title = "Standings" if whole_tier else f"{race.label} standings"
    out = race.folded

    def describe(records: bool) -> str:
        def team_list(teams: tuple[RaceTeam, ...]) -> str:
            return ", ".join(f"{t.name} {t.record}" if records else t.name for t in teams)

        parts = [f"{title}, {race.cutoff} playoff spots: {team_list(race.above)}."]
        if race.below:
            parts.append(f"Below the cut: {team_list(race.below)}.")
        if out:
            parts.append(f"Eliminated: {', '.join(t.name for t in out)}.")
        return " ".join(parts)

    text = describe(records=True)
    if len(text) > ALT_TEXT_MAX:
        text = describe(records=False)
    if len(text) > ALT_TEXT_MAX:
        text = text[: ALT_TEXT_MAX - 1].rstrip() + "…"
    return text


@dataclass(frozen=True)
class PlayoffRaceCard:
    """The /playoffs message for one tier: the standings graphic, or with no `graphics`, the text race board."""

    tier: str
    season: int
    colour: discord.Colour
    races: tuple[Race, ...]
    # One playoff group for the whole tier, rather than one per conference
    whole_tier: bool
    # The website's standings page for the tier and season
    standings_url: str | None = None
    # One encoded image per race, in order. Empty for the text race board.
    graphics: tuple[bytes, ...] = ()

    @property
    def complete(self) -> bool:
        return any(race.complete for race in self.races)

    def render(self) -> tuple[ui.LayoutView, list[discord.File]]:
        """The message and the files it references. Fresh Files each call, since a send consumes them."""
        view = ui.LayoutView(timeout=None)
        files: list[discord.File] = []
        if self.graphics:
            for container in self._graphic_containers(files):
                view.add_item(container)
        else:
            for container in self._board_containers():
                view.add_item(container)
        return view, files

    def _stage(self) -> str:
        return "FINAL STANDINGS" if self.complete else "PLAYOFF RACE"

    def _spots_line(self, race: Race) -> str:
        return f"-# {spots(race)} · {games_left(race)}"

    def _links(self) -> ui.ActionRow | None:
        if not self.standings_url:
            return None
        # A link button is always grey
        return ui.ActionRow(ui.Button(label="Full standings", url=self.standings_url))

    # The standings graphic

    def _graphic_containers(self, files: list[discord.File]) -> list[ui.Container]:
        """A card per playoff group: one for a whole tier, one per conference otherwise, all in the same message."""
        pairs = list(zip(self.races, self.graphics, strict=True))
        cards = []
        for index, (race, image) in enumerate(pairs):
            heading = f"## {self.tier}" if self.whole_tier else f"## {self.tier} · {race.label}"
            cards.append(self._graphic_card(race, image, files, heading=heading, links=index == len(pairs) - 1))
        return cards

    def _graphic_card(self, race: Race, image: bytes, files: list[discord.File], *, heading: str, links: bool) -> ui.Container:
        container = ui.Container(accent_colour=self.colour)
        container.add_item(ui.TextDisplay(f"-# SEASON {self.season} · {self._stage()}"))
        container.add_item(ui.TextDisplay(f"{heading}\n{self._spots_line(race)}"))

        file = discord.File(io.BytesIO(image), filename=f"playoffs-{len(files) + 1}.{GRAPHIC_FORMAT}")
        files.append(file)
        container.add_item(ui.MediaGallery(discord.MediaGalleryItem(file, description=alt_text(race, whole_tier=self.whole_tier))))

        # The graphic already shows who's clinched, on the bubble or out, and screen readers get its alt text.
        # The standings link closes the message, under the last card.
        row = self._links() if links else None
        if row:
            container.add_item(row)
        return container

    # The text race board

    def _board_containers(self) -> list[ui.Container]:
        containers = []
        for index, race in enumerate(self.races):
            container = ui.Container(accent_colour=self.colour)
            if index == 0:
                container.add_item(ui.TextDisplay(f"-# SEASON {self.season} · {self.tier.upper()} · {self._stage()}"))
            title = f"## {self.tier} playoff race" if self.whole_tier else f"## {race.label}"
            container.add_item(ui.TextDisplay(f"{title}\n{self._spots_line(race)}"))
            container.add_item(ui.Separator(visible=False))

            divisions = bool(race.divisions)
            heading = f"-# {'QUALIFIED' if race.complete else 'IN'} · SEEDS 1 TO {len(race.above)}"
            if race.cutoff <= 0:
                heading = "-# STANDINGS"
            container.add_item(ui.TextDisplay("\n".join([heading, *(board_row(t, divisions=divisions) for t in race.above)])))

            if race.cut:
                # The visible line is the cut line
                container.add_item(ui.Separator())
                if race.below:
                    rows = [board_row(t, divisions=divisions) for t in race.below]
                    container.add_item(ui.TextDisplay("\n".join(["-# BELOW THE CUT", *rows])))
                if race.folded:
                    # Its own TextDisplay, so it can't run on as part of the numbered list above it
                    container.add_item(ui.TextDisplay(eliminated_line(race.folded)))
            containers.append(container)

        links = self._links()
        if links and containers:
            containers[-1].add_item(ui.Separator())
            containers[-1].add_item(links)
        return containers
