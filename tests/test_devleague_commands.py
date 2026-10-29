from unittest.mock import AsyncMock, MagicMock, patch

import discord
import pytest

from rsc.devleague.devleague import SITE_UNAVAILABLE, DevLeagueMixIn
from rsc.exceptions import SiteUnavailable

from .utils import command_callback


@pytest.fixture
def interaction(mock_member) -> MagicMock:
    interaction = MagicMock(spec=discord.Interaction)
    interaction.guild = mock_member.guild
    interaction.user = mock_member
    interaction.response.defer = AsyncMock()
    interaction.followup.send = AsyncMock()
    return interaction


@pytest.mark.parametrize(
    ("command", "call"),
    [
        (DevLeagueMixIn.dev_league_status_cmd, "dev_league_status"),
        (DevLeagueMixIn.dev_league_checkin_cmd, "dev_league_check_in"),
        (DevLeagueMixIn.dev_league_checkout_cmd, "dev_league_check_out"),
    ],
)
async def test_site_down_says_so_once_without_raising(interaction, command, call):
    with patch(f"rsc.devleague.devleague.api.{call}", AsyncMock(side_effect=SiteUnavailable("down"))):
        await command_callback(command)(MagicMock(), interaction)

    # Raising would have Red post a second, generic error
    interaction.followup.send.assert_awaited_once()
    assert interaction.followup.send.await_args is not None
    assert interaction.followup.send.await_args.kwargs["ephemeral"] is True
    assert interaction.followup.send.await_args.kwargs["embed"].description == SITE_UNAVAILABLE
