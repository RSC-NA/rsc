from dataclasses import dataclass
from datetime import datetime

import discord
from discord import ui


def _count(n: int, noun: str) -> str:
    return f"{n} {noun}" if n == 1 else f"{n} {noun}s"


def _joined(items: tuple[str, ...]) -> str:
    """'a', 'a and b', 'a, b and c'"""
    if len(items) < 2:
        return "".join(items)
    return ", ".join(items[:-1]) + " and " + items[-1]


@dataclass(frozen=True)
class TierRow:
    name: str
    # The guild role found by name. Without one the row shows the bold name.
    role_id: int | None = None
    mmr_min: int | None = None
    mmr_max: int | None = None
    teams: int | None = None
    team_cap: int | None = None

    def text(self) -> str:
        title = f"<@&{self.role_id}>" if self.role_id is not None else f"**{discord.utils.escape_markdown(self.name)}**"
        parts = []
        if self.mmr_min is not None and self.mmr_max is not None:
            parts.append(f"{self.mmr_min}\N{EN DASH}{self.mmr_max} MMR")
        if self.teams is not None:
            parts.append(_count(self.teams, "team"))
        if self.team_cap is not None:
            parts.append(f"{self.team_cap} team cap")
        return f"{title}\n-# {' · '.join(parts)}" if parts else title


@dataclass(frozen=True)
class TiersCard:
    """The `/tiers` card. Sent with `AllowedMentions.none()`: its role mentions must never ping a tier."""

    # "<league> · Season <n>", or the guild name when there is no season
    heading: str
    # Highest tier first
    rows: tuple[TierRow, ...]
    icon_url: str | None = None
    match_nights: tuple[str, ...] = ()
    # Timezone-aware, shown as a Discord timestamp in each viewer's own time
    match_time: datetime | None = None

    def render(self) -> ui.LayoutView:
        container = ui.Container(accent_colour=discord.Colour.blue())
        for item in self._header():
            container.add_item(item)
        # An empty TextDisplay is rejected by Discord
        if self.rows:
            container.add_item(ui.Separator())
            container.add_item(ui.TextDisplay("\n".join(r.text() for r in self.rows)))
        if self.match_nights:
            at = f" at {discord.utils.format_dt(self.match_time, 't')}" if self.match_time else ""
            container.add_item(ui.Separator())
            container.add_item(ui.TextDisplay(f"-# Match nights {_joined(self.match_nights)}{at}"))
        view = ui.LayoutView(timeout=None)
        view.add_item(container)
        return view

    def _header(self) -> list[ui.Item]:
        summary = _count(len(self.rows), "tier")
        team_counts = [r.teams for r in self.rows if r.teams is not None]
        if team_counts:
            summary += f" · {_count(sum(team_counts), 'team')}"
        texts = (
            ui.TextDisplay(f"-# {discord.utils.escape_markdown(self.heading)}"),
            ui.TextDisplay("## Tiers"),
            ui.TextDisplay(summary),
        )
        if self.icon_url:
            return [ui.Section(*texts, accessory=ui.Thumbnail(self.icon_url))]
        return list(texts)
