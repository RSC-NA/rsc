from unittest.mock import AsyncMock, MagicMock, patch

import discord
import pytest

from rsc.devleague.manager import DevLeagueManagerMixIn
from rsc.devleague.runner import DevLeague

from .utils import command_callback


@pytest.fixture
def guild() -> MagicMock:
    return MagicMock(spec=discord.Guild)


@pytest.fixture
def interaction(guild) -> MagicMock:
    interaction = MagicMock(spec=discord.Interaction)
    interaction.guild = guild
    interaction.response.defer = AsyncMock()
    interaction.followup.send = AsyncMock()
    return interaction


@pytest.fixture
def cog() -> MagicMock:
    cog = MagicMock()
    cog._devleague_runner.league = DevLeague(MagicMock())
    cog._devleague_runner.open_lobbies = AsyncMock(return_value={102, 101})
    cog._devleague_runner.end_now = AsyncMock(return_value=[])
    return cog


class TestTeardownCommand:
    async def test_runs_the_shared_teardown_on_dev_league(self, cog, interaction):
        with patch("rsc.devleague.manager.teardown_command", AsyncMock()) as teardown:
            await command_callback(DevLeagueManagerMixIn._devleague_teardown_cmd)(cog, interaction, match_id=101)

        teardown.assert_awaited_once_with(interaction, cog._devleague_runner, 101)


class TestDisable:
    async def test_turns_off_then_ends_every_open_match(self, cog, guild, interaction):
        order = []
        cog._set_devleague_active = AsyncMock(side_effect=lambda *args: order.append("off"))
        cog._devleague_runner.end_now.side_effect = lambda *args: order.append("end") or []

        await command_callback(DevLeagueManagerMixIn._devleague_disable_cmd)(cog, interaction)

        # Off first, so no new match starts during the teardown
        assert order == ["off", "end"]
        cog._set_devleague_active.assert_awaited_once_with(guild, False)
        cog._devleague_runner.end_now.assert_awaited_once_with(guild, [101, 102])
        assert interaction.followup.send.await_args is not None
        embed = interaction.followup.send.await_args.kwargs["embed"]
        assert embed.description == "Dev League game channels will no longer be created.\nEnded 2 matches: 101, 102."
        assert embed.color == discord.Color.green()

    async def test_orange_when_a_match_fails_to_end(self, cog, interaction):
        cog._set_devleague_active = AsyncMock()
        cog._devleague_runner.end_now.return_value = [102]

        await command_callback(DevLeagueManagerMixIn._devleague_disable_cmd)(cog, interaction)

        assert interaction.followup.send.await_args is not None
        embed = interaction.followup.send.await_args.kwargs["embed"]
        assert embed.color == discord.Color.orange()
        assert "Unable to end match 102." in embed.description

    async def test_nothing_open(self, cog, interaction):
        cog._set_devleague_active = AsyncMock()
        cog._devleague_runner.open_lobbies.return_value = set()

        await command_callback(DevLeagueManagerMixIn._devleague_disable_cmd)(cog, interaction)

        assert interaction.followup.send.await_args is not None
        embed = interaction.followup.send.await_args.kwargs["embed"]
        assert embed.description == "Dev League game channels will no longer be created."
