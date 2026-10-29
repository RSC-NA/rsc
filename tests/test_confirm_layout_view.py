from unittest.mock import AsyncMock, MagicMock

import discord
import pytest
from discord.ui import ActionRow, Button, Container, TextDisplay

from rsc.views import ConfirmLayoutView, ResultView


def _interaction(*, responded: bool = False) -> MagicMock:
    interaction = MagicMock(spec=discord.Interaction)
    interaction.user = MagicMock(spec=discord.Member)
    interaction.response = MagicMock()
    interaction.response.is_done.return_value = responded
    interaction.response.send_message = AsyncMock()
    interaction.response.edit_message = AsyncMock()
    interaction.followup = MagicMock()
    interaction.followup.send = AsyncMock()
    interaction.edit_original_response = AsyncMock()
    return interaction


def _view(interaction: MagicMock | None = None, **kwargs) -> ConfirmLayoutView:
    return ConfirmLayoutView(interaction or _interaction(), title="Delete Franchise", description="Delete **Hex Systems**?", **kwargs)


def _container(view: discord.ui.LayoutView) -> Container:
    container = view.children[0]
    assert isinstance(container, Container)
    return container


def _buttons(view: ConfirmLayoutView) -> list[Button]:
    return [b for row in _container(view).children if isinstance(row, ActionRow) for b in row.children if isinstance(b, Button)]


def _texts(view: discord.ui.LayoutView) -> list[str]:
    return [c.content for c in _container(view).children if isinstance(c, TextDisplay)]


class TestLayout:
    async def test_title_description_and_buttons(self):
        view = _view(confirm_label="Delete", confirm_style=discord.ButtonStyle.danger)
        assert _texts(view) == ["## Delete Franchise", "Delete **Hex Systems**?"]
        confirm, cancel = _buttons(view)
        assert (confirm.label, confirm.style) == ("Delete", discord.ButtonStyle.danger)
        assert (cancel.label, cancel.style) == ("Cancel", discord.ButtonStyle.secondary)

    async def test_defaults(self):
        confirm, _ = _buttons(_view())
        assert (confirm.label, confirm.style) == ("Confirm", discord.ButtonStyle.success)
        assert _container(_view()).accent_colour == discord.Colour.orange()


class TestPrompt:
    async def test_responds_when_unanswered(self):
        interaction = _interaction()
        view = _view(interaction)
        await view.prompt()
        interaction.response.send_message.assert_awaited_once_with(view=view, ephemeral=True)

    async def test_follows_up_when_already_answered(self):
        interaction = _interaction(responded=True)
        view = _view(interaction)
        await view.prompt(ephemeral=False)
        interaction.followup.send.assert_awaited_once_with(view=view, ephemeral=False)
        interaction.response.send_message.assert_not_awaited()


class TestClicks:
    @pytest.mark.parametrize(("index", "confirmed", "title"), [(0, True, "## Deleting"), (1, False, "## Kept")])
    async def test_click_answers_and_records(self, index, confirmed, title):
        view = _view(working_title="Deleting", cancelled_title="Kept")
        click = _interaction()

        await _buttons(view)[index].callback(click)

        assert view.result is confirmed
        assert view.is_finished()
        # The click itself is answered, so Discord never shows "This interaction failed"
        result = click.response.edit_message.await_args.kwargs["view"]
        assert isinstance(result, ResultView)
        assert _texts(result)[0] == title

    async def test_timeout_means_no(self):
        interaction = _interaction()
        view = _view(interaction)
        await view.on_timeout()
        assert view.result is False
        result = interaction.edit_original_response.await_args.kwargs["view"]
        assert _texts(result)[0] == "## Time Out"
        assert _container(result).accent_colour == discord.Colour.yellow()
