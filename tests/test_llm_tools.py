"""Tests for the agent's tools.

The cog is a mock whose `RSCMixIn` helpers return real-shaped objects, so these
exercise the tools' aggregation and formatting without touching the API.
"""

from datetime import UTC, datetime
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock

import pytest

from rsc.llm.agent.context import AgentContext, UserIdentity
from rsc.llm.agent.tools.league import get_franchise, list_franchises, list_players
from rsc.llm.agent.tools.rules import ask_rulebook, get_rule, search_rules_tool
from rsc.llm.agent.tools.stats import top_players
from rsc.llm.config import TOOL_RESULT_MAX_CHARS
from rsc.llm.rulebook import RuleBook, load_rulebooks


def franchise(id_: int, name: str, prefix: str, gm: str, tiers: tuple[str, ...] = ("Master",)) -> SimpleNamespace:
    return SimpleNamespace(
        id=id_,
        name=name,
        prefix=prefix,
        gm=SimpleNamespace(rsc_name=gm, discord_id=1000 + id_),
        tiers=[SimpleNamespace(name=tier) for tier in tiers],
        teams=[],
    )


def elevated(member: str, franchise_id: int) -> SimpleNamespace:
    return SimpleNamespace(
        member=SimpleNamespace(rsc_name=member),
        franchise_id=franchise_id,
        agm=True,
        gm=False,
        position=None,
    )


def league_player(name: str, status: str = "FA", tier: str = "Master", team: str | None = None) -> SimpleNamespace:
    return SimpleNamespace(
        player=SimpleNamespace(name=name, rsc_name=name, discord_id=42),
        status=status,
        tier=SimpleNamespace(name=tier),
        team=SimpleNamespace(name=team, franchise=SimpleNamespace(name="Some Franchise")) if team else None,
        captain=False,
        contract_length=2,
        current_mmr=1500,
    )


def player_stat(name: str, goals: int, rank: int, games: int = 10) -> SimpleNamespace:
    return SimpleNamespace(
        player=SimpleNamespace(name=name, rsc_name=name),
        goals=goals,
        goals_rank=rank,
        games_played=games,
    )


@pytest.fixture
def cog():
    mock = MagicMock()
    mock.franchises = AsyncMock(return_value=[])
    mock.league_elevated_roles = AsyncMock(return_value=[])
    mock.players = AsyncMock(return_value=[])
    mock.player_count = AsyncMock(return_value=0)
    mock.tier_id_by_name = AsyncMock(return_value=7)
    mock.tier_player_stats = AsyncMock(return_value=[])
    mock.current_season = AsyncMock(return_value=SimpleNamespace(id=99, number=26))
    return mock


@pytest.fixture
def ctx(cog):
    guild = MagicMock()
    guild.id = 12345
    return AgentContext(
        cog=cog,
        guild=guild,
        client=MagicMock(),
        now=datetime(2026, 8, 10, tzinfo=UTC),
        identity=UserIdentity(name="nickm", discord_id=42),
    )


# Franchises and AGMs


async def test_list_franchises_returns_every_franchise(ctx, cog):
    """The failure that motivated the rewrite.

    Top-k retrieval returned five of thirty franchises and the model correctly
    reported it could not produce a full list. A tool call returns all of them.
    """
    cog.franchises.return_value = [franchise(i, f"Franchise {i}", f"F{i}", f"GM{i}") for i in range(30)]

    result = await list_franchises(ctx)

    assert "total=30" in result
    for i in range(30):
        assert f"GM: GM{i}" in result


async def test_list_franchises_fetches_agms_in_a_single_call(ctx, cog):
    """AGMs must cost one league-wide sweep, not one call per franchise.

    `FranchiseList` has no `agms` field, so the naive implementation is a detail
    fetch per franchise -- thirty round trips for one question.
    """
    cog.franchises.return_value = [franchise(i, f"Franchise {i}", f"F{i}", f"GM{i}") for i in range(30)]
    cog.league_elevated_roles.return_value = [elevated("Assistant0", 0), elevated("Assistant1", 1)]

    result = await list_franchises(ctx, include_agms=True)

    assert cog.league_elevated_roles.await_count == 1
    assert cog.league_elevated_roles.await_args.kwargs["agm"] is True
    assert "Assistant0" in result
    # A franchise with no AGM must still render, rather than being dropped.
    assert "AGMs: none" in result


async def test_list_franchises_omits_agms_when_not_asked(ctx, cog):
    cog.franchises.return_value = [franchise(1, "One", "O", "GM1")]

    result = await list_franchises(ctx)

    assert cog.league_elevated_roles.await_count == 0
    assert "AGMs" not in result


async def test_get_franchise_reports_missing_franchise(ctx, cog):
    cog.fetch_franchise = AsyncMock(return_value=None)

    assert "No franchise found" in await get_franchise(ctx, "Nonexistent")


# Players


async def test_list_players_reports_true_total_when_truncated(ctx, cog):
    """A capped list must never read as a complete one."""
    cog.players.return_value = [league_player(f"Player{i}") for i in range(25)]
    cog.player_count.return_value = 137

    result = await list_players(ctx, status="FA", limit=25)

    assert "total=137" in result
    assert "showing=25" in result


async def test_list_players_rejects_unknown_status(ctx):
    with pytest.raises(ValueError, match="unknown status"):
        await list_players(ctx, status="NOPE")


async def test_list_players_clamps_limit(ctx, cog):
    cog.players.return_value = []

    await list_players(ctx, limit=5000)

    assert cog.players.await_args.kwargs["limit"] == 50


# Stats


async def test_top_players_ranks_by_server_rank(ctx, cog):
    """Ranking happens here, not in the model."""
    cog.tier_player_stats.return_value = [
        player_stat("Third", 5, 3),
        player_stat("First", 20, 1),
        player_stat("Second", 12, 2),
    ]

    result = await top_players(ctx, stat="goals", tier="Master", limit=3)
    rows = [line for line in result.splitlines() if "|" in line and not line.startswith("RANK")]

    assert "First" in rows[0]
    assert "Second" in rows[1]
    assert "Third" in rows[2]


async def test_top_players_honours_min_games(ctx, cog):
    cog.tier_player_stats.return_value = [
        player_stat("Regular", 20, 1, games=15),
        player_stat("Cameo", 30, 2, games=1),
    ]

    result = await top_players(ctx, stat="goals", tier="Master", min_games=5)

    assert "Regular" in result
    assert "Cameo" not in result


async def test_top_players_rejects_unknown_stat(ctx):
    assert "ERROR" in await top_players(ctx, stat="vibes", tier="Master")


async def test_top_players_clamps_limit(ctx, cog):
    cog.tier_player_stats.return_value = [player_stat(f"P{i}", 100 - i, i + 1) for i in range(40)]

    result = await top_players(ctx, stat="goals", tier="Master", limit=99)
    rows = [line for line in result.splitlines() if line and line[0].isdigit()]

    assert len(rows) == 15


# Rules


@pytest.fixture(autouse=True)
async def _rulebooks():
    await load_rulebooks()


async def test_get_rule_returns_text_and_records_citation(ctx):
    result = await get_rule(ctx, "5.7.3", book="competitive")

    assert "5.7.3" in result
    assert "RSC Rules 5.7.3" in ctx.citations


async def test_get_rule_disambiguates_across_books(ctx):
    """Rule numbers repeat across books, so an unqualified lookup must show which is which."""
    result = await get_rule(ctx, "3.1")

    assert result.count("===") >= 4  # at least two labelled blocks
    assert "RSC Rules 3.1" in result
    assert "Behavioral 3.1" in result


async def test_get_rule_reports_missing_rule(ctx):
    assert "No rule" in await get_rule(ctx, "99.99", book="competitive")


async def test_search_rules_returns_excerpts_with_citations(ctx):
    result = await search_rules_tool(ctx, "substitution", book="competitive", limit=3)

    assert "RSC Rules" in result
    assert ctx.citations


async def test_rules_tools_reject_unknown_book(ctx):
    with pytest.raises(ValueError, match="unknown rulebook"):
        await get_rule(ctx, "1.1", book="madeup")


async def test_ask_rulebook_uses_the_subagent_and_shares_usage(ctx):
    ctx.client.responses = MagicMock()
    ctx.client.responses.create = AsyncMock(
        return_value=SimpleNamespace(
            output_text="You may not. See RSC Rules 5.6.3.2.",
            usage=SimpleNamespace(
                input_tokens=4000,
                output_tokens=50,
                input_tokens_details=SimpleNamespace(cached_tokens=0),
                output_tokens_details=SimpleNamespace(reasoning_tokens=0),
            ),
        )
    )

    result = await ask_rulebook(ctx, "can a permFA sub for the same franchise twice in a row")

    assert "5.6.3.2" in result
    # Sub-agent spend must count against the same ceiling as the main loop.
    assert ctx.usage.input_tokens == 4000


async def test_ask_rulebook_sends_only_scoped_sections(ctx):
    """Section scoping is the saving; a whole book would be far larger."""
    ctx.client.responses = MagicMock()
    ctx.client.responses.create = AsyncMock(
        return_value=SimpleNamespace(output_text="ok", usage=None)
    )

    await ask_rulebook(ctx, "can a permFA sub twice in a row", book="competitive")

    sent = ctx.client.responses.create.await_args.kwargs["input"][0]["content"]
    assert len(sent) < 25_000, "sub-agent context should be section scoped, not the whole book"


# Output budget


@pytest.mark.parametrize("count", [200])
async def test_tool_output_respects_the_char_budget(ctx, cog, count):
    cog.franchises.return_value = [franchise(i, f"Franchise Number {i}", f"FN{i}", f"GeneralManager{i}") for i in range(count)]

    result = await list_franchises(ctx)

    assert len(result) <= TOOL_RESULT_MAX_CHARS + 200
