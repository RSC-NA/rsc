import asyncio
from datetime import datetime
from unittest.mock import AsyncMock, MagicMock, patch

import discord
from discord.ui import ActionRow, Container, Label, MediaGallery, Section, Separator, TextDisplay, TextInput

from rsc.const import BEHAVIOR_RULES_URL, MODAL_TIMEOUT
from rsc.enums import Platform, PlayerType, Referrer, RegionPreference
from rsc.members.tracker_links import parse_tracker_links
from rsc.members.views import signup as signup_module
from rsc.members.views.signup import (
    FLOW_COLOUR,
    MATCH_NIGHTS_2V2,
    MATCH_NIGHTS_3V3,
    PERMFA_COLOUR,
    READY_COLOUR,
    AlreadySignedUp,
    AlreadySignedUpView,
    FixTrackersModal,
    NameTrackersModal,
    SignupAnswers,
    SignupContext,
    signup_cancelled_view,
    signup_timed_out_view,
    SignupFlowView,
    SignupKind,
    SignupOutcome,
    SignupPrefill,
    SignupStage,
    SignupSuccessView,
    banner_text,
    joined,
    tracker_problem_text,
)

STEAM = "https://rocketleague.tracker.network/rocket-league/profile/steam/76561197960409023/overview"
EPIC = "https://rocketleague.tracker.network/rocket-league/profile/epic/Xentrick/overview"
BAD = "https://rocketleague.tracker.network/rocket-league/"
EASTERN = signup_module._EASTERN
PERMFA = SignupContext(command="permfa", kind=SignupKind.PERMFA)


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


def _selects(view: discord.ui.LayoutView) -> dict[str, discord.ui.Select]:
    return {item.placeholder or "": item for item in view.walk_children() if isinstance(item, discord.ui.Select)}


def _picked(select: discord.ui.Select) -> list[str]:
    return [option.value for option in select.options if option.default]


def _text(view: discord.ui.LayoutView) -> str:
    return "\n".join(item.content for item in view.walk_children() if isinstance(item, TextDisplay))


def _card(view: discord.ui.LayoutView) -> Container:
    card = view.children[0]
    assert isinstance(card, Container)
    return card


def _footer(view: discord.ui.LayoutView) -> str:
    """The line above Continue"""
    texts = [item for item in _card(view).children if isinstance(item, TextDisplay)]
    return texts[-1].content


async def _flow_at_about(context: SignupContext | None = None) -> SignupFlowView:
    flow = _flow(context)
    await flow.start()
    await flow.toggle_nights(_interaction())
    await flow.toggle_rules(_interaction())
    await flow.to_about(_interaction())
    return flow


async def _answer_about(
    flow: SignupFlowView,
    kind=SignupKind.FREE_AGENT,
    played=PlayerType.NEW,
    region=RegionPreference.EAST,
    platform=Platform.EPIC,
    referrer=Referrer.FRIEND,
) -> SignupFlowView:
    for choice in (kind, played, region, platform, referrer):
        await flow.choose(_interaction(), choice)
    return flow


async def _open_form(flow: SignupFlowView) -> NameTrackersModal:
    interaction = _interaction()
    await flow.to_form(interaction)
    interaction.response.send_modal.assert_awaited_once()
    form = interaction.response.send_modal.await_args.args[0]
    assert isinstance(form, NameTrackersModal)
    return form


def _fill_name_trackers(form: NameTrackersModal, links: str, name="Xentrick") -> NameTrackersModal:
    form.name_input._value = name
    form.links_input._value = links
    return form


async def _flow_at_review(
    links: str = f"{STEAM}\n{EPIC}", context: SignupContext | None = None, kind=SignupKind.FREE_AGENT
) -> SignupFlowView:
    flow = await _answer_about(await _flow_at_about(context), kind=kind)
    form = await _open_form(flow)
    await flow.name_trackers_submitted(_interaction(), _fill_name_trackers(form, links))
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


class TestAnswers:
    def test_joined(self):
        assert joined(["region"]) == "region"
        assert joined(["a", "b"]) == "a and b"
        assert joined(["a", "b", "c"]) == "a, b and c"

    def test_pick_sets_the_matching_answer(self):
        answers = SignupAnswers()
        for choice in (SignupKind.PERMFA, PlayerType.FORMER, RegionPreference.EU, Platform.XBOX, Referrer.MLE):
            answers.pick(choice)
        assert (answers.kind, answers.player_type, answers.region, answers.platform, answers.referrer) == (
            SignupKind.PERMFA,
            PlayerType.FORMER,
            RegionPreference.EU,
            Platform.XBOX,
            Referrer.MLE,
        )
        assert answers.missing_choices == []

    async def test_not_ready_without_confirmations(self):
        flow = await _flow_at_review()
        assert flow.answers.ready
        flow.answers.rules_accepted = False
        assert not flow.answers.ready


class TestGate:
    async def test_start_posts_step_one(self):
        interaction = _interaction()
        flow = SignupFlowView(interaction, SignupContext())
        await flow.start()

        interaction.response.send_modal.assert_not_awaited()
        interaction.response.send_message.assert_awaited_once()
        assert interaction.response.send_message.await_args.kwargs["ephemeral"] is True
        assert flow.message_interaction is interaction
        assert flow.stage is SignupStage.GATE

        text = _text(flow)
        assert "RSC SIGN-UP · STEP 1 OF 3\n## Before you start" in text
        assert "**Monday and Wednesday at 10 PM ET**" in text
        # No "next one" timestamp; just the nights and time
        assert "Your next one" not in text
        assert BEHAVIOR_RULES_URL in text
        assert "Subs play on these nights too." not in text
        assert _footer(flow) == "-# Confirm both to continue."
        assert _card(flow).accent_colour == FLOW_COLOUR

        buttons = _buttons(flow)
        assert set(buttons) == {"I can play on match nights", "I agree to the rules", "Continue", "Cancel"}
        assert buttons["I can play on match nights"].style is discord.ButtonStyle.secondary
        assert buttons["I agree to the rules"].style is discord.ButtonStyle.secondary
        assert buttons["Continue"].disabled
        assert buttons["Continue"].style is discord.ButtonStyle.primary
        assert len(_components(flow)) <= 40

    async def test_confirm_turns_green_and_relabels(self):
        flow = _flow()
        await flow.start()
        interaction = _interaction()
        await flow.toggle_nights(interaction)

        interaction.response.edit_message.assert_awaited_once_with(view=flow)
        assert flow.message_interaction is interaction
        buttons = _buttons(flow)
        assert "I can play on match nights" not in buttons
        assert buttons["Match nights confirmed"].style is discord.ButtonStyle.success
        assert buttons["Continue"].disabled
        assert _footer(flow) == "-# Still to confirm: the rules."

    async def test_both_confirmed_enables_continue(self):
        flow = _flow()
        await flow.start()
        await flow.toggle_nights(_interaction())
        await flow.toggle_rules(_interaction())

        buttons = _buttons(flow)
        assert buttons["Rules accepted"].style is discord.ButtonStyle.success
        assert not buttons["Continue"].disabled
        assert _card(flow).accent_colour == READY_COLOUR
        assert _footer(flow) == "-# Next: a few questions about how you play."

    async def test_confirm_toggles_back_off(self):
        flow = _flow()
        await flow.start()
        await flow.toggle_rules(_interaction())
        await flow.toggle_nights(_interaction())
        await flow.toggle_rules(_interaction())

        buttons = _buttons(flow)
        assert buttons["I agree to the rules"].style is discord.ButtonStyle.secondary
        assert buttons["Continue"].disabled
        assert not flow.answers.rules_accepted

    async def test_confirm_can_be_locked_on(self):
        flow = _flow()
        await flow.start()
        with patch.object(signup_module, "CONFIRMS_CAN_UNDO", False):
            await flow.toggle_rules(_interaction())
            await flow.toggle_rules(_interaction())
        assert flow.answers.rules_accepted
        assert "Rules accepted" in _buttons(flow)

    async def test_continue_ignored_until_both_confirmed(self):
        flow = _flow()
        await flow.start()
        await flow.toggle_nights(_interaction())
        await flow.to_about(_interaction())
        assert flow.stage is SignupStage.GATE

    async def test_continue_edits_the_same_message_into_step_two(self):
        flow = _flow()
        await flow.start()
        await flow.toggle_nights(_interaction())
        await flow.toggle_rules(_interaction())
        interaction = _interaction()
        await flow.to_about(interaction)

        assert flow.stage is SignupStage.ABOUT
        interaction.response.edit_message.assert_awaited_once_with(view=flow)
        interaction.response.send_modal.assert_not_awaited()
        assert "STEP 2 OF 3\n## About you" in _text(flow)

    async def test_buttons_answer_through_their_callbacks(self):
        flow = _flow()
        await flow.start()
        interaction = _interaction()
        await _buttons(flow)["I can play on match nights"].callback(interaction)
        assert flow.answers.nights_confirmed
        interaction.response.edit_message.assert_awaited_once()

    async def test_permfa_gate(self):
        flow = _flow(PERMFA)
        await flow.start()
        text = _text(flow)
        assert "RSC PERMFA SIGN-UP · STEP 1 OF 3" in text
        assert "Your next one" not in text
        assert text.count("Subs play on these nights too.") == 1
        assert _card(flow).accent_colour == PERMFA_COLOUR

    async def test_2v2_gate_shows_thursday(self):
        flow = _flow(SignupContext(is_2v2=True))
        await flow.start()
        assert "**Thursday at 10 PM ET**" in _text(flow)


class TestAboutYou:
    async def test_nothing_answered(self):
        flow = await _flow_at_about()
        buttons = _buttons(flow)
        for label in ("Draft eligible", "Permanent Free Agent", "No, first season", "Yes, I've played", "US East", "US West", "Europe"):
            assert buttons[label].style is discord.ButtonStyle.secondary
        assert buttons["Continue"].disabled
        assert _footer(flow) == "-# Answer each question to continue."
        assert _card(flow).accent_colour == FLOW_COLOUR

        selects = _selects(flow)
        assert set(selects) == {"Choose your platform", "Choose one"}
        assert [o.label for o in selects["Choose your platform"].options] == [p.label for p in Platform]
        assert [o.label for o in selects["Choose one"].options] == [r.label for r in Referrer]
        assert not any(_picked(select) for select in selects.values())
        assert len(_components(flow)) <= 40

    async def test_a_line_between_every_question(self):
        flow = await _flow_at_about()
        children = _card(flow).children
        questions = {
            i: item.content
            for i, item in enumerate(children)
            if isinstance(item, TextDisplay) and "**" in item.content and "##" not in item.content
        }
        assert len(questions) == 5
        assert all(isinstance(children[i - 1], Separator) for i in questions)
        texts = list(questions.values())
        assert texts[0].startswith("-# HOW YOU PLAY\n**How do you want to play?**")
        assert texts[3].startswith("-# YOUR SETUP\n**Main platform**")
        # The footer sits under a line too, above the Continue/Cancel row and the Back row
        assert isinstance(children[-4], Separator)

    async def test_picked_answer_turns_blurple(self):
        flow = await _flow_at_about()
        interaction = _interaction()
        await _buttons(flow)["Draft eligible"].callback(interaction)

        interaction.response.edit_message.assert_awaited_once_with(view=flow)
        assert flow.answers.kind is SignupKind.FREE_AGENT
        buttons = _buttons(flow)
        assert buttons["Draft eligible"].style is discord.ButtonStyle.primary
        assert buttons["Permanent Free Agent"].style is discord.ButtonStyle.secondary

        await flow.choose(_interaction(), SignupKind.PERMFA)
        buttons = _buttons(flow)
        assert buttons["Draft eligible"].style is discord.ButtonStyle.secondary
        assert buttons["Permanent Free Agent"].style is discord.ButtonStyle.primary
        assert _card(flow).accent_colour == PERMFA_COLOUR
        assert "RSC PERMFA SIGN-UP · STEP 2 OF 3" in _text(flow)

    async def test_select_pick_is_the_default_when_redrawn(self):
        flow = await _flow_at_about()
        select = _selects(flow)["Choose your platform"]
        select._values = [Platform.STEAM.value]
        await select.callback(_interaction())

        assert flow.answers.platform is Platform.STEAM
        # The redraw builds new selects, with the pick as their default
        redrawn = _selects(flow)["Choose your platform"]
        assert redrawn is not select
        assert _picked(redrawn) == [Platform.STEAM.value]

        await flow.choose(_interaction(), Referrer.TWITCH)
        selects = _selects(flow)
        assert _picked(selects["Choose your platform"]) == [Platform.STEAM.value]
        assert _picked(selects["Choose one"]) == [Referrer.TWITCH.value]

    async def test_footer_names_what_is_missing(self):
        flow = await _flow_at_about()
        for choice in (SignupKind.FREE_AGENT, PlayerType.NEW, Platform.STEAM):
            await flow.choose(_interaction(), choice)
        assert _footer(flow) == "-# Still to answer: region and how you heard about RSC."
        assert _buttons(flow)["Continue"].disabled

    async def test_all_answered_enables_continue(self):
        flow = await _answer_about(await _flow_at_about())
        assert not _buttons(flow)["Continue"].disabled
        assert _card(flow).accent_colour == READY_COLOUR
        assert _footer(flow) == "-# All set. Next: your in-game name and trackers."

    async def test_continue_ignored_until_answered(self):
        flow = await _flow_at_about()
        await flow.choose(_interaction(), SignupKind.FREE_AGENT)
        interaction = _interaction()
        await flow.to_form(interaction)
        interaction.response.send_modal.assert_not_awaited()
        interaction.response.edit_message.assert_awaited_once()

    async def test_returning_player_preselected(self):
        flow = await _flow_at_about(SignupContext(player_type=PlayerType.FORMER))
        assert _buttons(flow)["Yes, I've played"].style is discord.ButtonStyle.primary

    async def test_permfa_preselects_permfa(self):
        flow = await _flow_at_about(PERMFA)
        buttons = _buttons(flow)
        assert buttons["Permanent Free Agent"].style is discord.ButtonStyle.primary
        assert buttons["Draft eligible"].style is discord.ButtonStyle.secondary
        assert _card(flow).accent_colour == PERMFA_COLOUR
        assert _footer(flow) == "-# Still to answer: played before, region, platform and how you heard about RSC."

    async def test_permfa_can_switch_to_free_agent(self):
        flow = await _flow_at_about(PERMFA)
        await flow.choose(_interaction(), SignupKind.FREE_AGENT)
        assert flow.answers.kind is SignupKind.FREE_AGENT
        assert "RSC SIGN-UP · STEP 2 OF 3" in _text(flow)
        assert _card(flow).accent_colour == FLOW_COLOUR

    async def test_permfa_can_skip_the_kind_question(self):
        with patch.object(signup_module, "PERMFA_ASKS_KIND", False):
            flow = await _flow_at_about(PERMFA)
            assert "Draft eligible" not in _buttons(flow)
            assert "-# HOW YOU PLAY\n**Have you played in RSC before?**" in _text(flow)
            await _answer_about(flow, kind=SignupKind.PERMFA)
            assert not _buttons(flow)["Continue"].disabled


class TestNameTrackersModal:
    async def test_continue_opens_one_form(self):
        flow = await _answer_about(await _flow_at_about())
        form = await _open_form(flow)

        assert form.title == "Step 3 of 3: Name & trackers"
        assert form.timeout == MODAL_TIMEOUT
        assert [type(item) for item in form.children] == [Label, TextDisplay, Label]
        name, links = form.children[0], form.children[2]
        assert isinstance(name, Label) and isinstance(links, Label)
        assert name.component is form.name_input
        assert name.description == "Must match your in-game name on your tracker link."
        assert links.component is form.links_input
        assert isinstance(form.name_input, TextInput)
        assert form.links_input.style is discord.TextStyle.paragraph
        help_text = form.children[1]
        assert isinstance(help_text, TextDisplay)
        assert "One account needs at least 50 3v3 games." in help_text.content

    def test_prefill_fills_name_and_trackers(self):
        form = NameTrackersModal(_flow(), SignupPrefill(rsc_name="Xentrick", trackers=(STEAM, EPIC)))
        assert form.name_input.default == "Xentrick"
        assert form.links_input.default == f"{STEAM}\n{EPIC}"
        labels = [item for item in form.children if isinstance(item, Label)]
        assert labels[0].description == "From your RSC profile. Must match your in-game name on your tracker link."
        assert labels[-1].description == "These are the trackers on your RSC profile. Add any new accounts."

    def test_no_prefill_leaves_fields_empty(self):
        form = NameTrackersModal(_flow(), SignupPrefill())
        assert form.name_input.default is None
        assert form.links_input.default is None

    async def test_ready_prefill_is_used(self):
        flow = await _answer_about(await _flow_at_about())
        flow.prefill = asyncio.ensure_future(asyncio.sleep(0, result=SignupPrefill(rsc_name="Xentrick", trackers=(EPIC,))))
        form = await _open_form(flow)
        assert form.name_input.default == "Xentrick"
        assert form.links_input.default == EPIC

    async def test_slow_prefill_does_not_hold_up_the_form(self):
        flow = await _answer_about(await _flow_at_about())
        flow.prefill = asyncio.ensure_future(asyncio.sleep(5, result=SignupPrefill(rsc_name="late")))
        with patch.object(signup_module, "PREFILL_WAIT", 0.01):
            form = await asyncio.wait_for(_open_form(flow), 1)
        assert form.name_input.default is None
        # The lookup keeps going, since it also creates the RSC member
        assert not flow.prefill.cancelled()
        flow.prefill.cancel()

    async def test_failed_prefill_opens_an_empty_form(self):
        async def broken() -> SignupPrefill:
            raise RuntimeError("lookup failed")

        flow = _flow()
        flow.prefill = asyncio.ensure_future(broken())
        assert await flow.prefill_result() == SignupPrefill()

    async def test_answers_win_over_prefill(self):
        flow = await _flow_at_review(EPIC)
        form = NameTrackersModal(flow, SignupPrefill(rsc_name="Old Name", trackers=(STEAM,)))
        assert form.title == "Name & trackers"
        assert form.name_input.default == "Xentrick"
        assert form.links_input.default == EPIC
        labels = [item for item in form.children if isinstance(item, Label)]
        assert labels[0].description == "Must match your in-game name on your tracker link."


class TestFixTrackersModal:
    async def test_only_the_tracker_field(self):
        flow = await _flow_at_review(f"{STEAM}\n{BAD}")
        form = FixTrackersModal(flow)
        # What's wrong and how to fix it are separate blocks, so the form isn't one crowded paragraph
        problem, fix, field = form.children
        assert form.links_input.default == f"{STEAM}\n{BAD}"
        assert isinstance(problem, TextDisplay) and isinstance(fix, TextDisplay)
        assert problem.content == f"### Line 2 isn't a tracker profile link\n-# YOU ENTERED\n`{BAD}`"
        assert fix.content.startswith("-# HOW TO FIX IT\nOpen your profile on the tracker site")
        assert isinstance(field, Label)


class TestTrackerProblemText:
    async def test_one_bad_line(self):
        text = tracker_problem_text(await parse_tracker_links(f"{STEAM}\n{BAD}"))
        assert text.startswith("### Line 2 isn't a tracker profile link")
        assert "profile/epic/YourName/overview" in text

    async def test_several_bad_lines(self):
        steam_name = "https://rocketleague.tracker.network/rocket-league/profile/steam/xentrick"
        text = tracker_problem_text(await parse_tracker_links(f"{BAD}\n{steam_name}"))
        assert text.startswith("### 2 links need fixing")
        assert "Steam64ID" in text


class TestSignupFlow:
    async def test_form_turns_the_message_into_review(self):
        flow = await _answer_about(await _flow_at_about())
        form = _fill_name_trackers(await _open_form(flow), f"{STEAM}\n{EPIC}")
        interaction = _interaction()
        await flow.name_trackers_submitted(interaction, form)

        interaction.response.edit_message.assert_awaited_once_with(view=flow)
        assert flow.message_interaction is interaction
        assert flow.stage is SignupStage.REVIEW
        assert flow.answers.ready
        assert flow.answers.tracker_urls == [STEAM, EPIC]
        buttons = _buttons(flow)
        assert not buttons["Submit sign-up"].disabled
        assert "Fix" not in buttons

    async def test_review_lists_step_two_under_about_you(self):
        flow = await _flow_at_review()
        text = _text(flow)
        # How they're signing up stands out as a heading, then one fact per line
        assert "### Signing up as Draft eligible\n-# You enter the draft, and a team can draft you onto its roster for the season." in text
        assert "**Experience:** New player\n**Region:** US East\n**Platform:** Epic Games\n**Heard about us:** A friend" in text
        assert "**Xentrick**\n**Trackers** · 2 accounts" in _text(flow)

    async def test_about_you_edit_goes_back_to_step_two(self):
        flow = await _flow_at_review()
        sections = [item for item in _card(flow).children if isinstance(item, Section)]
        edit = sections[0].accessory
        assert isinstance(edit, discord.ui.Button)
        await edit.callback(_interaction())

        assert flow.stage is SignupStage.ABOUT
        assert _buttons(flow)["Draft eligible"].style is discord.ButtonStyle.primary
        assert _picked(_selects(flow)["Choose your platform"]) == [Platform.EPIC.value]
        assert _footer(flow) == "-# All set. Next: check your details."

        # The form is already filled in, so Continue goes straight back to the review
        await flow.choose(_interaction(), RegionPreference.WEST)
        interaction = _interaction()
        await flow.to_form(interaction)
        interaction.response.send_modal.assert_not_awaited()
        assert flow.stage is SignupStage.REVIEW
        assert "**Region:** US West" in _text(flow)

    async def test_back_from_step_two_keeps_every_answer(self):
        flow = await _flow_at_about()
        await _answer_about(flow)
        # Back sits on its own row, under Continue and a red Cancel
        assert list(_buttons(flow))[-3:] == ["Continue", "Cancel", "Back"]
        assert _buttons(flow)["Cancel"].style is discord.ButtonStyle.danger

        await _buttons(flow)["Back"].callback(_interaction())
        assert flow.stage is SignupStage.GATE
        # Step 1 has nowhere to go back to
        assert "Back" not in _buttons(flow)
        assert _buttons(flow)["Match nights confirmed"].style is discord.ButtonStyle.success

        await _buttons(flow)["Continue"].callback(_interaction())
        assert flow.stage is SignupStage.ABOUT
        assert _buttons(flow)["Draft eligible"].style is discord.ButtonStyle.primary

    async def test_back_from_the_review_returns_to_step_two(self):
        flow = await _flow_at_review()
        assert list(_buttons(flow))[-3:] == ["Submit sign-up", "Cancel", "Back"]
        assert _buttons(flow)["Cancel"].style is discord.ButtonStyle.danger
        await _buttons(flow)["Back"].callback(_interaction())
        assert flow.stage is SignupStage.ABOUT

    async def test_tracker_edit_reopens_the_form_filled_in(self):
        flow = await _flow_at_review()
        interaction = _interaction()
        await flow.open_name_trackers(interaction)
        form = interaction.response.send_modal.await_args.args[0]
        assert isinstance(form, NameTrackersModal)
        assert form.links_input.default == f"{STEAM}\n{EPIC}"

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

    async def test_valid_trackers_can_skip_the_review(self):
        flow = await _answer_about(await _flow_at_about())
        form = _fill_name_trackers(await _open_form(flow), EPIC)
        interaction = _interaction()
        with patch.object(signup_module, "SKIP_REVIEW_WHEN_VALID", True):
            await flow.name_trackers_submitted(interaction, form)
        assert flow.outcome is SignupOutcome.SUBMITTED
        assert flow.submit_interaction is interaction

    async def test_cancel_on_step_one(self):
        flow = _flow()
        await flow.start()
        interaction = _interaction()
        await _buttons(flow)["Cancel"].callback(interaction)
        assert await flow.wait_for_outcome() is SignupOutcome.CANCELLED
        view = interaction.response.edit_message.await_args.kwargs["view"]
        assert "Sign-up cancelled" in _text(view)

    async def test_cancel_on_review(self):
        flow = await _flow_at_review()
        interaction = _interaction()
        await flow.cancel(interaction)
        assert await flow.wait_for_outcome() is SignupOutcome.CANCELLED

    async def test_closing_the_form_leaves_step_two(self):
        flow = await _answer_about(await _flow_at_about())
        form = await _open_form(flow)
        await form.on_timeout()
        assert flow.stage is SignupStage.ABOUT
        assert flow.outcome is SignupOutcome.PENDING
        assert not flow.is_finished()

    async def test_view_timeout_shows_message(self):
        flow = await _flow_at_about()
        latest = _interaction()
        flow.message_interaction = latest
        await flow.on_timeout()
        assert flow.outcome is SignupOutcome.TIMED_OUT
        view = latest.edit_original_response.await_args.kwargs["view"]
        assert "timed out" in _text(view)

    def test_timeout_stays_inside_the_token_life(self):
        timeout = _flow().timeout
        assert timeout is not None
        assert MODAL_TIMEOUT < timeout < 15 * 60


class TestEndings:
    async def test_banner_text_signup(self):
        flow = await _flow_at_review(context=SignupContext(season_number=24))
        text = banner_text(flow.answers, flow.context)
        assert (text.kicker, text.headline, text.permfa) == ("RSC · SEASON 24", "YOU'RE IN", False)
        assert text.chips == ["New player", "US East", "EPIC"]

    async def test_banner_text_permfa(self):
        flow = await _flow_at_review(context=PERMFA, kind=SignupKind.PERMFA)
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


class TestReviewDetails:
    async def test_bad_tracker_shows_its_whole_link_and_line_number(self):
        long_bad = BAD + "not-a-profile/" + "x" * 80
        flow = await _flow_at_review(f"{STEAM}\n{long_bad}")
        text = _text(flow)
        # Nothing cut off, so the player can tell which link to fix
        assert long_bad in text
        assert "**Line 2 needs fixing:**" in text

    async def test_fix_form_lists_every_bad_link_in_full(self):
        long_bad = BAD + "y" * 90
        text = tracker_problem_text(await parse_tracker_links(f"{long_bad}\n{BAD}"))
        assert long_bad in text and "…" not in text

    async def test_confirmations_each_on_their_own_line(self):
        footer = _footer(await _flow_at_review())
        nights, rules = footer.split("\n")
        assert nights.startswith("-# Match nights confirmed: ")
        assert rules == "-# Rules accepted"

    async def test_permfa_heading(self):
        flow = await _flow_at_review(kind=SignupKind.PERMFA)
        assert "### Signing up as Permanent Free Agent\n-# You skip the draft" in _text(flow)


class TestEndingColours:
    def test_cancelled_is_red_and_timed_out_is_yellow(self):
        context = SignupContext()
        cancelled = signup_cancelled_view(context).children[0]
        timed_out = signup_timed_out_view(context).children[0]
        assert isinstance(cancelled, Container) and isinstance(timed_out, Container)
        assert cancelled.accent_colour == discord.Colour.red()
        assert timed_out.accent_colour == discord.Colour.yellow()
