from collections.abc import Callable, Iterable, Mapping
from dataclasses import dataclass, field
from enum import Enum

import discord
from discord import ui
from rscapi.models.league_player import LeaguePlayer

from rsc.enums import Status, SubStatus

# Every component counts toward this, nested ones included
MAX_COMPONENTS = 40


class RosterGroup(Enum):
    """A section of the roster card. The value is its label, and the card shows them in this order."""

    ACTIVE = "ACTIVE ROSTER"
    SUBBED_OUT = "SUBBED OUT"
    INACTIVE_RESERVE = "INACTIVE RESERVE"


def roster_group(player: LeaguePlayer) -> RosterGroup:
    if player.sub_status == SubStatus.OUT:
        return RosterGroup.SUBBED_OUT
    if player.status in (Status.IR, Status.AGMIR):
        return RosterGroup.INACTIVE_RESERVE
    return RosterGroup.ACTIVE


# In display order. Plain IR has no tag, because its group label already says it.
_TAGS: tuple[tuple[str, Callable[[LeaguePlayer, int | None], bool]], ...] = (
    ("GM", lambda p, gm_id: gm_id is not None and p.player.discord_id == gm_id),
    ("Captain", lambda p, _: bool(p.captain)),
    ("Sub", lambda p, _: p.sub_status == SubStatus.IN),
    ("AGM", lambda p, _: p.status == Status.AGMIR),
)
_LEADERS = frozenset({"GM", "Captain"})


def roster_tags(player: LeaguePlayer, gm_id: int | None) -> tuple[str, ...]:
    return tuple(tag for tag, applies in _TAGS if applies(player, gm_id))


@dataclass(frozen=True)
class RosterRow:
    name: str
    mmr: int | None = None
    tags: tuple[str, ...] = ()
    profile_url: str | None = None


def group_rows(rows: Iterable[tuple[RosterGroup, RosterRow]]) -> dict[RosterGroup, tuple[RosterRow, ...]]:
    """Rows by group, in the order given, except that the GM and captain lead their group."""
    grouped: dict[RosterGroup, list[RosterRow]] = {}
    for group, row in rows:
        grouped.setdefault(group, []).append(row)
    return {group: tuple(sorted(rows, key=lambda r: not _LEADERS.intersection(r.tags))) for group, rows in grouped.items()}


def _size(item: ui.Item) -> int:
    if isinstance(item, (ui.Container, ui.Section, ui.ActionRow)):
        return 1 + sum(1 for _ in item.walk_children())
    return 1


@dataclass(frozen=True)
class RosterCard:
    """The `/roster` card. Sent with `AllowedMentions.none()`."""

    team: str
    franchise: str
    tier: str
    colour: discord.Colour
    gm: str | None = None
    # Franchise logo, or the server icon
    logo_url: str | None = None
    groups: Mapping[RosterGroup, tuple[RosterRow, ...]] = field(default_factory=dict)
    team_url: str | None = None
    franchise_url: str | None = None

    def render(self) -> ui.LayoutView:
        header = self._header()
        foot = self._foot()
        # The container counts as one
        budget = MAX_COMPONENTS - 1 - sum(_size(i) for i in (*header, *foot))
        rows = [(group, row) for group in RosterGroup for row in self.groups.get(group, ())]
        body, shown = self._fit(rows, budget)
        if shown < len(rows):
            # The "more" line takes one component itself
            body, shown = self._fit(rows, budget - 1)
            where = " on the team page" if self.team_url else ""
            body.append(ui.TextDisplay(f"-# And {len(rows) - shown} more{where}"))

        container = ui.Container(accent_colour=self.colour)
        for item in (*header, *body, *foot):
            container.add_item(item)
        view = ui.LayoutView(timeout=None)
        view.add_item(container)
        return view

    def _header(self) -> list[ui.Item]:
        esc = discord.utils.escape_markdown
        texts = [ui.TextDisplay(f"-# {esc(self.tier)} · {esc(self.franchise)}"), ui.TextDisplay(f"## {esc(self.team)}")]
        if self.gm:
            texts.append(ui.TextDisplay(f"General Manager **{esc(self.gm)}**"))
        if self.logo_url:
            return [ui.Section(*texts, accessory=ui.Thumbnail(self.logo_url))]
        return list(texts)

    def _foot(self) -> list[ui.Item]:
        links = (("Team page", self.team_url), ("Franchise page", self.franchise_url))
        buttons = [ui.Button(label=label, url=url) for label, url in links if url]
        if not buttons:
            return []
        return [ui.Separator(), ui.ActionRow(*buttons)]

    def _row(self, row: RosterRow) -> ui.Section | ui.TextDisplay:
        mmr = [f"{row.mmr} MMR"] if row.mmr is not None else []
        small = " · ".join([*mmr, *row.tags])
        name = f"**{discord.utils.escape_markdown(row.name)}**"
        text = ui.TextDisplay(f"{name}\n-# {small}" if small else name)
        if row.profile_url:
            return ui.Section(text, accessory=ui.Button(label="Profile", url=row.profile_url))
        if self.team_url:
            # Greyed out to keep the rows lined up. A link button, because a non-link one has a custom_id,
            # which keeps the timeout-less view in discord.py's view store until restart.
            return ui.Section(text, accessory=ui.Button(label="Profile", url=self.team_url, disabled=True))
        return text

    def _fit(self, rows: list[tuple[RosterGroup, RosterRow]], budget: int) -> tuple[list[ui.Item], int]:
        """The longest run of rows, with their group labels, that fits in `budget` components."""
        body: list[ui.Item] = []
        used = 0
        shown = 0
        current: RosterGroup | None = None
        for group, row in rows:
            label: list[ui.Item] = [ui.Separator(), ui.TextDisplay(f"-# {group.value}")] if group is not current else []
            section = self._row(row)
            cost = sum(_size(i) for i in label) + _size(section)
            if used + cost > budget:
                break
            body.extend((*label, section))
            used += cost
            shown += 1
            current = group
        return body, shown
