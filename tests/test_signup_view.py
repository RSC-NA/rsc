import asyncio
from datetime import datetime
from unittest.mock import AsyncMock, MagicMock, patch

import discord
from discord.ui import ActionRow, CheckboxGroup, Container, Label, MediaGallery, RadioGroup, Section, TextDisplay

from rsc.enums import Platform, PlayerType, Referrer, RegionPreference
from rsc.members.tracker_links import parse_tracker_links
from rsc.members.views import signup as signup_module
from rsc.members.views.signup import (
    MATCH_NIGHTS_2V2,
    MATCH_NIGHTS_3V3,
    AboutYouModal,
    AlreadySignedUp,
    AlreadySignedUpView,
    FixTrackersModal,
    NameTrackersModal,
    SignupContext,
    SignupFlowView,
    SignupKind,
    SignupOutcome,
    SignupPrefill,
    SignupStage,
    SignupSuccessView,
    banner_text,
    tracker_problem_text,
)

STEAM = "https://rocketleague.tracker.network/rocket-league/profile/steam/76561197960409023/overview"
EPIC = "https://rocketleague.tracker.network/rocket-league/profile/epic/Xentrick/overview"
BAD = "https://rocketleague.tracker.network/rocket-league/"
EASTERN = signup_module._EASTERN


def _interaction() -> MagicMock:
    interaction = MagicMock(spec=discord.Interaction)
    interaction.user = MagicMock(spec=discord.Member)
    interaction.response = MagicMock()
    interaction.response.send_modal = AsyncMock()
    interaction.response.send_message = AsyncMock()
    interaction.response.edit_message = AsyncMock()
    interaction.response.defer = AsyncMock()
    interaction.edit_original_response = AsyncMock()
    return interaction


def _flow(context: SignupContext | None = None) -> SignupFlowView:
    return SignupFlowView(_interaction(), context or SignupContext())


def _components(view: discord.ui.LayoutView) -> list[discord.ui.Item]:
    return list(view.walk_children())


def _buttons(view: discord.ui.LayoutView) -> dict[str, discord.ui.Button]:
    return {item.label or "": item for item in view.walk_children() if isinstance(item, discord.ui.Button)}


def _text(view: discord.ui.LayoutView) -> str:
    return "\n".join(item.content for item in view.walk_children() if isinstance(item, TextDisplay))


def _fill_about_you(form: AboutYouModal, kind=SignupKind.FREE_AGENT, played=PlayerType.NEW, region=RegionPreference.EAST) -> AboutYouModal:
    form.kind._value = kind.value
    form.played._value = played.value
    form.region._value = region.value
    form.agreements._values = ["nights", "rules"]
    return form


def _fill_name_trackers(form: NameTrackersModal, links: str, name="Xentrick") -> NameTrackersModal:
    form.name_input._value = name
    form.platform._values = [Platform.EPIC.value]
    form.referrer._values = [Referrer.FRIEND.value]
    form.links_input._value = links
    return form


async def _flow_at_review(links: str = f"{STEAM}\n{EPIC}", context: SignupContext | None = None) -> SignupFlowView:
    flow = _flow(context)
    await flow.about_you_submitted(_interaction(), _fill_about_you(AboutYouModal(flow)))
    await flow.name_trackers_submitted(_interaction(), _fill_name_trackers(NameTrackersModal(flow, SignupPrefill()), links))
    return flow


class TestMatchNights:
    def test_same_evening_before_ten(self):
        monday = datetime(2026, 11, 2, 21, 0, tzinfo=EASTERN)
        assert MATCH_NIGHTS_3V3.next_start(monday) == datetime(2026, 11, 2, 22, 0, tzinfo=EASTERN)

    def test_after_start_moves_to_next_night(self):
        monday = datetime(2026, 11, 2, 23, 0, tzinfo=EASTERN)
        assert MATCH_NIGHTS_3V3.next_start(monday) == datetime(2026, 11, 4, 22, 0, tzinfo=EASTERN)

    def test_2v2_plays_thursday(self):
        friday = datetime(2026, 11, 6, 12, 0, tzinfo=EASTERN)
        assert MATCH_NIGHTS_2V2.next_start(friday) == datetime(2026, 11, 12, 22, 0, tzinfo=EASTERN)

    def test_context_picks_2v2_by_guild(self):
        guild = MagicMock(spec=discord.Guild)
        guild.id = signup_module._2V2_GUILD_ID
        context = SignupContext.for_guild(guild)
        assert context.match_nights is MATCH_NIGHTS_2V2
        assert context.game_mode == "2v2"


class TestAboutYouModal:
    def test_has_five_items_with_required_agreements(self):
        form = AboutYouModal(_flow())
        assert len(form.children) == 5
        assert form.title == "Sign up for RSC"
        assert isinstance(form.agreements, CheckboxGroup)
        assert (form.agreements.min_values, form.agreements.max_values, form.agreements.required) == (2, 2, True)
        assert not any(option.default for option in form.agreements.options)
        # Nothing preselected for a plain /signup
        assert not any(option.default for option in form.kind.options)

    def test_permfa_preselects_permfa(self):
        form = AboutYouModal(_flow(SignupContext(command="permfa", kind=SignupKind.PERMFA)))
        assert form.title == "Sign up as a Permanent Free Agent"
        assert [option.value for option in form.kind.options if option.default] == [SignupKind.PERMFA]

    def test_returning_player_preselected(self):
        form = AboutYouModal(_flow(SignupContext(player_type=PlayerType.FORMER)))
        assert [option.value for option in form.played.options if option.default] == [PlayerType.FORMER]

    def test_labels_wrap_every_input(self):
        form = AboutYouModal(_flow())
        assert isinstance(form.children[0], TextDisplay)
        assert all(isinstance(item, Label) for item in form.children[1:])
        assert all(isinstance(item.component, CheckboxGroup | RadioGroup) for item in form.children[1:] if isinstance(item, Label))

    async def test_edit_reopens_filled_in(self):
        flow = await _flow_at_review()
        form = AboutYouModal(flow)
        assert form.title == "Edit your details"
        assert all(option.default for option in form.agreements.options)
        assert [option.value for option in form.region.options if option.default] == [RegionPreference.EAST]


class TestNameTrackersModal:
    def test_prefill_fills_name_and_trackers(self):
        form = NameTrackersModal(_flow(), SignupPrefill(rsc_name="Xentrick", trackers=(STEAM, EPIC)))
        assert len(form.children) == 5
        assert form.name_input.default == "Xentrick"
        assert form.links_input.default == f"{STEAM}\n{EPIC}"
        labels = [item for item in form.children if isinstance(item, Label)]
        assert labels[0].description == "From your RSC profile. Change it if you play under a new name."
        assert labels[-1].description == "These are the trackers on your RSC profile. Add any new accounts."
        # The referrer is the middle question
        assert isinstance(form.children[2], Label)
        assert form.children[2].component is form.referrer

    def test_no_prefill_leaves_fields_empty(self):
        form = NameTrackersModal(_flow(), SignupPrefill())
        assert form.name_input.default is None
        assert form.links_input.default is None

    async def test_answers_win_over_prefill(self):
        flow = await _flow_at_review(EPIC)
        form = NameTrackersModal(flow, SignupPrefill(rsc_name="Old Name", trackers=(STEAM,)))
        assert form.name_input.default == "Xentrick"
        assert form.links_input.default == EPIC
        assert [option.value for option in form.platform.options if option.default] == [Platform.EPIC]


class TestFixTrackersModal:
    async def test_only_the_tracker_field(self):
        flow = await _flow_at_review(f"{STEAM}\n{BAD}")
        form = FixTrackersModal(flow)
        assert len(form.children) == 2
        assert form.links_input.default == f"{STEAM}\n{BAD}"
        problem = form.children[0]
        assert isinstance(problem, TextDisplay)
        assert "Line 2 isn't a tracker profile link" in problem.content


class TestTrackerProblemText:
    async def test_one_bad_line(self):
        text = tracker_problem_text(await parse_tracker_links(f"{STEAM}\n{BAD}"))
        assert text.startswith("### ⚠️ Line 2 isn't a tracker profile link")
        assert "profile/epic/YourName/overview" in text

    async def test_several_bad_lines(self):
        steam_name = "https://rocketleague.tracker.network/rocket-league/profile/steam/xentrick"
        text = tracker_problem_text(await parse_tracker_links(f"{BAD}\n{steam_name}"))
        assert text.startswith("### ⚠️ 2 links need fixing")
        assert "Steam64ID" in text


class TestSignupFlow:
    async def test_start_opens_form_one(self):
        interaction = _interaction()
        await SignupFlowView(interaction, SignupContext()).start()
        interaction.response.send_modal.assert_awaited_once()
        assert isinstance(interaction.response.send_modal.await_args.args[0], AboutYouModal)

    async def test_form_one_posts_ephemeral_bridge(self):
        flow = _flow()
        interaction = _interaction()
        await flow.about_you_submitted(interaction, _fill_about_you(AboutYouModal(flow)))

        assert flow.stage is SignupStage.BRIDGE
        interaction.response.send_message.assert_awaited_once()
        assert interaction.response.send_message.await_args.kwargs["ephemeral"] is True
        assert "Step 1 of 2 done" in _text(flow)
        assert set(_buttons(flow)) == {"Continue to step 2", "Cancel"}
        assert flow.message_interaction is interaction

    async def test_form_two_turns_bridge_into_review(self):
        flow = await _flow_at_review()
        assert flow.stage is SignupStage.REVIEW
        assert flow.answers.ready
        assert flow.answers.tracker_urls == [STEAM, EPIC]
        buttons = _buttons(flow)
        assert not buttons["Submit sign-up"].disabled
        assert "Fix" not in buttons
        assert "Free Agent · New player · US East" in _text(flow)
        assert "heard about us from a friend" in _text(flow)

    async def test_review_fits_component_limit(self):
        flow = await _flow_at_review("\n".join([EPIC.replace("Xentrick", f"P{i}") for i in range(15)]))
        assert len(_components(flow)) <= 40
        assert "and 5 more" in _text(flow)

    async def test_bad_link_blocks_submit(self):
        flow = await _flow_at_review(f"{STEAM}\n{BAD}")
        buttons = _buttons(flow)
        assert buttons["Submit sign-up"].disabled
        assert "Fix" in buttons
        assert "1 of 2 needs fixing" in _text(flow)

        interaction = _interaction()
        await flow.open_fix(interaction)
        assert isinstance(interaction.response.send_modal.await_args.args[0], FixTrackersModal)

    async def test_fixing_trackers_keeps_other_answers(self):
        flow = await _flow_at_review(f"{STEAM}\n{BAD}")
        form = FixTrackersModal(flow)
        form.links_input._value = f"{STEAM}\n{EPIC}"
        await flow.trackers_fixed(_interaction(), form)
        assert flow.answers.ready
        assert flow.answers.rsc_name == "Xentrick"
        assert not _buttons(flow)["Submit sign-up"].disabled

    async def test_submit_hands_over_the_click(self):
        flow = await _flow_at_review()
        interaction = _interaction()
        await flow.submit(interaction)

        assert flow.outcome is SignupOutcome.SUBMITTED
        assert flow.submit_interaction is interaction
        assert flow.is_finished()
        assert all(button.disabled for button in _buttons(flow).values())
        assert "Submitting your sign-up" in _text(flow)

    async def test_submit_ignored_until_ready(self):
        flow = await _flow_at_review(BAD)
        await flow.submit(_interaction())
        assert flow.outcome is SignupOutcome.PENDING
        assert not flow.is_finished()

    async def test_cancel(self):
        flow = await _flow_at_review()
        interaction = _interaction()
        await flow.cancel(interaction)
        assert await flow.wait_for_outcome() is SignupOutcome.CANCELLED
        view = interaction.response.edit_message.await_args.kwargs["view"]
        assert "Sign-up cancelled" in _text(view)

    async def test_closed_form_one_times_out(self):
        flow = _flow()
        await flow.form_timed_out()
        assert await flow.wait_for_outcome() is SignupOutcome.TIMED_OUT

    async def test_closed_later_form_does_not_end_sign_up(self):
        flow = await _flow_at_review()
        await flow.form_timed_out()
        assert flow.outcome is SignupOutcome.PENDING
        assert not flow.is_finished()

    async def test_view_timeout_shows_message(self):
        flow = await _flow_at_review()
        latest = _interaction()
        flow.message_interaction = latest
        await flow.on_timeout()
        assert flow.outcome is SignupOutcome.TIMED_OUT
        view = latest.edit_original_response.await_args.kwargs["view"]
        assert "timed out" in _text(view)

    async def test_slow_prefill_does_not_hold_up_form_two(self):
        flow = _flow()
        flow.prefill = asyncio.ensure_future(asyncio.sleep(5, result=SignupPrefill(rsc_name="late")))
        with patch.object(signup_module, "PREFILL_WAIT", 0.01):
            assert await flow.prefill_result() == SignupPrefill()
        flow.prefill.cancel()

    async def test_ready_prefill_is_used(self):
        flow = _flow()
        flow.prefill = asyncio.ensure_future(asyncio.sleep(0, result=SignupPrefill(rsc_name="Xentrick")))
        interaction = _interaction()
        await flow.open_name_trackers(interaction)
        form = interaction.response.send_modal.await_args.args[0]
        assert form.name_input.default == "Xentrick"


class TestEndings:
    async def test_banner_text_signup(self):
        flow = await _flow_at_review(context=SignupContext(season_number=24))
        text = banner_text(flow.answers, flow.context)
        assert (text.kicker, text.headline, text.permfa) == ("RSC · SEASON 24", "YOU'RE IN", False)
        assert text.chips == ["New player", "US East", "EPIC"]

    async def test_banner_text_permfa(self):
        flow = _flow()
        await flow.about_you_submitted(_interaction(), _fill_about_you(AboutYouModal(flow), kind=SignupKind.PERMFA))
        text = banner_text(flow.answers, SignupContext(season_number=24))
        assert (text.kicker, text.headline, text.permfa) == ("RSC · PERMFA SIGN-UP", "REQUEST SENT", True)
        assert text.chips[0] == "PermFA"

    async def test_success_with_banner_and_note(self):
        flow = await _flow_at_review(context=SignupContext(season_number=24))
        view = SignupSuccessView(flow.answers, flow.context, banner=True, nickname_too_long=True)
        assert any(isinstance(item, MediaGallery) for item in view.walk_children())
        assert "You're signed up for Season 24" in _text(view)
        assert "too long for Discord" in _text(view)

    async def test_success_without_banner(self):
        flow = await _flow_at_review()
        view = SignupSuccessView(flow.answers, flow.context, banner=False)
        assert not any(isinstance(item, MediaGallery) for item in view.walk_children())

    def test_already_signed_up_buttons(self):
        view = AlreadySignedUpView(AlreadySignedUp.SIGNUP, on_status=AsyncMock(), on_intent=AsyncMock())
        assert set(_buttons(view)) == {"My status", "Declare intent"}

    def test_waiting_permfa_has_no_intent_button(self):
        view = AlreadySignedUpView(AlreadySignedUp.PERMFA_WAITING, on_status=AsyncMock())
        assert set(_buttons(view)) == {"My status"}
        assert "waiting on staff" in _text(view)

    async def test_timeout_drops_buttons(self):
        interaction = _interaction()
        view = AlreadySignedUpView(AlreadySignedUp.PERMFA, interaction=interaction, on_status=AsyncMock())
        await view.on_timeout()
        assert not _buttons(view)
        assert not any(isinstance(item, Section) for item in view.walk_children())
        interaction.edit_original_response.assert_awaited_once()

    def test_container_layout(self):
        view = AlreadySignedUpView(AlreadySignedUp.PERMFA)
        assert isinstance(view.children[0], Container)
        assert not any(isinstance(item, ActionRow) for item in view.walk_children())
