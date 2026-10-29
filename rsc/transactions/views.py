"""Transaction modals, and the transaction and trade cards posted to the transactions channel (Components V2)."""

import logging
from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path

import discord
from discord import ui
from discord.ui import TextInput

log = logging.getLogger("red.rsc.transactions.views")


class TradeAnnouncementModal(discord.ui.Modal, title="Trade Announcement"):
    trade: TextInput = TextInput(
        label="Enter what GM receives",
        placeholder="GM receives...",
        style=discord.TextStyle.paragraph,
        required=True,
    )

    async def on_submit(self, interaction: discord.Interaction):
        await interaction.response.defer(ephemeral=True)
        if not self.trade.value:
            await interaction.followup.send(content="No trade data provided...", ephemeral=True)
            return
        self.stop()


@dataclass(frozen=True)
class TransactionCard:
    """One player's transaction: signed, released, re-signed, subbed, retired or moved on or off IR."""

    # The small label: "TEMPORARY CONTRACT · Elite"
    move: str
    # The player's name, already markdown-escaped
    name: str
    # "joins **Quantum** · Hex Systems", already markdown-escaped
    summary: str
    player_id: int
    colour: discord.Colour
    banner: Path
    created_at: datetime
    # The starter a substitute replaces
    player_out_id: int | None = None
    # When a temporary contract ends: the starter who comes back in for the departing sub (`player_id`)
    starter_back_id: int | None = None
    gm_id: int | None = None
    # Shown beside the text: a franchise logo or server icon URL, or a bundled image such as a free agent tier badge
    logo: str | Path | None = None

    def render(self) -> tuple[ui.LayoutView, list[discord.File]]:
        """The card and the files it references. Fresh Files each call, since a send consumes them."""
        # Built like the match result: label, then the name as the headline, then where they went.
        # Separate TextDisplays, since a heading after other text in one block gets extra space above it.
        texts = (ui.TextDisplay(f"-# {self.move}"), ui.TextDisplay(f"## {self.name}"), ui.TextDisplay(self.summary))
        files: list[discord.File] = []
        container = ui.Container(accent_colour=self.colour)
        if self.logo is None:
            for text in texts:
                container.add_item(text)
        else:
            if isinstance(self.logo, Path):
                logo = discord.File(self.logo, filename=self.logo.name)
                files.append(logo)
                thumbnail = ui.Thumbnail(logo)
            else:
                thumbnail = ui.Thumbnail(self.logo)
            container.add_item(ui.Section(*texts, accessory=thumbnail))

        gm = f"**GM** <@{self.gm_id}>" if self.gm_id else None
        if self.starter_back_id:
            people = [f"**Out** <@{self.player_id}> · **In** <@{self.starter_back_id}>", gm]
        elif self.player_out_id:
            people = [f"**In** <@{self.player_id}> · **Out** <@{self.player_out_id}>", gm]
        else:
            people = [" · ".join(filter(None, [f"**Player** <@{self.player_id}>", gm]))]
        container.add_item(ui.Separator())
        # A TextDisplay, so these mentions ping; embed mentions never do
        container.add_item(ui.TextDisplay("\n".join(filter(None, people))))

        # The banner image is padded so it fills ~70% of the card, close to the old embed's size
        banner = discord.File(self.banner, filename=self.banner.name)
        files.append(banner)
        container.add_item(ui.Separator(visible=False, spacing=discord.SeparatorSpacing.small))
        container.add_item(ui.MediaGallery(discord.MediaGalleryItem(banner)))
        # The Discord ID wording matches the old embed footer, so one search finds old and new posts
        container.add_item(ui.TextDisplay(f"-# Discord ID: {self.player_id} · {discord.utils.format_dt(self.created_at, 'f')}"))

        view = ui.LayoutView(timeout=None)
        view.add_item(container)
        return view, files


# Discord's limits for one Components V2 message: 40 components counting nested ones, and
# 4,000 characters of text. The text limit keeps some headroom.
TRADE_MAX_COMPONENTS = 40
TRADE_MAX_TEXT = 3900


def ordinal(number: int) -> str:
    """1st, 2nd, 3rd, 4th, 11th, 21st."""
    suffix = "th" if 10 <= number % 100 <= 20 else {1: "st", 2: "nd", 3: "rd"}.get(number % 10, "th")
    return f"{number}{suffix}"


@dataclass(frozen=True)
class TradePick:
    """One draft pick changing hands."""

    tier: str
    round: int | None
    # This season's pick number in the tier, when it has one
    number: int | None = None
    future: bool = False
    season: int | None = None
    # The original owner's prefix, when the pick was first someone other than the giver's
    via: str | None = None

    def describe(self) -> str:
        """`S25 1st Round Elite · via IRN`, or `2nd Round Elite, pick 14` for this season's picks."""
        round_name = f"{ordinal(self.round)} Round" if self.round is not None else "Unknown Round"
        if self.future:
            # The API sends no season (or 0) for some future picks; the "Future Pick" label still says what it is
            text = f"S{self.season} {round_name} {self.tier}" if self.season else f"{round_name} {self.tier}"
        elif self.number is None:
            text = f"{round_name} {self.tier}"
        else:
            text = f"{round_name} {self.tier}, pick {self.number}"
        return f"{text} · via {self.via}" if self.via else text


@dataclass(frozen=True)
class TradePlayer:
    """One player changing franchises."""

    # `<@id>`, so the player is pinged, or their escaped name when they have no Discord ID
    mention: str
    # The team they join, already markdown-escaped
    team: str | None = None

    def describe(self) -> str:
        return f"{self.mention} → {self.team}" if self.team else self.mention


@dataclass(frozen=True)
class TradeGiver:
    """Everything one receiving franchise gets from one other franchise."""

    # Already markdown-escaped. None when the API doesn't say where the assets came from.
    name: str | None
    players: tuple[TradePlayer, ...] = ()
    picks: tuple[TradePick, ...] = ()
    # Set only when the giver receives nothing, so it has no card of its own: its GM is pinged by the "From" label
    gm_id: int | None = None


@dataclass(frozen=True)
class TradeReceiver:
    """One franchise's card: what it receives, split by the franchise giving it."""

    # Already markdown-escaped
    name: str
    colour: discord.Colour
    givers: tuple[TradeGiver, ...]
    gm_id: int | None = None
    # Franchise logo URL, shown beside the name
    logo: str | None = None


@dataclass(frozen=True)
class _Line:
    text: str
    # How many picks the line lists. Player lines are 0 and never cut, since they carry pings.
    picks: int = 0


@dataclass
class _Group:
    """One giver's block in a card, as it will render."""

    label: str | None
    lines: list[_Line]
    cut: int = 0
    gm_id: int | None = None

    def heading(self) -> str | None:
        if not self.label:
            return None
        return f"-# From {self.label} · **GM** <@{self.gm_id}>" if self.gm_id else f"-# From {self.label}"

    def content(self) -> str:
        parts = [line.text for line in self.lines]
        if self.cut:
            parts.append(f"…and {self.cut} more pick{'' if self.cut == 1 else 's'}")
        return "\n".join(parts)

    def text(self) -> str:
        return "\n".join(filter(None, [self.heading(), self.content()]))


@dataclass(frozen=True)
class _Body:
    """One block under a thin line: its heading, a little space, then the players and picks."""

    heading: str | None
    content: str


@dataclass
class _Card:
    """One receiver's container, with the overflow choices made for it."""

    receiver: TradeReceiver
    groups: list[_Group]
    logo: bool
    # Each giver in its own blocks under a thin line, or all of them in one TextDisplay
    split: bool = True
    # Each heading in its own TextDisplay with a little space under it, or at the top of its block
    spaced: bool = True

    def header(self) -> list[str]:
        # The name on top, then the GM. Separate TextDisplays beside a logo, since a heading after
        # other text in one block gets extra space above it; one block starting with the heading otherwise.
        lines = [f"### {self.receiver.name}"]
        if self.receiver.gm_id:
            lines.append(f"**GM** <@{self.receiver.gm_id}>")
        return lines

    def bodies(self) -> list[_Body]:
        if self.split:
            bodies = [_Body(group.heading(), group.content()) for group in self.groups]
        else:
            bodies = [_Body(None, "\n".join(group.text() for group in self.groups))]
        # "RECEIVES" heads what the franchise gets, under the line, so it isn't read as the GM's label
        if bodies:
            first = bodies[0]
            bodies[0] = _Body("\n".join(filter(None, ["-# RECEIVES", first.heading])), first.content)
        if not self.spaced:
            bodies = [_Body(None, "\n".join(filter(None, [body.heading, body.content]))) for body in bodies]
        return bodies

    def texts(self) -> list[str]:
        header = self.header() if self.logo else ["\n".join(self.header())]
        return header + [text for body in self.bodies() for text in (body.heading, body.content) if text]

    def components(self) -> int:
        # Container, then a Section (its TextDisplays and Thumbnail) or one TextDisplay, then per body a
        # Separator and TextDisplay, plus a heading TextDisplay and invisible Separator when it has a heading
        header = 2 + len(self.header()) if self.logo else 1
        return 1 + header + sum(4 if body.heading else 2 for body in self.bodies())

    def container(self) -> ui.Container:
        container = ui.Container(accent_colour=self.receiver.colour)
        if self.logo and self.receiver.logo:
            # The logo sits beside the name and GM, pinned to the top of the Section
            thumbnail = ui.Thumbnail(self.receiver.logo, description=f"{self.receiver.name} logo")
            container.add_item(ui.Section(*(ui.TextDisplay(text) for text in self.header()), accessory=thumbnail))
        else:
            container.add_item(ui.TextDisplay("\n".join(self.header())))
        for body in self.bodies():
            # A thin line under the header, and between givers when a franchise receives from more than one
            container.add_item(ui.Separator())
            if body.heading:
                # A little space between the heading and what's traded
                container.add_item(ui.TextDisplay(body.heading))
                container.add_item(ui.Separator(visible=False, spacing=discord.SeparatorSpacing.small))
            # A TextDisplay, so the player mentions ping; embed mentions never do
            container.add_item(ui.TextDisplay(body.content))
        return container


def _tier_rank(tier: str, tier_order: tuple[str, ...]) -> int:
    return tier_order.index(tier) if tier in tier_order else len(tier_order)


def _giver_lines(giver: TradeGiver, tier_order: tuple[str, ...]) -> list[_Line]:
    """Players, then this season's picks, then future picks, a line each.

    Future picks run from the latest season down. Then picks run from the highest tier down,
    then by round and pick number.
    """
    lines = [_Line(f"- **Player** {player.describe()}") for player in giver.players]

    def order(pick: TradePick) -> tuple[int, int, int, int]:
        # Unknown seasons and rounds sort last
        return (
            -pick.season if pick.season else 1,
            _tier_rank(pick.tier, tier_order),
            pick.round if pick.round is not None else 10_000,
            pick.number or 10_000,
        )

    lines += [_Line(f"- **Pick** {p.describe()}", picks=1) for p in sorted((p for p in giver.picks if not p.future), key=order)]
    lines += [_Line(f"- **Future Pick** {p.describe()}", picks=1) for p in sorted((p for p in giver.picks if p.future), key=order)]
    return lines


@dataclass(frozen=True)
class TradeCard:
    """A trade: the banner, then one card per receiving franchise, then the transaction ID."""

    receivers: tuple[TradeReceiver, ...]
    banner: Path
    created_at: datetime
    transaction_id: int | None = None
    # Tier names, highest first, to order the picks
    tier_order: tuple[str, ...] = field(default=())

    def render(self) -> tuple[ui.LayoutView, list[discord.File]]:
        """The message and the files it references. Fresh Files each call, since a send consumes them."""
        cards, omitted = self._plan()
        view = ui.LayoutView(timeout=None)

        # The banner is the message's header, as wide as the cards under it
        banner = discord.File(self.banner, filename=self.banner.name)
        view.add_item(ui.MediaGallery(discord.MediaGalleryItem(banner, description="Trade")))
        for card in cards:
            view.add_item(card.container())
        if omitted:
            view.add_item(ui.TextDisplay(self._omitted_text(omitted)))
        view.add_item(ui.TextDisplay(self._footer()))
        return view, [banner]

    def _footer(self) -> str:
        when = discord.utils.format_dt(self.created_at, "f")
        return f"-# Transaction ID: {self.transaction_id} · {when}" if self.transaction_id is not None else f"-# {when}"

    @staticmethod
    def _omitted_text(receivers: list[TradeReceiver]) -> str:
        """The franchises that didn't fit as cards, one line each, still pinging their GM and players."""
        lines = [f"-# …and {len(receivers)} more franchise{'' if len(receivers) == 1 else 's'}"]
        for receiver in receivers:
            parts = [f"**{receiver.name}**"]
            if receiver.gm_id:
                parts.append(f"**GM** <@{receiver.gm_id}>")
            # Givers with no card of their own are pinged here too
            parts += [f"**From** {g.name} · **GM** <@{g.gm_id}>" for g in receiver.givers if g.name and g.gm_id]
            players = [p.mention for g in receiver.givers for p in g.players]
            if players:
                parts.append(", ".join(players))
            picks = sum(len(g.picks) for g in receiver.givers)
            if picks:
                parts.append(f"{picks} pick{'' if picks == 1 else 's'}")
            lines.append(" · ".join(parts))
        return "\n".join(lines)

    def _plan(self) -> tuple[list[_Card], list[TradeReceiver]]:
        """Fit the message to Discord's limits.

        Components, past 40: drop the space under headings from the last card up, then the logos the
        same way, then put each card's givers in one TextDisplay, then list the last franchises in one
        line each. Text, past 3,900 characters: cut picks from the longest list, which ends
        `…and N more picks`. Players are never cut.
        """
        # Every giver is labelled, so a two-franchise trade looks like a bigger one
        cards = [
            _Card(
                receiver=r,
                groups=[_Group(g.name, _giver_lines(g, self.tier_order), gm_id=g.gm_id) for g in r.givers],
                logo=r.logo is not None,
            )
            for r in self.receivers
        ]
        omitted: list[TradeReceiver] = []

        def components() -> int:
            # The banner gallery, the footer, and the omitted line when there is one
            return 2 + sum(card.components() for card in cards) + (1 if omitted else 0)

        while components() > TRADE_MAX_COMPONENTS:
            spaced = [card for card in cards if card.spaced]
            with_logo = [card for card in cards if card.logo]
            splittable = [card for card in cards if len(card.bodies()) > 1]
            if spaced:
                spaced[-1].spaced = False
            elif with_logo:
                with_logo[-1].logo = False
            elif splittable:
                max(splittable, key=lambda card: len(card.groups)).split = False
            elif len(cards) > 1:
                omitted.insert(0, cards.pop().receiver)
            else:
                break

        def text_length() -> int:
            texts = [text for card in cards for text in card.texts()]
            if omitted:
                texts.append(self._omitted_text(omitted))
            texts.append(self._footer())
            return sum(len(text) for text in texts)

        while text_length() > TRADE_MAX_TEXT:
            cuttable = [group for card in cards for group in card.groups if any(line.picks for line in group.lines)]
            if not cuttable:
                log.warning("Trade card is over the text limit with nothing left to cut")
                break
            group = max(cuttable, key=lambda g: len(g.text()))
            index = max(i for i, line in enumerate(group.lines) if line.picks)
            group.cut += group.lines.pop(index).picks

        return cards, omitted
