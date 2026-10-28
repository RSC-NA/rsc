import asyncio
import logging
from collections.abc import Awaitable, Callable
from dataclasses import dataclass, field
from datetime import datetime, time, timedelta
from enum import Enum, StrEnum, auto
from zoneinfo import ZoneInfo

import discord
from discord.ui import (
    ActionRow,
    Container,
    Label,
    MediaGallery,
    Section,
    Separator,
    TextDisplay,
    TextInput,
)

from rsc.const import BEHAVIOR_RULES_URL, MODAL_TIMEOUT
from rsc.enums import Platform, PlayerType, Referrer, RegionPreference
from rsc.members.tracker_links import TRACKER_EXAMPLE, TrackerLine, TrackerProblem, parse_tracker_links
from rsc.utils.images import SIGNUP_BANNER_FILENAME
from rsc.views import AuthorOnlyLayoutView, ResultView

log = logging.getLogger("red.rsc.members.views.signup")

# Guild ID for the 2v2 league
_2V2_GUILD_ID = 809939294331994113

_EASTERN = ZoneInfo("America/New_York")
_MATCH_START = time(22)

FLOW_COLOUR = discord.Colour.blurple()
PERMFA_COLOUR = discord.Colour(0xF0B232)
READY_COLOUR = discord.Colour(0x23A55A)
FIX_COLOUR = discord.Colour(0xF0B232)

TRACKER_SITE_URL = "https://rocketleague.tracker.network"
STEAM_ID_URL = "https://steamidfinder.com/"

# How long opening the form waits on the prefill lookup. Discord wants the modal within 3 seconds.
PREFILL_WAIT = 1.5

# Inactivity before the sign-up message times out. Kept under the 15 minute life of an
# interaction token, so the timeout card can still be drawn, and over MODAL_TIMEOUT.
FLOW_TIMEOUT = 14 * 60.0

# Open design choices, kept as switches so they're easy to flip.
# /permfa still shows "How do you want to play?", with PermFA picked
PERMFA_ASKS_KIND = True
# A second click on a confirm button turns it grey again
CONFIRMS_CAN_UNDO = True
# Send straight from the form when every tracker parses, instead of showing the review card
SKIP_REVIEW_WHEN_VALID = False


class SignupKind(StrEnum):
    FREE_AGENT = "FA"
    PERMFA = "PERMFA"

    @property
    def label(self) -> str:
        match self:
            # Signing up puts a player in the draft; nobody signs up as a Free Agent
            case SignupKind.FREE_AGENT:
                return "Draft eligible"
            case SignupKind.PERMFA:
                return "Permanent Free Agent"
            case _:
                raise ValueError(f"Unknown Signup Kind: {self}")


KIND_QUESTION = (
    "**How do you want to play?**\n"
    "-# **Draft eligible:** you enter the draft, and a team can draft you onto its roster for the season.\n"
    "-# **Permanent Free Agent:** you skip the draft and sub for teams in your tier. You're never signed to a roster."
)

# Every answer picked on the message rather than typed in the form
Choice = SignupKind | PlayerType | RegionPreference | Platform | Referrer


class SignupStage(Enum):
    GATE = auto()  # Step 1: confirm match nights and rules
    ABOUT = auto()  # Step 2: how they play and their setup
    REVIEW = auto()
    SUBMITTING = auto()


class SignupOutcome(Enum):
    PENDING = auto()
    SUBMITTED = auto()
    CANCELLED = auto()
    TIMED_OUT = auto()


class AlreadySignedUp(Enum):
    SIGNUP = auto()
    PERMFA = auto()
    PERMFA_WAITING = auto()


@dataclass(frozen=True)
class MatchNights:
    weekdays: tuple[int, ...]  # Monday is 0
    days: str
    short: str

    def next_start(self, now: datetime | None = None) -> datetime:
        """Start of the next match night, 10 PM Eastern"""
        now = (now or datetime.now(_EASTERN)).astimezone(_EASTERN)
        for offset in range(8):
            day = now.date() + timedelta(days=offset)
            start = datetime.combine(day, _MATCH_START, tzinfo=_EASTERN)
            if day.weekday() in self.weekdays and start > now:
                return start
        raise ValueError("No match night in the next week")


MATCH_NIGHTS_3V3 = MatchNights(weekdays=(0, 2), days="Monday and Wednesday", short="Mon & Wed")
MATCH_NIGHTS_2V2 = MatchNights(weekdays=(3,), days="Thursday", short="Thu")


@dataclass(frozen=True)
class SignupContext:
    """What the command knows before the first form opens."""

    command: str = "signup"
    is_2v2: bool = False
    season_number: int | None = None
    kind: SignupKind | None = None  # preselected by /permfa
    player_type: PlayerType | None = None  # preselected for returning players

    @classmethod
    def for_guild(cls, guild: discord.Guild | None, **kwargs) -> "SignupContext":
        return cls(is_2v2=bool(guild and guild.id == _2V2_GUILD_ID), **kwargs)

    @property
    def match_nights(self) -> MatchNights:
        return MATCH_NIGHTS_2V2 if self.is_2v2 else MATCH_NIGHTS_3V3

    @property
    def game_mode(self) -> str:
        return "2v2" if self.is_2v2 else "3v3"


@dataclass(frozen=True)
class SignupPrefill:
    """What RSC already has on file. The name is only set for members that existed before this sign-up."""

    rsc_name: str | None = None
    trackers: tuple[str, ...] = ()


@dataclass
class SignupAnswers:
    nights_confirmed: bool = False
    rules_accepted: bool = False
    kind: SignupKind | None = None
    player_type: PlayerType | None = None
    region: RegionPreference | None = None
    rsc_name: str = ""
    platform: Platform | None = None
    referrer: Referrer | None = None
    trackers: list[TrackerLine] = field(default_factory=list)

    def pick(self, choice: Choice) -> None:
        match choice:
            case SignupKind():
                self.kind = choice
            case PlayerType():
                self.player_type = choice
            case RegionPreference():
                self.region = choice
            case Platform():
                self.platform = choice
            case Referrer():
                self.referrer = choice

    @property
    def missing_confirmations(self) -> list[str]:
        missing = []
        if not self.nights_confirmed:
            missing.append("match nights")
        if not self.rules_accepted:
            missing.append("the rules")
        return missing

    @property
    def missing_choices(self) -> list[str]:
        answers = [
            (self.kind, "how you'll play"),
            (self.player_type, "played before"),
            (self.region, "region"),
            (self.platform, "platform"),
            (self.referrer, "how you heard about RSC"),
        ]
        return [name for answer, name in answers if answer is None]

    @property
    def bad_trackers(self) -> list[TrackerLine]:
        return [t for t in self.trackers if not t.valid]

    @property
    def tracker_urls(self) -> list[str]:
        return [t.url for t in self.trackers if t.valid]

    @property
    def tracker_text(self) -> str:
        return "\n".join(t.raw for t in self.trackers)

    @property
    def ready(self) -> bool:
        return bool(
            self.nights_confirmed
            and self.rules_accepted
            and self.kind
            and self.player_type
            and self.region
            and self.rsc_name
            and self.platform
            and self.referrer
            and self.trackers
            and not self.bad_trackers
        )


def referrer_phrase(referrer: Referrer) -> str:
    """Finishes 'heard about us from …'"""
    match referrer:
        case Referrer.FRIEND | Referrer.OTHER:
            return referrer.label.lower()
        case _:
            return referrer.label


def joined(items: list[str]) -> str:
    """'a', 'a and b', 'a, b and c'"""
    if len(items) < 2:
        return "".join(items)
    return ", ".join(items[:-1]) + " and " + items[-1]


def _code(text: str, limit: int = 80) -> str:
    """Inline code that the player's own backticks can't break"""
    text = text.replace("`", "'")
    if len(text) > limit:
        text = text[: limit - 1] + "…"
    return f"`{text}`"


def tracker_problem_text(trackers: list[TrackerLine]) -> str:
    """The explanation at the top of the fix form"""
    bad = [(i, t) for i, t in enumerate(trackers, start=1) if not t.valid]
    if len(bad) == 1:
        number, line = bad[0]
        lines = [f"### ⚠️ Line {number} {line.problem}", f"You entered {_code(line.raw)}."]
    else:
        lines = [f"### ⚠️ {len(bad)} links need fixing"]
        lines += [f"- Line {number}: {_code(line.raw, 50)} {line.problem}" for number, line in bad]

    problems = {line.problem for _, line in bad}
    if problems - {TrackerProblem.NOT_STEAM64}:
        lines.append(
            f"Open your profile on the tracker site and copy the full address from your browser. It should look like:\n`{TRACKER_EXAMPLE}`"
        )
    if TrackerProblem.NOT_STEAM64 in problems:
        lines.append(f"Steam profiles must use your 17-digit Steam64ID, not a custom name. [Find yours here]({STEAM_ID_URL}).")
    return "\n".join(lines)


def tracker_summary(answers: SignupAnswers, limit: int = 10) -> str:
    """Trackers block on the review card"""
    total = len(answers.trackers)
    bad = len(answers.bad_trackers)
    if bad:
        head = f"**Trackers** · {bad} of {total} need{'s' if bad == 1 else ''} fixing"
    else:
        head = f"**Trackers** · {total} account{'s' if total != 1 else ''}"
    rows = []
    for line in answers.trackers[:limit]:
        if line.valid:
            rows.append(f"- {line.platform_name} · {_code(line.player_id, 40)}")
        else:
            rows.append(f"- ⚠️ {_code(line.raw, 50)} {line.problem}")
    if total > limit:
        rows.append(f"- and {total - limit} more")
    return "\n".join([head, *rows])


# ── Forms ────────────────────────────────────────────────────────────────


class NameTrackersModal(discord.ui.Modal):
    """Step 3, the only form: in-game name and tracker links. Everything else is picked on the message."""

    def __init__(self, flow: "SignupFlowView", prefill: SignupPrefill):
        # Reopened from the review card once it's been filled in
        title = "Name & trackers" if flow.answers.rsc_name else "Step 3 of 3: Name & trackers"
        super().__init__(title=title, timeout=MODAL_TIMEOUT)
        self.flow = flow
        answers = flow.answers

        name = answers.rsc_name or prefill.rsc_name
        self.name_input: TextInput = TextInput(placeholder="Your in-game name", default=name or None, min_length=2, max_length=25)
        name_hint = "Must match your in-game name on your tracker link."
        if prefill.rsc_name and not answers.rsc_name:
            name_hint = f"From your RSC profile. {name_hint}"
        self.add_item(Label(text="In-game name", description=name_hint, component=self.name_input))

        self.add_item(
            TextDisplay(
                "**Your trackers**\n"
                f"-# Add every account you play on, one link per line. Find yours at [rocketleague.tracker.network]({TRACKER_SITE_URL}). "
                f"Steam accounts use your Steam64ID ([find it here]({STEAM_ID_URL})). "
                f"One account needs at least 50 {flow.context.game_mode} games."
            )
        )

        links = answers.tracker_text or "\n".join(prefill.trackers)
        self.links_input: TextInput = TextInput(style=discord.TextStyle.paragraph, placeholder=TRACKER_EXAMPLE, default=links or None)
        links_hint = (
            "These are the trackers on your RSC profile. Add any new accounts."
            if prefill.trackers and not answers.trackers
            else "Paste the full profile address from your browser, one per line."
        )
        self.add_item(Label(text="Tracker links", description=links_hint, component=self.links_input))

    async def on_submit(self, interaction: discord.Interaction):
        await self.flow.name_trackers_submitted(interaction, self)


class FixTrackersModal(discord.ui.Modal):
    """Only the tracker field, with the problem spelled out. Name and referrer are already saved."""

    def __init__(self, flow: "SignupFlowView"):
        super().__init__(title="Fix your trackers", timeout=MODAL_TIMEOUT)
        self.flow = flow
        self.add_item(TextDisplay(tracker_problem_text(flow.answers.trackers)))
        self.links_input: TextInput = TextInput(style=discord.TextStyle.paragraph, default=flow.answers.tracker_text or None)
        self.add_item(Label(text="Tracker links", description="One per line. Your other links are kept.", component=self.links_input))

    async def on_submit(self, interaction: discord.Interaction):
        await self.flow.trackers_fixed(interaction, self)


# ── Flow ─────────────────────────────────────────────────────────────────

FlowAction = Callable[["SignupFlowView", discord.Interaction], Awaitable[None]]


class _FlowButton(discord.ui.Button["SignupFlowView"]):
    def __init__(self, action: FlowAction, **kwargs):
        super().__init__(**kwargs)
        self.action = action

    async def callback(self, interaction: discord.Interaction):
        if self.view is None:
            return
        await self.action(self.view, interaction)


class _ChoiceButton(discord.ui.Button["SignupFlowView"]):
    """One answer to a button-row question. The picked one is blurple."""

    def __init__(self, choice: Choice, label: str, picked: Choice | None):
        style = discord.ButtonStyle.primary if choice is picked else discord.ButtonStyle.secondary
        super().__init__(label=label, style=style)
        self.choice = choice

    async def callback(self, interaction: discord.Interaction):
        if self.view is None:
            return
        await self.view.choose(interaction, self.choice)


class _ChoiceSelect(discord.ui.Select["SignupFlowView"]):
    """A select-menu question. Each redraw shows the pick as the default, so it isn't lost."""

    def __init__(self, placeholder: str, choices: list[tuple[Choice, str]], picked: Choice | None):
        options = [discord.SelectOption(label=label, value=choice.value, default=choice is picked) for choice, label in choices]
        super().__init__(placeholder=placeholder, options=options)
        self.choices = {choice.value: choice for choice, _ in choices}

    async def callback(self, interaction: discord.Interaction):
        if self.view is None:
            return
        await self.view.choose(interaction, self.choices[self.values[0]])


class SignupFlowView(AuthorOnlyLayoutView):
    """Sign-up as one ephemeral message, edited in place, and one form.

    The command posts step 1, "Before you start": Continue stays disabled until both confirm buttons
    are green. It redraws the message as step 2, "About you", whose Continue opens
    :class:`NameTrackersModal`. That form turns the message into the review card, where any answer
    can be changed. Every message here is ephemeral.
    """

    def __init__(self, interaction: discord.Interaction, context: SignupContext, timeout: float = FLOW_TIMEOUT):
        super().__init__(interaction=interaction, timeout=timeout)
        self.context = context
        # /permfa preselects PermFA, and dropped players are preset as returning
        self.answers = SignupAnswers(kind=context.kind, player_type=context.player_type)
        self.stage = SignupStage.GATE
        self.outcome = SignupOutcome.PENDING
        self.prefill: asyncio.Task[SignupPrefill] | None = None
        self.submit_interaction: discord.Interaction | None = None
        # Latest interaction whose response is the sign-up message, used to edit it on timeout
        self.message_interaction: discord.Interaction | None = None

    # ── entry points ──

    async def start(self) -> None:
        self.render()
        await self.interaction.response.send_message(view=self, ephemeral=True)
        self.message_interaction = self.interaction

    async def wait_for_outcome(self) -> SignupOutcome:
        if await self.wait() and self.outcome is SignupOutcome.PENDING:
            self.outcome = SignupOutcome.TIMED_OUT
        return self.outcome

    # ── step 1: before you start ──

    async def toggle_nights(self, interaction: discord.Interaction) -> None:
        self.answers.nights_confirmed = not self.answers.nights_confirmed if CONFIRMS_CAN_UNDO else True
        await self._redraw(interaction)

    async def toggle_rules(self, interaction: discord.Interaction) -> None:
        self.answers.rules_accepted = not self.answers.rules_accepted if CONFIRMS_CAN_UNDO else True
        await self._redraw(interaction)

    async def to_about(self, interaction: discord.Interaction) -> None:
        if not self.answers.missing_confirmations:
            self.stage = SignupStage.ABOUT
        await self._redraw(interaction)

    # ── step 2: about you ──

    async def choose(self, interaction: discord.Interaction, choice: Choice) -> None:
        self.answers.pick(choice)
        await self._redraw(interaction)

    async def to_form(self, interaction: discord.Interaction) -> None:
        if self.answers.missing_choices:
            await self._redraw(interaction)
        elif self.answers.rsc_name:
            # Back from the review card's Edit: the form is already filled in
            self.stage = SignupStage.REVIEW
            await self._redraw(interaction)
        else:
            await self.open_name_trackers(interaction)

    # ── forms ──

    async def name_trackers_submitted(self, interaction: discord.Interaction, form: NameTrackersModal) -> None:
        if self.is_finished():
            await interaction.response.defer()
            return
        a = self.answers
        a.rsc_name = form.name_input.value.strip()
        a.trackers = await parse_tracker_links(form.links_input.value)
        if SKIP_REVIEW_WHEN_VALID and a.ready:
            await self.submit(interaction)
            return
        self.stage = SignupStage.REVIEW
        await self._redraw(interaction)

    async def trackers_fixed(self, interaction: discord.Interaction, form: FixTrackersModal) -> None:
        if self.is_finished():
            await interaction.response.defer()
            return
        self.answers.trackers = await parse_tracker_links(form.links_input.value)
        await self._redraw(interaction)

    async def prefill_result(self) -> SignupPrefill:
        """Whatever the lookup has within PREFILL_WAIT. The form opens either way."""
        if self.prefill is None:
            return SignupPrefill()
        try:
            return await asyncio.wait_for(asyncio.shield(self.prefill), PREFILL_WAIT)
        except Exception as exc:
            log.debug(f"Signup prefill unavailable: {exc!r}")
            return SignupPrefill()

    # ── buttons ──

    async def back_to_gate(self, interaction: discord.Interaction) -> None:
        # Answers are kept, so going forward again needs no re-picking
        self.stage = SignupStage.GATE
        await self._redraw(interaction)

    async def back_to_about(self, interaction: discord.Interaction) -> None:
        self.stage = SignupStage.ABOUT
        await self._redraw(interaction)

    async def open_name_trackers(self, interaction: discord.Interaction) -> None:
        await interaction.response.send_modal(NameTrackersModal(self, await self.prefill_result()))

    async def open_fix(self, interaction: discord.Interaction) -> None:
        await interaction.response.send_modal(FixTrackersModal(self))

    async def cancel(self, interaction: discord.Interaction) -> None:
        self.outcome = SignupOutcome.CANCELLED
        self.stop()
        await interaction.response.edit_message(view=signup_cancelled_view(self.context))

    async def submit(self, interaction: discord.Interaction) -> None:
        if not self.answers.ready:
            await self._redraw(interaction)
            return
        self.outcome = SignupOutcome.SUBMITTED
        self.stage = SignupStage.SUBMITTING
        self.render()
        await interaction.response.edit_message(view=self)
        self.submit_interaction = interaction
        self.stop()

    async def on_timeout(self):
        if self.outcome is not SignupOutcome.PENDING or self.message_interaction is None:
            return
        self.outcome = SignupOutcome.TIMED_OUT
        try:
            await self.message_interaction.edit_original_response(view=signup_timed_out_view(self.context))
        except discord.HTTPException as exc:
            log.debug(f"Could not show the sign-up timeout: {exc}")

    # ── rendering ──

    async def _redraw(self, interaction: discord.Interaction) -> None:
        self.render()
        await interaction.response.edit_message(view=self)
        self._touch(interaction)

    def _touch(self, interaction: discord.Interaction) -> None:
        """Remember the message's latest interaction and restart the inactivity timer"""
        self.message_interaction = interaction
        self.timeout = self.timeout

    def render(self) -> None:
        self.clear_items()
        match self.stage:
            case SignupStage.GATE:
                self.add_item(self._gate())
            case SignupStage.ABOUT:
                self.add_item(self._about())
            case SignupStage.REVIEW | SignupStage.SUBMITTING:
                self.add_item(self._review())

    @property
    def _kicker(self) -> str:
        return "RSC PERMFA SIGN-UP" if self.answers.kind is SignupKind.PERMFA else "RSC SIGN-UP"

    def _accent(self, ready: bool) -> discord.Colour:
        if ready:
            return READY_COLOUR
        return PERMFA_COLOUR if self.answers.kind is SignupKind.PERMFA else FLOW_COLOUR

    @staticmethod
    def _confirm(action: FlowAction, done: bool, *, ask: str, confirmed: str) -> ActionRow:
        """Grey until clicked, then green with its label changed, so colour isn't the only signal"""
        if done:
            return ActionRow(_FlowButton(action, label=confirmed, style=discord.ButtonStyle.success))
        return ActionRow(_FlowButton(action, label=ask, style=discord.ButtonStyle.secondary))

    @staticmethod
    def _continue_row(action: FlowAction, ready: bool) -> ActionRow:
        return ActionRow(
            _FlowButton(action, label="Continue", style=discord.ButtonStyle.primary, disabled=not ready),
            _FlowButton(SignupFlowView.cancel, label="Cancel", style=discord.ButtonStyle.danger),
        )

    @staticmethod
    def _back_row(action: FlowAction, disabled: bool = False) -> ActionRow:
        """Back sits on its own row under Continue and Cancel. A row can't be right-aligned."""
        return ActionRow(_FlowButton(action, label="Back", style=discord.ButtonStyle.secondary, disabled=disabled))

    @staticmethod
    def _questions(header: str, questions: list[tuple[str, ActionRow]]) -> list[discord.ui.Item]:
        """Each question above its answers, a thin line between questions. The header sits above the first."""
        items: list[discord.ui.Item] = []
        for number, (text, answers) in enumerate(questions):
            if number:
                items.append(Separator())
            items += [TextDisplay(f"-# {header}\n{text}" if number == 0 else text), answers]
        return items

    def _gate(self) -> Container:
        """Step 1: the match nights and the rules, each confirmed with its own button"""
        a = self.answers
        nights = self.context.match_nights
        missing = a.missing_confirmations
        if not missing:
            footer = "Next: a few questions about how you play."
        elif len(missing) == 2:
            footer = "Confirm both to continue."
        else:
            footer = f"Still to confirm: {missing[0]}."

        nights_text = f"-# MATCH NIGHTS\n**{nights.days} at 10 PM ET**"
        if self.context.kind is SignupKind.PERMFA:
            nights_text += "\n-# Subs play on these nights too."
        rules_text = (
            "-# BEHAVIOUR RULES\n"
            "They apply in our Discord, on the website and in every RSC match.\n"
            f"[Read the RSC behaviour rules]({BEHAVIOR_RULES_URL})"
        )

        return Container(
            TextDisplay(f"-# {self._kicker} · STEP 1 OF 3\n## Before you start"),
            Separator(),
            TextDisplay(nights_text),
            self._confirm(
                SignupFlowView.toggle_nights, a.nights_confirmed, ask="I can play on match nights", confirmed="Match nights confirmed"
            ),
            Separator(),
            TextDisplay(rules_text),
            self._confirm(SignupFlowView.toggle_rules, a.rules_accepted, ask="I agree to the rules", confirmed="Rules accepted"),
            Separator(),
            TextDisplay(f"-# {footer}"),
            self._continue_row(SignupFlowView.to_about, ready=not missing),
            accent_colour=self._accent(ready=not missing),
        )

    def _about(self) -> Container:
        """Step 2: three button-row questions and two selects"""
        a = self.answers
        missing = a.missing_choices
        if not missing:
            footer = "All set. Next: check your details." if a.rsc_name else "All set. Next: your in-game name and trackers."
        elif len(missing) == 5:
            footer = "Answer each question to continue."
        else:
            footer = f"Still to answer: {joined(missing)}."

        play: list[tuple[str, ActionRow]] = []
        if PERMFA_ASKS_KIND or self.context.kind is not SignupKind.PERMFA:
            play.append(
                (
                    KIND_QUESTION,
                    ActionRow(
                        _ChoiceButton(SignupKind.FREE_AGENT, "Draft eligible", a.kind),
                        _ChoiceButton(SignupKind.PERMFA, "Permanent Free Agent", a.kind),
                    ),
                )
            )
        play.append(
            (
                "**Have you played in RSC before?**",
                ActionRow(
                    _ChoiceButton(PlayerType.NEW, "No, first season", a.player_type),
                    _ChoiceButton(PlayerType.FORMER, "Yes, I've played", a.player_type),
                ),
            )
        )
        play.append(
            (
                "**Where do you usually play from?**",
                ActionRow(*(_ChoiceButton(region, region.full_name, a.region) for region in RegionPreference)),
            )
        )
        setup = [
            (
                "**Main platform**\n-# The one you play RSC matches on.",
                ActionRow(_ChoiceSelect("Choose your platform", [(p, p.label) for p in Platform], a.platform)),
            ),
            (
                "**How did you hear about RSC?**",
                ActionRow(_ChoiceSelect("Choose one", [(r, r.label) for r in Referrer], a.referrer)),
            ),
        ]

        return Container(
            TextDisplay(f"-# {self._kicker} · STEP 2 OF 3\n## About you"),
            Separator(),
            *self._questions("HOW YOU PLAY", play),
            Separator(),
            *self._questions("YOUR SETUP", setup),
            Separator(),
            TextDisplay(f"-# {footer}"),
            self._continue_row(SignupFlowView.to_form, ready=not missing),
            self._back_row(SignupFlowView.back_to_gate),
            accent_colour=self._accent(ready=not missing),
        )

    def _review(self) -> Container:
        a = self.answers
        busy = self.stage is SignupStage.SUBMITTING
        bad = bool(a.bad_trackers)
        nights = self.context.match_nights
        title = "RSC PERMFA SIGN-UP" if a.kind is SignupKind.PERMFA else "RSC SIGN-UP"

        # Everything picked in step 2, so its Edit goes back there
        about = [part.label for part in (a.kind, a.player_type) if part]
        if a.region:
            about.append(a.region.full_name)
        setup = []
        if a.platform:
            setup.append(a.platform.label)
        if a.referrer:
            setup.append(f"heard about us from {referrer_phrase(a.referrer)}")
        about_text = "\n".join(" · ".join(line) for line in (about, setup) if line)

        if bad:
            tracker_button = _FlowButton(
                SignupFlowView.open_fix, label="Fix", style=discord.ButtonStyle.primary, emoji="\N{PENCIL}", disabled=busy
            )
        else:
            tracker_button = _FlowButton(SignupFlowView.open_name_trackers, label="Edit", emoji="\N{PENCIL}", disabled=busy)

        if busy:
            footer = "-# Submitting your sign-up…"
        else:
            start = discord.utils.format_dt(nights.next_start(), "F")
            footer = f"-# ✓ Match nights ({nights.short}, 10 PM ET · {start} for you) · ✓ Rules"

        return Container(
            TextDisplay(f"-# {title} · REVIEW\n## Check your details"),
            Section(
                TextDisplay(f"**About you**\n{about_text}"),
                accessory=_FlowButton(SignupFlowView.back_to_about, label="Edit", emoji="\N{PENCIL}", disabled=busy),
            ),
            Separator(),
            Section(TextDisplay(f"**{a.rsc_name}**\n{tracker_summary(a)}"), accessory=tracker_button),
            Separator(),
            TextDisplay(footer),
            ActionRow(
                _FlowButton(
                    SignupFlowView.submit,
                    label="Submit sign-up",
                    style=discord.ButtonStyle.success,
                    emoji="\N{WHITE HEAVY CHECK MARK}",
                    disabled=bad or busy,
                ),
                _FlowButton(SignupFlowView.cancel, label="Cancel", style=discord.ButtonStyle.danger, disabled=busy),
            ),
            self._back_row(SignupFlowView.back_to_about, disabled=busy),
            accent_colour=FIX_COLOUR if bad else READY_COLOUR,
        )


# ── Endings ──────────────────────────────────────────────────────────────


def signup_cancelled_view(context: SignupContext) -> ResultView:
    return ResultView(
        title="Sign-up cancelled",
        description=f"Nothing was submitted. Run `/{context.command}` whenever you're ready.",
        colour=discord.Colour.dark_grey(),
    )


def signup_timed_out_view(context: SignupContext) -> ResultView:
    return ResultView(
        title="\N{STOPWATCH} Sign-up timed out",
        description=f"Nothing was submitted. Run `/{context.command}` to start again.",
        colour=discord.Colour.dark_grey(),
    )


@dataclass(frozen=True)
class BannerText:
    kicker: str
    headline: str
    name: str
    chips: list[str]
    permfa: bool


def banner_text(answers: SignupAnswers, context: SignupContext) -> BannerText:
    permfa = answers.kind is SignupKind.PERMFA
    if permfa:
        kicker, headline = "RSC · PERMFA SIGN-UP", "REQUEST SENT"
    else:
        kicker = f"RSC · SEASON {context.season_number}" if context.season_number else "RSC · NEXT SEASON"
        headline = "YOU'RE IN"
    returning = answers.player_type is PlayerType.FORMER
    chips = ["PermFA" if permfa else ("Returning" if returning else "New player")]
    if answers.region:
        chips.append(answers.region.full_name)
    if answers.platform:
        chips.append(answers.platform.name)
    return BannerText(kicker=kicker, headline=headline, name=answers.rsc_name, chips=chips, permfa=permfa)


class SignupSuccessView(discord.ui.LayoutView):
    """E1: the per-player banner, then what happens next."""

    def __init__(self, answers: SignupAnswers, context: SignupContext, *, banner: bool, nickname_too_long: bool = False):
        super().__init__(timeout=None)
        if answers.kind is SignupKind.PERMFA:
            heading = "## \N{WHITE HEAVY CHECK MARK} PermFA request sent"
            steps = (
                "- Staff will process your request. This can take a little while.\n"
                "- Once you're approved, teams in your tier can pick you up as a sub."
            )
        else:
            season = f"Season {context.season_number}" if context.season_number else "next season"
            heading = f"## \N{WHITE HEAVY CHECK MARK} You're signed up for {season}"
            steps = "- Watch league notices for the Draft and Combines.\n- Check where you stand any time with `/signupstatus`."

        items: list[discord.ui.Item] = []
        if banner:
            items.append(MediaGallery(discord.MediaGalleryItem(f"attachment://{SIGNUP_BANNER_FILENAME}")))
        items += [TextDisplay(heading), Separator(), TextDisplay(f"### What happens next\n{steps}")]
        if nickname_too_long:
            items.append(
                TextDisplay(
                    "-# Your nickname couldn't be updated because your RSC name is too long for Discord. "
                    "Open a modmail ticket to have it shortened."
                )
            )
        self.add_item(Container(*items, accent_colour=READY_COLOUR))


StatusAction = Callable[[discord.Interaction], Awaitable[None]]


class _StatusButton(discord.ui.Button["AlreadySignedUpView"]):
    def __init__(self, action: StatusAction, **kwargs):
        super().__init__(**kwargs)
        self.action = action

    async def callback(self, interaction: discord.Interaction):
        await self.action(interaction)


class AlreadySignedUpView(discord.ui.LayoutView):
    """E3 and E3W. Shown before step 1 for PermFAs, or when the API rejects a duplicate sign-up."""

    def __init__(
        self,
        state: AlreadySignedUp,
        *,
        interaction: discord.Interaction | None = None,
        on_status: StatusAction | None = None,
        on_intent: StatusAction | None = None,
    ):
        super().__init__(timeout=MODAL_TIMEOUT)
        self.state = state
        self.interaction = interaction
        self.on_status = on_status
        self.on_intent = on_intent
        self._render(buttons=True)

    def _render(self, *, buttons: bool) -> None:
        self.clear_items()
        match self.state:
            case AlreadySignedUp.SIGNUP:
                heading = "You're already signed up"
                body = "We already have your sign-up for next season, so there's nothing to fill in again."
                colour = FLOW_COLOUR
            case AlreadySignedUp.PERMFA:
                heading = "You're already a Permanent Free Agent"
                body = "You can already sub for teams in your tier, so there's nothing to send again."
                colour = PERMFA_COLOUR
            case AlreadySignedUp.PERMFA_WAITING:
                heading = "Your PermFA request is waiting on staff"
                body = (
                    "You've already signed up as a Permanent Free Agent. Staff haven't processed it yet, so there's nothing to send again."
                )
                colour = PERMFA_COLOUR
            case _:
                raise ValueError(f"Unknown state: {self.state}")

        status = _StatusButton(self.on_status, label="My status") if buttons and self.on_status else None
        items: list[discord.ui.Item] = [
            TextDisplay(f"## {heading}"),
            TextDisplay(body),
            Separator(),
            self._row("**Where do I stand?**\n-# See your status for next season.", status),
        ]
        match self.state:
            case AlreadySignedUp.SIGNUP:
                intent = (
                    _StatusButton(self.on_intent, label="Declare intent", style=discord.ButtonStyle.primary)
                    if buttons and self.on_intent
                    else None
                )
                items.append(self._row("**Played last season?**\n-# Returning players declare intent instead of signing up.", intent))
            case AlreadySignedUp.PERMFA:
                items.append(TextDisplay("-# Want a full-time team? League staff may offer PermFAs a move to regular Free Agent."))
            case AlreadySignedUp.PERMFA_WAITING:
                items.append(TextDisplay("-# Requests are processed by league staff. You'll get your PermFA role once it's approved."))
        self.add_item(Container(*items, accent_colour=colour))

    @staticmethod
    def _row(text: str, button: discord.ui.Button | None) -> Section | TextDisplay:
        if button is None:
            return TextDisplay(text)
        return Section(TextDisplay(text), accessory=button)

    async def on_timeout(self):
        """Drop the buttons rather than leave ones that no longer answer"""
        if self.interaction is None:
            return
        self._render(buttons=False)
        try:
            await self.interaction.edit_original_response(view=self)
        except discord.HTTPException as exc:
            log.debug(f"Could not remove expired sign-up buttons: {exc}")
