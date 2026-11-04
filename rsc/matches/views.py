"""The `/match` card and the pending-opponent card (Components V2)."""

import re
from dataclasses import dataclass
from datetime import datetime
from typing import Any, Literal

import discord
from discord import ui
from rscapi.models.team_player import TeamPlayer

from rsc.ballchasing.views import FALLBACK_LOGO
from rsc.enums import MatchFormat, MatchTeamEnum, Status, SubStatus
from rsc.views import ready_cog

NO_UPCOMING_MATCH = "You do not have any upcoming matches."

_SUB_TAGS = {SubStatus.OUT: "(Subbed Out)", SubStatus.IN: "(Subbed In)"}
_BACKTICK_RUN = re.compile(r"`{2,}")


def player_line(name: str, player: TeamPlayer, *, is_gm: bool) -> str | None:
    """A roster line, `name (C) (Sub) (GM)`, or None for a status that doesn't belong on a match roster."""
    tags: list[str] = []
    if player.captain:
        tags.append("(C)")
    match player.status:
        case Status.FREE_AGENT | Status.PERM_FA:
            tags.append(_SUB_TAGS.get(SubStatus(player.sub_status or 0), "(Sub)"))
        case Status.IR:
            tags.append("(IR)")
        case Status.AGMIR:
            tags.append("(AGM IR)")
        case Status.ROSTERED | Status.RENEWED:
            pass
        case _:
            return None
    if is_gm:
        tags.append("(GM)")
    return " ".join([name, *tags])


def series_label(match_format: str | None, num_games: int | None) -> str | None:
    """'4-game series' or 'Best of 5'."""
    if not match_format:
        return None
    if match_format == MatchFormat.GAME_SERIES:
        return f"{num_games}-game series" if num_games else "Game series"
    return f"Best of {num_games or match_format.removeprefix('BO')}"


def _timestamps(when: datetime) -> str:
    epoch = int(when.timestamp())
    return f"<t:{epoch}:F> · <t:{epoch}:R>"


def _inline_code(value: str) -> str:
    # A value holding a backtick needs the double-backtick form, or it would end the span early
    return f"`` {value} ``" if "`" in value else f"`{value}`"


def _code_block(lines: tuple[str, ...]) -> str:
    # Names go in raw, since escaping shows as backslashes in a code block. A zero-width space
    # between backticks keeps a name from closing the block early.
    body = "\n".join(_BACKTICK_RUN.sub(lambda run: "\N{ZERO WIDTH SPACE}".join(run[0]), line) for line in lines)
    return f"```\n{body}\n```"


def _logos(*urls: str | None) -> tuple[list[ui.Thumbnail], list[discord.File]]:
    """A thumbnail per logo URL. A missing logo shows the bundled RSC logo, attached once however many need it."""
    files: list[discord.File] = []
    thumbnails: list[ui.Thumbnail] = []
    for url in urls:
        if url:
            thumbnails.append(ui.Thumbnail(url))
            continue
        if not files:
            files.append(discord.File(FALLBACK_LOGO, filename=FALLBACK_LOGO.name))
        thumbnails.append(ui.Thumbnail(files[0]))
    return thumbnails, files


@dataclass(frozen=True)
class TeamBlock:
    name: str
    franchise: str | None
    # A mention, or the GM's escaped name when they aren't in the server
    gm: str | None
    # Franchise logo or server icon. None falls back to the bundled RSC logo.
    logo_url: str | None
    # Formatted by `player_line`, unescaped: they go in a code block
    players: tuple[str, ...]


@dataclass(frozen=True)
class Contact:
    """Who the viewer's team talks to on the other side."""

    mention: str
    role: Literal["captain", "GM"]


@dataclass(frozen=True)
class MatchCard:
    """The `/match` reply. Sent with `AllowedMentions.none()`: it names players but pings no one."""

    tier: str | None
    label: str
    series: str | None
    starts: datetime | None
    lobby_name: str | None
    lobby_pass: str | None
    home: TeamBlock
    away: TeamBlock
    # The viewer's side, or None for staff outside the match: their teams list home first, with no check-in line
    side: MatchTeamEnum | None
    contact: Contact | None
    check_in_channel: str | None
    match_url: str | None
    # Playoffs only
    bracket_url: str | None
    reportmatch: str
    colour: discord.Colour

    def render(self) -> tuple[ui.LayoutView, list[discord.File]]:
        """The card, plus any file it references. A fresh File each call, since a send consumes it."""
        esc = discord.utils.escape_markdown
        sides = ((MatchTeamEnum.HOME, self.home), (MatchTeamEnum.AWAY, self.away))
        if self.side is MatchTeamEnum.AWAY:
            sides = sides[::-1]
        thumbnails, files = _logos(*(team.logo_url for _, team in sides))

        container = ui.Container(accent_colour=self.colour)
        container.add_item(ui.TextDisplay(f"-# {' · '.join(filter(None, [self.tier, self.label, self.series]))}"))
        container.add_item(ui.TextDisplay(f"## {esc(self.home.name)} vs {esc(self.away.name)}"))
        if self.starts:
            container.add_item(ui.TextDisplay(_timestamps(self.starts)))

        container.add_item(ui.Separator())
        container.add_item(ui.TextDisplay(self._lobby()))
        if check_in := self._check_in():
            container.add_item(ui.TextDisplay(check_in))

        for (side, team), thumbnail in zip(sides, thumbnails, strict=True):
            container.add_item(ui.Separator())
            container.add_item(self._team_section(side, team, thumbnail))

        container.add_item(ui.Separator())
        container.add_item(
            ui.TextDisplay(
                f"-# Turn on crossplay. Save every replay and screenshot the scoreboard before you leave. Report with {self.reportmatch}."
            )
        )

        links = ui.ActionRow()
        if self.match_url:
            links.add_item(ui.Button(label="Match page", url=self.match_url))
        if self.bracket_url:
            links.add_item(ui.Button(label="Bracket", url=self.bracket_url))
        if links.children:
            container.add_item(links)

        view = ui.LayoutView(timeout=None)
        view.add_item(container)
        return view, files

    def _lobby(self) -> str:
        if not self.lobby_name:
            return "**Lobby** Not posted yet"
        lines = [f"**Lobby** {_inline_code(self.lobby_name)}"]
        if self.lobby_pass:
            lines.append(f"**Password** {_inline_code(self.lobby_pass)}")
        return "\n".join(lines)

    def _check_in(self) -> str | None:
        if self.side is None:
            return None
        opponent = discord.utils.escape_markdown((self.away if self.side is MatchTeamEnum.HOME else self.home).name)
        where = f" in {self.check_in_channel}" if self.check_in_channel else ""
        if self.side is MatchTeamEnum.HOME:
            target = f"{self.contact.mention}, the {opponent} {self.contact.role}," if self.contact else f"the {opponent} team"
            return f"You're **home**. Create the lobby, then ping {target}{where} when your team is ready."
        who = f"{self.contact.mention}, the {opponent} {self.contact.role}," if self.contact else f"The {opponent} team"
        return f"You're **away**. {who} pings you{where} when the lobby is up. Join once your whole team is ready."

    def _team_section(self, side: MatchTeamEnum, team: TeamBlock, thumbnail: ui.Thumbnail) -> ui.Section:
        esc = discord.utils.escape_markdown
        facts = [
            None if self.side is None else ("Your team" if side is self.side else "Opponent"),
            side.full_name.lower(),
            esc(team.franchise) if team.franchise else None,
            f"GM {team.gm}" if team.gm else None,
        ]
        roster = _code_block(team.players) if team.players else "No players listed"
        return ui.Section(
            ui.TextDisplay(f"### {esc(team.name)}"),
            ui.TextDisplay(f"-# {' · '.join(filter(None, facts))}"),
            ui.TextDisplay(roster),
            accessory=thumbnail,
        )


_PENDING_SIDE = {
    True: "You're **home** whichever team wins.",
    False: "You're **away** whichever team wins.",
    None: "The higher seed is home, so it depends on who wins.",
}


@dataclass(frozen=True)
class PendingSeriesCard:
    """A bye seed's next playoff series, while its opponent is the winner of a series not yet reported."""

    # What Refresh asks for again
    team_id: int
    asked: bool
    tier: str
    round_label: str
    series: str | None
    team: str
    opponents: tuple[str, ...]
    starts: datetime | None
    # The round name of the series deciding the opponent, e.g. "Wildcard"
    feeder_round: str | None
    feeder_starts: datetime | None
    # True or False when the side is fixed whoever wins, None when it depends on the winner's seed
    home: bool | None
    logo_url: str | None
    bracket_url: str | None
    colour: discord.Colour

    def render(self) -> tuple[ui.LayoutView, list[discord.File]]:
        esc = discord.utils.escape_markdown
        (thumbnail,), files = _logos(self.logo_url)
        winner_of = " / ".join(f"**{esc(name)}**" for name in self.opponents)
        container = ui.Container(
            ui.Section(
                ui.TextDisplay(f"-# {' · '.join(filter(None, [self.tier, self.round_label, self.series]))}"),
                ui.TextDisplay(f"## {esc(self.team)} vs TBD"),
                ui.TextDisplay(f"Winner of {winner_of}"),
                accessory=thumbnail,
            ),
            accent_colour=self.colour,
        )
        if self.starts:
            container.add_item(ui.TextDisplay(_timestamps(self.starts)))
        container.add_item(ui.Separator())

        feeder = " ".join(filter(None, [self.feeder_round, "series"]))
        if self.feeder_starts:
            feeder += f" (<t:{int(self.feeder_starts.timestamp())}:t>)"
        container.add_item(ui.TextDisplay(f"**Lobby** Posted once the {feeder} is reported."))
        container.add_item(ui.TextDisplay(_PENDING_SIDE[self.home]))

        buttons = ui.ActionRow()
        buttons.add_item(MatchRefreshButton(self.team_id, asked=self.asked))
        if self.bracket_url:
            buttons.add_item(ui.Button(label="Bracket", url=self.bracket_url))
        container.add_item(buttons)

        view = ui.LayoutView(timeout=None)
        view.add_item(container)
        return view, files


def no_match_view() -> ui.LayoutView:
    """What Refresh shows when the team turns out to have no upcoming match."""
    view = ui.LayoutView(timeout=None)
    view.add_item(ui.Container(ui.TextDisplay(NO_UPCOMING_MATCH), accent_colour=discord.Colour.blue()))
    return view


MATCH_REFRESH_TEMPLATE = r"match_refresh:(?P<team_id>\d+):(?P<asked>[01])"


class MatchRefreshButton(ui.DynamicItem[ui.Button], template=MATCH_REFRESH_TEMPLATE):
    """Refresh on the pending-opponent card: runs `/match` again and swaps the card in place.

    `asked` records whether `/match` named the team, since a named team's lobby is for franchise
    managers only. A DynamicItem, so it still answers after a restart.
    """

    def __init__(self, team_id: int, *, asked: bool):
        self.team_id = team_id
        self.asked = asked
        super().__init__(ui.Button(label="Refresh", style=discord.ButtonStyle.primary, custom_id=f"match_refresh:{team_id}:{int(asked)}"))

    @classmethod
    async def from_custom_id(
        cls,
        interaction: discord.Interaction,
        item: ui.Item[Any],
        match: re.Match[str],
        /,
    ) -> "MatchRefreshButton":
        return cls(int(match["team_id"]), asked=match["asked"] == "1")

    async def callback(self, interaction: discord.Interaction):
        # Acknowledge first. The API calls below can exceed the 3 second deadline.
        await interaction.response.defer()

        guild = interaction.guild
        member = interaction.user
        if not (guild and isinstance(member, discord.Member)):
            return
        cog = await ready_cog(interaction, guild)
        if not cog:
            return

        reply = await cog.match_reply(guild, member, self.team_id, asked=self.asked)
        if isinstance(reply, discord.Embed):
            # A Components V2 message can't turn back into an embed
            return await interaction.followup.send(embed=reply, ephemeral=True)

        view, files = reply.render() if reply else (no_match_view(), [])
        await interaction.edit_original_response(view=view, attachments=files, allowed_mentions=discord.AllowedMentions.none())
