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
    CheckboxGroup,
    Container,
    Label,
    MediaGallery,
    RadioGroup,
    Section,
    Select,
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

# How long opening Form 2 waits on the prefill lookup. Discord wants the modal within 3 seconds.
PREFILL_WAIT = 1.5


class SignupKind(StrEnum):
    FREE_AGENT = "FA"
    PERMFA = "PERMFA"

    @property
    def label(self) -> str:
        match self:
            case SignupKind.FREE_AGENT:
                return "Free Agent"
            case SignupKind.PERMFA:
                return "Permanent Free Agent"
            case _:
                raise ValueError(f"Unknown Signup Kind: {self}")


class SignupStage(Enum):
    FORM = auto()  # Form 1 is open and nothing has been posted yet
    BRIDGE = auto()  # Form 1 is done, waiting on Form 2
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
    kind: SignupKind | None = None
    player_type: PlayerType | None = None
    region: RegionPreference | None = None
    rsc_name: str = ""
    platform: Platform | None = None
    referrer: Referrer | None = None
    trackers: list[TrackerLine] = field(default_factory=list)

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
            self.kind
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


class AboutYouModal(discord.ui.Modal):
    """Form 1: agreements, how they want to play, experience and region."""

    def __init__(self, flow: "SignupFlowView"):
        if flow.stage is not SignupStage.FORM:
            title = "Edit your details"
        elif flow.context.kind is SignupKind.PERMFA:
            title = "Sign up as a Permanent Free Agent"
        else:
            title = "Sign up for RSC"
        super().__init__(title=title, timeout=MODAL_TIMEOUT)
        self.flow = flow
        answers = flow.answers
        nights = flow.context.match_nights
        agreed = flow.stage is not SignupStage.FORM

        self.add_item(TextDisplay(f"**Match nights:** {nights.days} at 10 PM ET.\n[Read the RSC behaviour rules]({BEHAVIOR_RULES_URL})"))

        # Both boxes must be ticked
        self.agreements: CheckboxGroup = CheckboxGroup(required=True, min_values=2, max_values=2)
        self.agreements.add_option(
            label="I can play on match nights", value="nights", description=f"{nights.days} at 10 PM ET", default=agreed
        )
        self.agreements.add_option(
            label="I agree to the RSC behaviour rules",
            value="rules",
            description="In our Discord, on the website and in every RSC match",
            default=agreed,
        )
        self.add_item(Label(text="Before you start", component=self.agreements))

        kind = answers.kind or flow.context.kind
        self.kind: RadioGroup = RadioGroup(required=True)
        self.kind.add_option(
            label=SignupKind.FREE_AGENT.label,
            value=SignupKind.FREE_AGENT,
            description="Can be drafted and signed to a team",
            default=kind is SignupKind.FREE_AGENT,
        )
        self.kind.add_option(
            label=SignupKind.PERMFA.label,
            value=SignupKind.PERMFA,
            description="Sub for teams in your tier, never signed to a roster",
            default=kind is SignupKind.PERMFA,
        )
        self.add_item(Label(text="How do you want to play?", component=self.kind))

        played = answers.player_type or flow.context.player_type
        self.played: RadioGroup = RadioGroup(required=True)
        self.played.add_option(label="No, this is my first season", value=PlayerType.NEW, default=played is PlayerType.NEW)
        self.played.add_option(
            label="Yes, I've played before",
            value=PlayerType.FORMER,
            description="In any earlier RSC season",
            default=played is PlayerType.FORMER,
        )
        self.add_item(Label(text="Have you played in RSC before?", component=self.played))

        self.region: RadioGroup = RadioGroup(required=True)
        for region in RegionPreference:
            self.region.add_option(label=region.full_name, value=region, default=region is answers.region)
        self.add_item(Label(text="Where do you usually play from?", component=self.region))

    async def on_submit(self, interaction: discord.Interaction):
        await self.flow.about_you_submitted(interaction, self)

    async def on_timeout(self):
        await self.flow.form_timed_out()


class NameTrackersModal(discord.ui.Modal):
    """Form 2: in-game name, platform, how they found RSC and tracker links."""

    def __init__(self, flow: "SignupFlowView", prefill: SignupPrefill):
        super().__init__(title="Name & trackers", timeout=MODAL_TIMEOUT)
        self.flow = flow
        answers = flow.answers

        name = answers.rsc_name or prefill.rsc_name
        self.name_input: TextInput = TextInput(placeholder="Your in-game name", default=name or None, min_length=2, max_length=25)
        name_hint = (
            "From your RSC profile. Change it if you play under a new name."
            if prefill.rsc_name and not answers.rsc_name
            else "Exactly as it shows in your matches."
        )
        self.add_item(Label(text="In-game name", description=name_hint, component=self.name_input))

        self.platform: Select = Select(placeholder="Choose one", required=True)
        for platform in Platform:
            self.platform.add_option(label=platform.label, value=platform, default=platform is answers.platform)
        self.add_item(Label(text="Main platform", description="The one you play RSC matches on.", component=self.platform))

        self.referrer: Select = Select(placeholder="Choose one", required=True)
        for referrer in Referrer:
            self.referrer.add_option(label=referrer.label, value=referrer, default=referrer is answers.referrer)
        self.add_item(Label(text="How did you hear about RSC?", component=self.referrer))

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


class SignupFlowView(AuthorOnlyLayoutView):
    """Sign-up as two forms joined by one ephemeral message.

    The command opens :class:`AboutYouModal` straight away. Its Submit posts the one-line bridge,
    whose button opens :class:`NameTrackersModal`. That form turns the bridge into the review card,
    where either form can be reopened filled in. Every message here is ephemeral.
    """

    def __init__(self, interaction: discord.Interaction, context: SignupContext, timeout: float = MODAL_TIMEOUT * 2):
        super().__init__(interaction=interaction, timeout=timeout)
        self.context = context
        self.answers = SignupAnswers()
        self.stage = SignupStage.FORM
        self.outcome = SignupOutcome.PENDING
        self.prefill: asyncio.Task[SignupPrefill] | None = None
        self.submit_interaction: discord.Interaction | None = None
        # Latest interaction whose response is the sign-up message, used to edit it on timeout
        self.message_interaction: discord.Interaction | None = None

    # ── entry points ──

    async def start(self) -> None:
        await self.interaction.response.send_modal(AboutYouModal(self))

    async def wait_for_outcome(self) -> SignupOutcome:
        if await self.wait() and self.outcome is SignupOutcome.PENDING:
            self.outcome = SignupOutcome.TIMED_OUT
        return self.outcome

    # ── forms ──

    async def about_you_submitted(self, interaction: discord.Interaction, form: AboutYouModal) -> None:
        if self.is_finished():
            await interaction.response.defer()
            return
        a = self.answers
        a.kind = SignupKind(form.kind.value) if form.kind.value else a.kind
        a.player_type = PlayerType(form.played.value) if form.played.value else a.player_type
        a.region = RegionPreference(form.region.value) if form.region.value else a.region

        if self.stage is SignupStage.FORM:
            self.stage = SignupStage.BRIDGE
            self.render()
            await interaction.response.send_message(view=self, ephemeral=True)
        else:
            self.render()
            await interaction.response.edit_message(view=self)
        self._touch(interaction)

    async def name_trackers_submitted(self, interaction: discord.Interaction, form: NameTrackersModal) -> None:
        if self.is_finished():
            await interaction.response.defer()
            return
        a = self.answers
        a.rsc_name = form.name_input.value.strip()
        a.platform = Platform(form.platform.values[0]) if form.platform.values else a.platform
        a.referrer = Referrer(form.referrer.values[0]) if form.referrer.values else a.referrer
        a.trackers = await parse_tracker_links(form.links_input.value)
        self.stage = SignupStage.REVIEW
        self.render()
        await interaction.response.edit_message(view=self)
        self._touch(interaction)

    async def trackers_fixed(self, interaction: discord.Interaction, form: FixTrackersModal) -> None:
        if self.is_finished():
            await interaction.response.defer()
            return
        self.answers.trackers = await parse_tracker_links(form.links_input.value)
        self.render()
        await interaction.response.edit_message(view=self)
        self._touch(interaction)

    async def form_timed_out(self) -> None:
        """Only Form 1, before anything is posted, ends the sign-up. Later forms can be reopened."""
        if self.stage is SignupStage.FORM and self.outcome is SignupOutcome.PENDING:
            self.outcome = SignupOutcome.TIMED_OUT
            self.stop()

    async def prefill_result(self) -> SignupPrefill:
        if self.prefill is None:
            return SignupPrefill()
        try:
            return await asyncio.wait_for(asyncio.shield(self.prefill), PREFILL_WAIT)
        except Exception as exc:
            log.debug(f"Signup prefill unavailable: {exc!r}")
            return SignupPrefill()

    # ── buttons ──

    async def open_about_you(self, interaction: discord.Interaction) -> None:
        await interaction.response.send_modal(AboutYouModal(self))

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
            self.render()
            await interaction.response.edit_message(view=self)
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

    def _touch(self, interaction: discord.Interaction) -> None:
        """Remember the message's latest interaction and restart the inactivity timer"""
        self.message_interaction = interaction
        self.timeout = self.timeout

    def render(self) -> None:
        self.clear_items()
        if self.stage is SignupStage.BRIDGE:
            self.add_item(TextDisplay("✅ **Step 1 of 2 done.** Next: your in-game name and trackers."))
            self.add_item(
                ActionRow(
                    _FlowButton(
                        SignupFlowView.open_name_trackers,
                        label="Continue to step 2",
                        style=discord.ButtonStyle.primary,
                        emoji="\N{MEMO}",
                    ),
                    _FlowButton(SignupFlowView.cancel, label="Cancel", style=discord.ButtonStyle.secondary),
                )
            )
        elif self.stage in (SignupStage.REVIEW, SignupStage.SUBMITTING):
            self.add_item(self._review())

    def _review(self) -> Container:
        a = self.answers
        busy = self.stage is SignupStage.SUBMITTING
        bad = bool(a.bad_trackers)
        nights = self.context.match_nights
        title = "RSC PERMFA SIGN-UP" if a.kind is SignupKind.PERMFA else "RSC SIGN-UP"

        about = [part.label for part in (a.kind, a.player_type) if part]
        if a.region:
            about.append(a.region.full_name)
        details = [f"**{a.rsc_name}**"]
        if a.platform:
            details.append(a.platform.label)
        if a.referrer:
            details.append(f"heard about us from {referrer_phrase(a.referrer)}")

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
                TextDisplay("**About you**\n" + " · ".join(about)),
                accessory=_FlowButton(SignupFlowView.open_about_you, label="Edit", emoji="\N{PENCIL}", disabled=busy),
            ),
            Separator(),
            Section(TextDisplay(" · ".join(details) + "\n" + tracker_summary(a)), accessory=tracker_button),
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
                _FlowButton(SignupFlowView.cancel, label="Cancel", style=discord.ButtonStyle.secondary, disabled=busy),
            ),
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
    """E3 and E3W. Shown before Form 1 for PermFAs, or when the API rejects a duplicate sign-up."""

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
