import discord.ui
import logging
from enum import IntEnum

import discord
from discord.ui import (
    ActionRow,
    Container,
    Label,
    Separator,
    TextDisplay,
    TextInput,
)

from rsc.const import BEHAVIOR_RULES_URL
from rsc.enums import Platform, PlayerType, Referrer, RegionPreference
from rsc.views import AuthorOnlyLayoutView, LinkButton

log = logging.getLogger("red.rsc.members.views.signup")

TrackerLink = str

# Guild ID for the 2v2 league
_2V2_GUILD_ID = 809939294331994113


class SignupState(IntEnum):
    TIMES = 0
    RULES = 1
    PLAYER_TYPE = 2
    REGION = 3
    PLATFORM = 4
    REFERRER = 5
    TRACKERS = 6
    FINISHED = 7
    CANCELLED = 8


# ── Modal ────────────────────────────────────────────────────────────────


class PlayerInfoModal(discord.ui.Modal, title="RSC Sign Up Information"):
    """Modal that collects the player's in-game name and tracker links.

    Includes instructional text so the user knows exactly what to provide.
    """

    def __init__(self, *, is_2v2: bool = False):
        super().__init__()
        self.submitted = False

        # In-game Name

        self.rsc_name = Label(
            text="In-game Name",
            description="Must match the name you play matches on exactly — no exceptions.",
            component=TextInput(
                style=discord.TextStyle.short,
                placeholder="Your in-game name...",
                min_length=2,
                max_length=25,
                required=True,
            ),
        )
        self.add_item(self.rsc_name)

        tracker_req = f"A tracker with 50 {'2v2' if is_2v2 else '3v3'} games played is required."

        self.add_item(
            TextDisplay(
                content=(
                    "### \N{BAR CHART}  Tracker Information\n"
                    "Submit tracker links for **ALL** of your accounts, each on a separate line.\n\n"
                    "Find your tracker(s) at "
                    "[rocketleague.tracker.network](https://rocketleague.tracker.network).\n\n"
                    "**Steam** accounts must use your Steam64ID "
                    "([find it here](https://steamidfinder.com/)).\n\n"
                    f"*{tracker_req}*"
                )
            )
        )

        self.links = Label(
            text="\N{BAR CHART} Tracker Links",
            description="One link per line for every account you own.",
            component=TextInput(
                style=discord.TextStyle.paragraph,
                placeholder=("https://rocketleague.tracker.network/rocket-league/profile/steam/76561197960409023/overview"),
                min_length=50,  # rough validation to prevent accidental non-link input
                required=True,
            ),
        )
        self.add_item(self.links)

    async def on_submit(self, interaction: discord.Interaction):
        self.submitted = True
        await interaction.response.defer(ephemeral=True)


# ── Shared Button / Select Components ────────────────────────────────────


class _StepButton(discord.ui.Button):
    """Button tied to a specific signup step."""

    def __init__(self, step: SignupState, **kwargs):
        super().__init__(**kwargs)
        self.step = step

    async def callback(self, interaction: discord.Interaction):
        view: SignupLayoutView = self.view  # type: ignore[assignment]
        await view.complete_step(interaction, self.step)


class _CancelButton(discord.ui.Button):
    """Cancel button that aborts the entire signup flow."""

    def __init__(self):
        super().__init__(label="Cancel", style=discord.ButtonStyle.danger, emoji="\N{OCTAGONAL SIGN}")

    async def callback(self, interaction: discord.Interaction):
        view: SignupLayoutView = self.view  # type: ignore[assignment]
        view.state = SignupState.CANCELLED
        view.stop()
        await interaction.response.defer(ephemeral=True)


class _EnumSelect(discord.ui.Select):
    """Base select tied to a signup step that auto-populates options from an enum."""

    step: SignupState  # set by subclasses

    async def callback(self, interaction: discord.Interaction):
        view: SignupLayoutView = self.view  # type: ignore[assignment]
        self.store_value(view, self.values[0])
        # Mark the chosen option as default so it displays when disabled
        for opt in self.options:
            opt.default = opt.value == self.values[0]
        await view.complete_step(interaction, self.step)

    def store_value(self, view: "SignupLayoutView", value: str) -> None:
        raise NotImplementedError


class _PlayerTypeSelect(_EnumSelect):
    step = SignupState.PLAYER_TYPE

    def __init__(self, *, disabled: bool = True):
        super().__init__(placeholder="New or former player...", disabled=disabled)
        for p in PlayerType:
            self.add_option(label=f"{p.value} PLAYER", value=p)

    def store_value(self, view: "SignupLayoutView", value: str) -> None:
        view.player_type = PlayerType(value)


class _RegionSelect(_EnumSelect):
    step = SignupState.REGION

    def __init__(self, *, disabled: bool = True):
        super().__init__(placeholder="Select your preferred region...", disabled=disabled)
        for p in RegionPreference:
            self.add_option(label=p.full_name.upper(), value=p)

    def store_value(self, view: "SignupLayoutView", value: str) -> None:
        view.region = RegionPreference(value)


class _PlatformSelect(_EnumSelect):
    step = SignupState.PLATFORM

    def __init__(self, *, disabled: bool = True):
        super().__init__(placeholder="Select your primary platform...", disabled=disabled)
        for p in Platform:
            self.add_option(label=p, value=p)

    def store_value(self, view: "SignupLayoutView", value: str) -> None:
        view.platform = Platform(value)


class _ReferrerSelect(_EnumSelect):
    step = SignupState.REFERRER

    def __init__(self, *, disabled: bool = True):
        super().__init__(placeholder="I found out about RSC from...", disabled=disabled)
        for p in Referrer:
            self.add_option(label=p, value=p)

    def store_value(self, view: "SignupLayoutView", value: str) -> None:
        view.referrer = Referrer(value)


# ── Phase 1: Agreement ──────────────────────────────────────────────────


class AgreementPhase:
    """Phase 1 — Game Times and Rules containers with gated agree buttons."""

    def __init__(self, *, is_2v2: bool):
        self.times_btn = _StepButton(
            step=SignupState.TIMES,
            label="Yes, I'm available",
            style=discord.ButtonStyle.success,
            emoji="\N{WHITE HEAVY CHECK MARK}",
        )
        self.rules_btn = _StepButton(
            step=SignupState.RULES,
            label="I Agree",
            style=discord.ButtonStyle.success,
            emoji="\N{WHITE HEAVY CHECK MARK}",
            disabled=True,
        )
        self.rules_link = LinkButton(label="RSC Behavior Rules", url=BEHAVIOR_RULES_URL)
        self.cancel_btn = _CancelButton()

        times_desc = (
            (
                "We play our games on **Thursday** nights at **10PM**.\n\n"
                "By selecting the button below, you are agreeing that you are available to play on those days and time."
            )
            if is_2v2
            else (
                "We play our games on **Monday** and **Wednesday** at **10PM EST**.\n\n"
                "By selecting the button below, you are agreeing that you are available to play on those days and time."
            )
        )

        self.times_container = Container(
            TextDisplay("## \N{CLOCK FACE TEN OCLOCK}  RSC Game Times"),  # codespell:ignore oclock
            TextDisplay(times_desc),
            Separator(spacing=discord.SeparatorSpacing.small),
            ActionRow(self.times_btn, self.cancel_btn),
            accent_colour=discord.Colour.blue(),
        )
        self.rules_container = Container(
            TextDisplay("## \N{SCROLL}  RSC Rules"),
            TextDisplay(
                "In RSC we maintain a non-negotiable set of rules regarding player behavior."
                " Please review the rules via the link below.\n\n"
                "By selecting **I Agree**, you are agreeing to all RSC rules in our Discord, website, and RSC-related games."
            ),
            Separator(spacing=discord.SeparatorSpacing.small),
            ActionRow(self.rules_btn, self.rules_link),
            accent_colour=discord.Colour.dark_grey(),
        )

    @property
    def containers(self) -> list[Container]:
        return [self.times_container, self.rules_container]

    def complete_step(self, step: SignupState) -> SignupState:
        """Update visuals for the completed step. Returns the next state."""
        completed = discord.Colour.green()
        unlocked = discord.Colour.blue()

        match step:
            case SignupState.TIMES:
                self.times_btn.disabled = True
                self.times_btn.label = "\N{WHITE HEAVY CHECK MARK} Accepted"
                self.times_btn.style = discord.ButtonStyle.secondary
                self.cancel_btn.disabled = True
                self.times_container.accent_colour = completed
                self.rules_btn.disabled = False
                self.rules_container.accent_colour = unlocked
                return SignupState.RULES
            case SignupState.RULES:
                return SignupState.PLAYER_TYPE
            case _:
                raise ValueError(f"AgreementPhase cannot handle step {step!r}")


# ── Phase 2: Player Info Selects ────────────────────────────────────────


class SelectPhase:
    """Phase 2 — Four sequential select dropdowns for player info."""

    def __init__(self):
        self.player_type_select = _PlayerTypeSelect(disabled=False)
        self.region_select = _RegionSelect()
        self.platform_select = _PlatformSelect()
        self.referrer_select = _ReferrerSelect()

        self.player_type_container = Container(
            TextDisplay("## \N{BUST IN SILHOUETTE}  New or Returning Player"),
            TextDisplay("Are you a new RSC player or returning from a previous season?"),
            Separator(spacing=discord.SeparatorSpacing.small),
            ActionRow(self.player_type_select),
            accent_colour=discord.Colour.blue(),
        )
        self.region_container = Container(
            TextDisplay("## \N{EARTH GLOBE AMERICAS}  Region Preference"),
            TextDisplay("What is your preferred region when playing Rocket League?"),
            Separator(spacing=discord.SeparatorSpacing.small),
            ActionRow(self.region_select),
            accent_colour=discord.Colour.dark_grey(),
        )
        self.platform_container = Container(
            TextDisplay("## \N{VIDEO GAME}  Primary Platform"),
            TextDisplay("Please select your primary platform for playing Rocket League."),
            Separator(spacing=discord.SeparatorSpacing.small),
            ActionRow(self.platform_select),
            accent_colour=discord.Colour.dark_grey(),
        )
        self.referrer_container = Container(
            TextDisplay("## \N{LEFT-POINTING MAGNIFYING GLASS}  How Did You Find Us?"),
            TextDisplay("How did you find out about RSC?"),
            Separator(spacing=discord.SeparatorSpacing.small),
            ActionRow(self.referrer_select),
            accent_colour=discord.Colour.dark_grey(),
        )

    @property
    def containers(self) -> list[Container]:
        return [
            self.player_type_container,
            self.region_container,
            self.platform_container,
            self.referrer_container,
        ]

    def complete_step(self, step: SignupState) -> SignupState:
        """Update visuals for the completed step. Returns the next state."""
        completed = discord.Colour.green()
        unlocked = discord.Colour.blue()

        match step:
            case SignupState.PLAYER_TYPE:
                self.player_type_select.disabled = True
                self.player_type_container.accent_colour = completed
                self.region_select.disabled = False
                self.region_container.accent_colour = unlocked
                return SignupState.REGION
            case SignupState.REGION:
                self.region_select.disabled = True
                self.region_container.accent_colour = completed
                self.platform_select.disabled = False
                self.platform_container.accent_colour = unlocked
                return SignupState.PLATFORM
            case SignupState.PLATFORM:
                self.platform_select.disabled = True
                self.platform_container.accent_colour = completed
                self.referrer_select.disabled = False
                self.referrer_container.accent_colour = unlocked
                return SignupState.REFERRER
            case SignupState.REFERRER:
                self.referrer_select.disabled = True
                self.referrer_container.accent_colour = completed
                return SignupState.TRACKERS
            case _:
                raise ValueError(f"SelectPhase cannot handle step {step!r}")


# ── Signup Layout View ──────────────────────────────────────────────────


class SignupLayoutView(AuthorOnlyLayoutView):
    """Three-phase signup form using Components V2 layout.

    Phase 1 — :class:`AgreementPhase`: Game Times and Rules acceptance.
    Phase 2 — :class:`SelectPhase`: Player Type, Region, Platform, Referrer.
    Phase 3 — :class:`PlayerInfoModal`: In-game name and tracker links.
    """

    def __init__(self, interaction: discord.Interaction, timeout: float = 600.0):
        super().__init__(interaction=interaction, timeout=timeout)
        self.state = SignupState.TIMES
        self.player_type = PlayerType.NEW
        self.platform = Platform.EPIC
        self.region = RegionPreference.EAST
        self.referrer = Referrer.OTHER
        self.rsc_name: str = ""
        self.trackers: list[TrackerLink] = []

        self._is_2v2 = bool(interaction.guild and interaction.guild.id == _2V2_GUILD_ID)

        self._agreement = AgreementPhase(is_2v2=self._is_2v2)
        self._selects: SelectPhase | None = None  # built lazily in Phase 2

        self._load_phase(self._agreement)

    # ── helpers ──

    def _load_phase(self, phase: AgreementPhase | SelectPhase) -> None:
        """Replace all items with the containers from *phase*."""
        self.clear_items()
        for container in phase.containers:
            self.add_item(container)

    # ── public ──

    async def prompt(self):
        """Send the initial layout view message."""
        await self.interaction.response.send_message(view=self, ephemeral=True)

    async def complete_step(self, interaction: discord.Interaction, step: SignupState):
        """Delegate step completion to the active phase and transition when needed."""
        log.debug(f"[SIGNUP] Completed step: {step.name}")

        # Phase 1 steps
        if step in (SignupState.TIMES, SignupState.RULES):
            next_state = self._agreement.complete_step(step)
            self.state = next_state

            if next_state == SignupState.PLAYER_TYPE:
                # Transition: swap to Phase 2
                self._selects = SelectPhase()
                self._load_phase(self._selects)
                await interaction.response.edit_message(view=self)
                return

            await interaction.response.edit_message(view=self)
            return

        # Phase 2 steps
        if self._selects is None:
            return  # should never happen
        next_state = self._selects.complete_step(step)
        self.state = next_state

        if next_state == SignupState.TRACKERS:
            # Transition: open the tracker modal (Phase 3)
            info_modal = PlayerInfoModal(is_2v2=self._is_2v2)
            await interaction.response.send_modal(info_modal)
            await info_modal.wait()

            if not info_modal.submitted:
                # User dismissed the modal
                self.state = SignupState.CANCELLED
                self.stop()
                return

            rsc_name_input: TextInput = info_modal.rsc_name.component  # type: ignore[assignment]
            links_input: TextInput = info_modal.links.component  # type: ignore[assignment]
            self.rsc_name = rsc_name_input.value
            self.trackers = links_input.value.splitlines()

            self.state = SignupState.FINISHED
            self.stop()
            await self.interaction.edit_original_response(view=self)
            return

        await interaction.response.edit_message(view=self)


# Alias so existing imports from other modules still work
SignupView = SignupLayoutView
