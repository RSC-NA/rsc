from unittest.mock import AsyncMock, MagicMock, call

import discord
import pytest

from rsc.combines.runner import CombinesLeague
from rsc.devleague.runner import DevLeague
from rsc.lobbies.commands import ended_lines, teardown_command
from rsc.lobbies.runner import LobbyRunner


@pytest.fixture
def guild() -> MagicMock:
    return MagicMock(spec=discord.Guild)


@pytest.fixture
def interaction(guild) -> MagicMock:
    interaction = MagicMock(spec=discord.Interaction)
    interaction.guild = guild
    interaction.response.send_message = AsyncMock()
    interaction.response.defer = AsyncMock()
    interaction.followup.send = AsyncMock()
    return interaction


def _runner(open_ids: set[int], failed: list[int] | None = None, league=DevLeague) -> MagicMock:
    runner = MagicMock()
    runner.league = league(MagicMock())
    runner.open_lobbies = AsyncMock(return_value=open_ids)
    runner.end_now = AsyncMock(return_value=failed or [])
    return runner


def _embed(send: AsyncMock) -> discord.Embed:
    assert send.await_args is not None
    return send.await_args.kwargs["embed"]


class TestTeardownCommand:
    async def test_one_lobby(self, guild, interaction):
        runner = _runner({101, 102})

        await teardown_command(interaction, runner, 101)

        runner.end_now.assert_awaited_once_with(guild, [101])
        assert _embed(interaction.followup.send).description == "Ended match 101."

    async def test_no_id_ends_every_open_lobby(self, guild, interaction):
        runner = _runner({102, 101})

        await teardown_command(interaction, runner, None)

        runner.end_now.assert_awaited_once_with(guild, [101, 102])
        assert _embed(interaction.followup.send).description == "Ended 2 matches: 101, 102."

    async def test_unknown_lobby(self, interaction):
        runner = _runner({101})

        await teardown_command(interaction, runner, 7)

        runner.end_now.assert_not_called()
        assert _embed(interaction.response.send_message).description == "Match 7 has no live card or voice channels."

    async def test_nothing_to_end(self, interaction):
        runner = _runner(set())

        await teardown_command(interaction, runner, None)

        runner.end_now.assert_not_called()
        assert _embed(interaction.response.send_message).description == "There are no open matches to end."

    async def test_failures_are_reported(self, interaction):
        runner = _runner({101, 102}, failed=[101])

        await teardown_command(interaction, runner, None)

        assert _embed(interaction.followup.send).description == "Ended match 102.\nUnable to end match 101. Check the bot's permissions."

    async def test_combines_wording(self, interaction):
        runner = _runner({4812, 4813}, league=CombinesLeague)

        await teardown_command(interaction, runner, None)

        embed = _embed(interaction.followup.send)
        assert embed.title == "Combines Teardown"
        assert embed.description == "Ended 2 lobbies: 4812, 4813."


class TestEndedLines:
    def test_nothing_ended(self):
        assert ended_lines(DevLeague(MagicMock()), [], []) == []


class TestEndNow:
    async def test_one_failure_does_not_stop_the_rest(self, guild):
        runner = LobbyRunner(MagicMock(), DevLeague(MagicMock()))
        runner.teardown = AsyncMock(side_effect=[discord.HTTPException(MagicMock(status=403), "nope"), None])

        failed = await runner.end_now(guild, [101, 102])

        assert failed == [101]
        assert runner.teardown.await_args_list == [call(guild, 101, delay=False), call(guild, 102, delay=False)]
