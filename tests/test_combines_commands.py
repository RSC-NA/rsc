from unittest.mock import AsyncMock, MagicMock, patch

import discord
import pytest

from rsc.combines.combines import SITE_UNAVAILABLE, CombineMixIn
from rsc.combines.models import CombinesStatus
from rsc.exceptions import SiteUnavailable

from .utils import command_callback


@pytest.fixture
def interaction(mock_member) -> MagicMock:
    interaction = MagicMock(spec=discord.Interaction)
    interaction.guild = mock_member.guild
    interaction.user = mock_member
    interaction.response.defer = AsyncMock()
    interaction.response.send_message = AsyncMock()
    interaction.followup.send = AsyncMock()
    return interaction


@pytest.fixture
def cog() -> MagicMock:
    cog = MagicMock()
    cog._get_combines_active = AsyncMock(return_value=True)
    cog._get_combines_api = AsyncMock(return_value="https://combines.example/api/")
    return cog


def _reply(interaction) -> discord.Embed:
    interaction.response.defer.assert_awaited_once_with(ephemeral=True)
    interaction.response.send_message.assert_not_awaited()
    interaction.followup.send.assert_awaited_once()
    assert interaction.followup.send.await_args is not None
    assert interaction.followup.send.await_args.kwargs["ephemeral"] is True
    return interaction.followup.send.await_args.kwargs["embed"]


@pytest.mark.parametrize(
    ("command", "call"),
    [
        (CombineMixIn._combines_check_in_cmd, "combines_check_in"),
        (CombineMixIn._combines_check_out_cmd, "combines_check_out"),
        (CombineMixIn._combines_lobby_info_cmd, "combines_lobby"),
        (CombineMixIn._combines_active_cmd, "combines_active"),
    ],
)
async def test_site_down_defers_then_says_so_once(cog, interaction, command, call):
    with patch(f"rsc.combines.combines.api.{call}", AsyncMock(side_effect=SiteUnavailable("down"))):
        await command_callback(command)(cog, interaction)

    embed = _reply(interaction)
    assert embed.description == SITE_UNAVAILABLE


async def test_check_out_success_is_not_an_error(cog, interaction):
    result = CombinesStatus(status="success", message="Checked out")
    with patch("rsc.combines.combines.api.combines_check_out", AsyncMock(return_value=result)):
        await command_callback(CombineMixIn._combines_check_out_cmd)(cog, interaction)

    embed = _reply(interaction)
    assert embed.title == "Checked Out"


async def test_check_out_error_shows_the_site_message(cog, interaction):
    result = CombinesStatus(status="error", message="You are not checked in")
    with patch("rsc.combines.combines.api.combines_check_out", AsyncMock(return_value=result)):
        await command_callback(CombineMixIn._combines_check_out_cmd)(cog, interaction)

    embed = _reply(interaction)
    assert (embed.title, embed.description) == ("Combines Check Out", "You are not checked in")
