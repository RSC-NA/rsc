"""Tests for the /playerstats and /teamstats embed."""

from typing import Any
from unittest.mock import MagicMock

from rscapi.models.player_season_stats import PlayerSeasonStats

from rsc.stats.stats import StatsMixIn


def _player_stats(**overrides) -> PlayerSeasonStats:
    values: dict[str, Any] = {
        "player": "Striker",
        "season": 27,
        "games_played": 40,
        "games_won": 26,
        "games_lost": 14,
        "goals": 50,
        "saves": 30,
        "assists": 20,
        "shots": 120,
        "shooting_percentage": 41.67,
        "mvps": 12,
        "points": 15000,
        "avg_speed": 1520.33,
        "team_goals_in_games": 113,
        "opponent_goals_in_games": 74,
    }
    values.update(overrides)
    return PlayerSeasonStats.model_construct(**values)


def _fields(embed) -> dict[str, str]:
    return {f.name: f.value for f in embed.fields if f.name}


async def test_player_embed_shows_goals_for_against_and_differential():
    embed = await StatsMixIn.create_stats_embed(MagicMock(), _player_stats())

    fields = _fields(embed)
    assert fields["Team Goals"] == "113"
    assert fields["Goals Against"] == "74"
    assert fields["Goal Differential"] == "+39"


async def test_player_embed_negative_differential_has_sign():
    embed = await StatsMixIn.create_stats_embed(MagicMock(), _player_stats(team_goals_in_games=60, opponent_goals_in_games=75))

    assert _fields(embed)["Goal Differential"] == "-15"


async def test_player_embed_omits_goal_fields_when_missing():
    embed = await StatsMixIn.create_stats_embed(MagicMock(), _player_stats(opponent_goals_in_games=None))

    fields = _fields(embed)
    assert "Team Goals" not in fields
    assert "Goals Against" not in fields
    assert "Goal Differential" not in fields
