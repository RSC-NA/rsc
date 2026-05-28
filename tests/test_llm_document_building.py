from datetime import UTC, datetime, timedelta
from types import SimpleNamespace
from unittest.mock import MagicMock

import pytest

from rsc.enums import MatchType
from rsc.llm.loaders.matchloader import MatchDocumentLoader
from rsc.llm.loaders.statsloader import PlayerStatsDocumentLoader, StandingsDocumentLoader, TeamStatsDocumentLoader


@pytest.mark.asyncio
async def test_match_loader_batches_result_enrichment_and_preserves_order() -> None:
    match_date = datetime.now(UTC) - timedelta(days=1)
    matches = []
    for idx in range(3):
        match = MagicMock()
        match.id = idx + 1
        match.match_type = MatchType.REGULAR
        match.day = idx + 1
        match.var_date = match_date
        match.home_team = f"Home {idx + 1}"
        match.away_team = f"Away {idx + 1}"
        matches.append(match)

    fetched_ids: list[int] = []

    async def fetch_match(match_id: int) -> SimpleNamespace:
        fetched_ids.append(match_id)
        return SimpleNamespace(home_wins=match_id, away_wins=0, ballchasing_group=None)

    loader = MatchDocumentLoader(matches, match_fetcher=fetch_match)
    docs = [doc async for doc in loader.alazy_load()]

    assert fetched_ids == [1, 2, 3]
    assert [doc.metadata["id"] for doc in docs] == ["1", "2", "3"]
    assert "doc_type" not in docs[0].metadata
    assert "corpus" not in docs[0].metadata
    assert "source_type" not in docs[0].metadata
    assert "Home 1 won" in docs[0].page_content
    assert "Home 2 won" in docs[1].page_content
    assert "Home 3 won" in docs[2].page_content


@pytest.mark.asyncio
async def test_match_loader_fetches_results_only_within_grace_window() -> None:
    now = datetime.now(UTC)
    match_dates = [
        now - timedelta(days=1),
        now + timedelta(days=1),
        now + timedelta(days=3),
        None,
    ]
    matches = []
    for idx, match_date in enumerate(match_dates, start=1):
        match = MagicMock()
        match.id = idx
        match.match_type = MatchType.REGULAR
        match.day = idx
        match.var_date = match_date
        match.home_team = f"Home {idx}"
        match.away_team = f"Away {idx}"
        matches.append(match)

    fetched_ids: list[int] = []

    async def fetch_match(match_id: int) -> SimpleNamespace:
        fetched_ids.append(match_id)
        return SimpleNamespace(home_wins=match_id, away_wins=0, ballchasing_group=None)

    loader = MatchDocumentLoader(matches, match_fetcher=fetch_match)
    docs = [doc async for doc in loader.alazy_load()]

    assert fetched_ids == [1, 2]
    assert [doc.metadata["id"] for doc in docs] == ["1", "2", "3", "4"]
    assert "Home 1 won" in docs[0].page_content
    assert "Home 2 won" in docs[1].page_content
    assert "Match Result:" not in docs[2].page_content
    assert "Match Result:" not in docs[3].page_content


@pytest.mark.asyncio
async def test_player_stats_loader_builds_player_stats_document() -> None:
    stats = SimpleNamespace(
        id=10,
        player="nickm",
        season=22,
        type="regular season",
        games_played=20,
        games_won=12,
        games_lost=8,
        goals=40,
        assists=15,
        saves=30,
        shots=100,
        points=95,
        mvps=3,
        shooting_percentage=40.0,
        avg_speed=1500,
        bpm=390.5,
        bcpm=620.2,
        demos_inflicted=7,
        demos_taken=4,
    )

    docs = [doc async for doc in PlayerStatsDocumentLoader([stats]).alazy_load()]

    assert len(docs) == 1
    assert "nickm has RSC player stats for Season 22" in docs[0].page_content
    assert "40 goals" in docs[0].page_content
    assert "40.00% shooting percentage" in docs[0].page_content
    assert "390.50 boost per minute" in docs[0].page_content
    assert "620.20 boost collected per minute" in docs[0].page_content
    assert docs[0].metadata["source"] == "Player Stats API"
    assert docs[0].metadata["player"] == "nickm"
    assert docs[0].metadata["season_number"] == 22
    assert "source_type" not in docs[0].metadata


@pytest.mark.asyncio
async def test_team_stats_loader_builds_team_stats_document() -> None:
    stats = SimpleNamespace(
        id=20,
        team="Boost Hunters",
        type="regular season",
        games_played=30,
        games_won=18,
        games_lost=12,
        win_percentage=60.0,
        goals=90,
        assists=65,
        saves=120,
        shots=250,
        points=210,
        opponent_goals=75,
        opponent_assists=50,
        opponent_saves=110,
        opponent_shots=220,
        opponent_points=175,
        shooting_percentage=36.0,
        opponent_shooting_percentage=34.0,
        goal_differential=15,
        demos_inflicted=22,
        demos_taken=19,
    )

    docs = [doc async for doc in TeamStatsDocumentLoader([stats], season_number=22).alazy_load()]

    assert len(docs) == 1
    assert "Boost Hunters has RSC team stats for Season 22" in docs[0].page_content
    assert "15 goal differential" in docs[0].page_content
    assert "60.00% win percentage" in docs[0].page_content
    assert "36.00% shooting percentage" in docs[0].page_content
    assert "34.00% opponent shooting percentage" in docs[0].page_content
    assert docs[0].metadata["source"] == "Team Stats API"
    assert docs[0].metadata["team"] == "Boost Hunters"
    assert docs[0].metadata["season_number"] == 22
    assert "source_type" not in docs[0].metadata


@pytest.mark.asyncio
async def test_standings_loader_builds_franchise_and_tier_documents() -> None:
    franchise_standing = SimpleNamespace(
        franchise="Boost Club",
        gm="nickm",
        wins=50,
        losses=30,
        win_percentage=62.5,
        franchise_standings_rank=2,
    )
    team_standing = SimpleNamespace(
        franchise="Boost Club",
        team="Boost Hunters",
        tier="Elite",
        rank=1,
        games_played=30,
        games_won=20,
        games_lost=10,
    )

    docs = [
        doc
        async for doc in StandingsDocumentLoader(
            franchise_standings=[franchise_standing],
            team_standings=[team_standing],
            season_number=22,
        ).alazy_load()
    ]

    assert len(docs) == 2
    assert "Boost Club is ranked #2" in docs[0].page_content
    assert "62.50% win percentage" in docs[0].page_content
    assert "Boost Hunters is ranked #1" in docs[1].page_content
    assert docs[0].metadata["source"] == "Franchise Standings API"
    assert docs[1].metadata["source"] == "Tier Standings API"
    assert docs[0].metadata["standings_scope"] == "franchise"
    assert docs[1].metadata["standings_scope"] == "team"
    assert "source_type" not in docs[0].metadata
