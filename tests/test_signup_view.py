from unittest.mock import AsyncMock, MagicMock

import discord
import pytest
from discord.ui import ActionRow, Container, TextDisplay

from rsc.members.views.signup import (
    AgreementPhase,
    PermFAAgreementPhase,
    PermFASignupView,
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
    return interaction


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

        assert phase.times_btn.disabled
        assert not phase.permfa_btn.disabled
        assert phase.cancel_btn in _buttons(phase.permfa_container)
        assert phase.cancel_btn not in _buttons(phase.times_container)

    async def test_acknowledging_unlocks_game_times(self):
        interaction = _interaction()
        view = PermFASignupView(interaction)
        phase = view._agreement

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
