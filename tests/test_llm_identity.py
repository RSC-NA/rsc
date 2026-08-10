"""Tests for the asker's league identity.

`UserIdentity.describe()` is pasted straight into the user block of every
question, so anything ugly or wrong here is read back to the asker in the
answer.
"""

from unittest.mock import AsyncMock, MagicMock

import discord
import pytest
from rscapi.models.league_player_status_enum import LeaguePlayerStatusEnum

from rsc.llm.agent.service import resolve_agent_identity


def league_player(status: str, *, tier: str = "Elite", team: str | None = None) -> MagicMock:
    player = MagicMock()
    player.player.name = "nickm"
    # The generated client hands back its own enum, not a plain string.
    player.status = LeaguePlayerStatusEnum(status)
    player.tier.name = tier
    if team is None:
        player.team = None
    else:
        player.team.name = team
        player.team.franchise.name = "The Quad Dynasty"
    return player


@pytest.fixture
def guild():
    mock = MagicMock()
    mock.id = 1
    return mock


@pytest.fixture
def member():
    # spec= matters: resolve_agent_identity only looks a member up in the API
    # when isinstance(member, discord.Member) holds.
    mock = MagicMock(spec=discord.Member)
    mock.id = 100
    mock.display_name = "RF | nickm"
    return mock


async def test_status_is_described_in_the_league_s_own_wording(guild, member):
    """The bug this guards: "nickm is a LeaguePlayerStatusEnum.FA in the Elite tier."

    `str()` on the client's enum yields its repr, which went into the prompt and
    came back out in the answer.
    """
    cog = MagicMock()
    cog.players = AsyncMock(return_value=[league_player("FA")])

    identity = await resolve_agent_identity(cog, guild, member)

    assert identity.status == "Free Agent"
    assert identity.describe() == "nickm is a Free Agent in the Elite tier."


async def test_rostered_players_are_described_by_team_and_franchise(guild, member):
    cog = MagicMock()
    cog.players = AsyncMock(return_value=[league_player("RO", tier="Veteran", team="Pushwalkers")])

    identity = await resolve_agent_identity(cog, guild, member)

    assert identity.describe() == "nickm plays for Pushwalkers (The Quad Dynasty) in the Veteran tier."


async def test_an_api_failure_still_yields_a_usable_identity(guild, member):
    """An unidentified asker gets an answer, just without personalisation.

    The fallback name comes from the nickname, so it still has the franchise
    prefix taken off it.
    """
    cog = MagicMock()
    cog.players = AsyncMock(side_effect=RuntimeError("league is down"))

    identity = await resolve_agent_identity(cog, guild, member)

    assert identity.name == "nickm"
    assert identity.discord_id == 100
