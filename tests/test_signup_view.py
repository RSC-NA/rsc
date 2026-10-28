from unittest.mock import AsyncMock, MagicMock

import discord
import pytest
from discord.ui import ActionRow, Container, TextDisplay

from rsc.members.views.signup import (
    AgreementPhase,
    PermFAAgreementPhase,
    PermFASignupView,
    PlayerInfoModal,
    SelectPhase,
    SignupState,
    SignupView,
)

GUILD_ID = 395806681994493964


def _interaction():
    interaction = MagicMock(spec=discord.Interaction)
    interaction.user = MagicMock(spec=discord.Member)
    interaction.guild = MagicMock(spec=discord.Guild)
    interaction.guild.id = GUILD_ID
    interaction.response = MagicMock()
    interaction.response.edit_message = AsyncMock()
    interaction.response.send_modal = AsyncMock()
    interaction.edit_original_response = AsyncMock()
    return interaction


async def _view_at_trackers(interaction) -> SignupView:
    """A signup view that has finished every select, with its modal still open."""
    view = SignupView(interaction)
    for step in (SignupState.TIMES, SignupState.RULES):
        await view.complete_step(interaction, step)
    assert view._selects is not None
    for step in (SignupState.PLAYER_TYPE, SignupState.REGION, SignupState.PLATFORM):
        view._selects.complete_step(step)
    view.state = view._selects.complete_step(SignupState.REFERRER)
    return view


def _modal(*, timed_out: bool, submitted: bool, name: str = "Xentrick", links: str = "a\nb") -> PlayerInfoModal:
    modal = PlayerInfoModal()
    modal.wait = AsyncMock(return_value=timed_out)
    modal.submitted = submitted
    modal.name_input._value = name
    modal.links_input._value = links
    return modal


def _text(container: Container) -> str:
    return "\n".join(c.content for c in container.children if isinstance(c, TextDisplay))


def _buttons(container: Container) -> list[discord.ui.Item]:
    return [item for row in container.children if isinstance(row, ActionRow) for item in row.children]


class TestSignupView:
    async def test_starts_at_game_times(self):
        view = SignupView(_interaction())
        phase = view._agreement

        assert type(phase) is AgreementPhase
        assert view.state == SignupState.TIMES
        assert phase.containers == [phase.times_container, phase.rules_container]
        assert not phase.times_btn.disabled
        assert phase.cancel_btn in _buttons(phase.times_container)

    async def test_rejects_permfa_step(self):
        view = SignupView(_interaction())
        with pytest.raises(ValueError):
            view._agreement.complete_step(SignupState.PERMFA)


class TestPermFASignupView:
    async def test_starts_at_permfa_acknowledgement(self):
        view = PermFASignupView(_interaction())
        phase = view._agreement

        assert isinstance(phase, PermFAAgreementPhase)
        assert view.state == SignupState.PERMFA
        assert phase.containers == [phase.permfa_container, phase.times_container, phase.rules_container]
        assert "Permanent Free Agent" in _text(phase.permfa_container)
        assert "/signup" in _text(phase.permfa_container)

    async def test_game_times_locked_until_acknowledged(self):
        view = PermFASignupView(_interaction())
        phase = view._agreement
        assert isinstance(phase, PermFAAgreementPhase)

        assert phase.times_btn.disabled
        assert not phase.permfa_btn.disabled
        assert phase.cancel_btn in _buttons(phase.permfa_container)
        assert phase.cancel_btn not in _buttons(phase.times_container)

    async def test_acknowledging_unlocks_game_times(self):
        interaction = _interaction()
        view = PermFASignupView(interaction)
        phase = view._agreement
        assert isinstance(phase, PermFAAgreementPhase)

        await view.complete_step(interaction, SignupState.PERMFA)

        assert view.state == SignupState.TIMES
        assert phase.permfa_btn.disabled
        assert phase.cancel_btn.disabled
        assert not phase.times_btn.disabled
        interaction.response.edit_message.assert_awaited_once_with(view=view)

    async def test_agreement_leads_to_player_info(self):
        interaction = _interaction()
        view = PermFASignupView(interaction)

        for step in (SignupState.PERMFA, SignupState.TIMES, SignupState.RULES):
            await view.complete_step(interaction, step)

        assert view.state == SignupState.PLAYER_TYPE
        assert isinstance(view._selects, SelectPhase)


class TestPlayerInfoModal:
    async def test_info_button_locked_until_referrer(self):
        phase = SelectPhase()
        assert phase.info_btn.disabled
        assert phase.info_btn in _buttons(phase.referrer_container)

        for step in (SignupState.PLAYER_TYPE, SignupState.REGION, SignupState.PLATFORM):
            phase.complete_step(step)
        assert phase.complete_step(SignupState.REFERRER) == SignupState.TRACKERS
        assert not phase.info_btn.disabled

    async def test_referrer_opens_modal_and_shows_reopen_button(self):
        interaction = _interaction()
        view = SignupView(interaction)
        for step in (SignupState.TIMES, SignupState.RULES, SignupState.PLAYER_TYPE, SignupState.REGION, SignupState.PLATFORM):
            await view.complete_step(interaction, step)

        view.collect_player_info = AsyncMock()
        await view.complete_step(interaction, SignupState.REFERRER)

        modal = interaction.response.send_modal.await_args.args[0]
        assert isinstance(modal, PlayerInfoModal)
        # A dismissed modal must not be waited on forever
        assert modal.timeout == view.timeout
        interaction.edit_original_response.assert_awaited_once_with(view=view)
        assert view._selects is not None
        assert not view._selects.info_btn.disabled

    async def test_dismissed_modal_leaves_signup_open(self):
        interaction = _interaction()
        view = await _view_at_trackers(interaction)

        await view.collect_player_info(_modal(timed_out=True, submitted=False))

        assert view.state == SignupState.TRACKERS
        assert not view.is_finished()
        assert view._selects is not None
        assert not view._selects.info_btn.disabled
        interaction.edit_original_response.assert_not_awaited()

    async def test_submitted_modal_finishes_signup(self):
        interaction = _interaction()
        view = await _view_at_trackers(interaction)

        await view.collect_player_info(_modal(timed_out=False, submitted=True, links="https://a\nhttps://b"))

        assert view.state == SignupState.FINISHED
        assert view.is_finished()
        assert view.rsc_name == "Xentrick"
        assert view.trackers == ["https://a", "https://b"]
        assert view._selects is not None
        assert view._selects.info_btn.disabled
        interaction.edit_original_response.assert_awaited_once_with(view=view)

    async def test_only_first_submission_counts(self):
        interaction = _interaction()
        view = await _view_at_trackers(interaction)

        await view.collect_player_info(_modal(timed_out=False, submitted=True, name="First"))
        await view.collect_player_info(_modal(timed_out=False, submitted=True, name="Second"))

        assert view.rsc_name == "First"
        interaction.edit_original_response.assert_awaited_once()
