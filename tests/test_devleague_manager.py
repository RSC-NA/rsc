from unittest.mock import AsyncMock, MagicMock, call

import discord
import pytest

from rsc.devleague.manager import DevLeagueManagerMixIn

from .utils import command_callback

teardown_cmd = command_callback(DevLeagueManagerMixIn._devleague_teardown_cmd)


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


def _cog(open_ids: set[int]) -> MagicMock:
    cog = MagicMock()
    cog._devleague_runner.open_lobbies = AsyncMock(return_value=open_ids)
    cog._devleague_runner.teardown = AsyncMock()
    return cog


def _description(send: AsyncMock) -> str:
    assert send.await_args is not None
    return send.await_args.kwargs["embed"].description


class TestTeardownCommand:
    async def test_one_match_skips_the_grace_period(self, guild, interaction):
        cog = _cog({101, 102})

        await teardown_cmd(cog, interaction, match_id=101)

        cog._devleague_runner.teardown.assert_awaited_once_with(guild, 101, delay=False)
        assert _description(interaction.followup.send) == "Ended match 101."

    async def test_no_match_ends_every_open_match(self, guild, interaction):
        cog = _cog({102, 101})

        await teardown_cmd(cog, interaction)

        assert cog._devleague_runner.teardown.await_args_list == [
            call(guild, 101, delay=False),
            call(guild, 102, delay=False),
        ]
        assert _description(interaction.followup.send) == "Ended 2 matches: 101, 102."

    async def test_unknown_match(self, interaction):
        cog = _cog({101})

        await teardown_cmd(cog, interaction, match_id=7)

        cog._devleague_runner.teardown.assert_not_called()
        assert _description(interaction.response.send_message) == "Match 7 has no live card or voice channels."

    async def test_nothing_to_end(self, interaction):
        cog = _cog(set())

        await teardown_cmd(cog, interaction)

        cog._devleague_runner.teardown.assert_not_called()
        assert _description(interaction.response.send_message) == "There are no Dev League matches to end."

    async def test_one_failure_does_not_stop_the_rest(self, interaction):
        cog = _cog({101, 102})
        cog._devleague_runner.teardown.side_effect = [discord.HTTPException(MagicMock(status=403), "nope"), None]

        await teardown_cmd(cog, interaction)

        assert cog._devleague_runner.teardown.await_count == 2
        assert _description(interaction.followup.send) == "Ended match 102.\nUnable to end match 101. Check the bot's permissions."
