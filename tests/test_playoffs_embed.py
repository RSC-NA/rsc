"""Tests for the /playoffs command and embed."""

from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock, patch

import discord
import pytest
from rscapi.exceptions import ApiException
from rscapi.models.tier_playoff_hunt import TierPlayoffHunt

from rsc.exceptions import RscException
from rsc.stats.stats import PLAYOFF_CUT_LINE, StatsMixIn

from .utils import command_callback


def _team(rank: int, name: str, qualified: bool, **overrides) -> dict:
    values = {
        "team_id": rank,
        "team_name": name,
        "franchise_id": rank,
        "franchise_name": f"{name} Franchise",
        "franchise_prefix": name[:3].upper(),
        "franchise_logo_url": "",
        "conference": "L",
        "conference_label": "Lunar",
        "division": "N",
        "division_label": "None",
        "overall_rank": rank,
        "overall_games_back": float(rank - 1),
        "playoff_rank": rank,
        "playoff_seed": rank if qualified else None,
        "playoff_group_label": "Lunar",
        "playoff_cutoff": 2,
        "playoff_qualified": qualified,
        "playoff_qualifier_reason": "cut" if qualified else None,
        "tiebreak_draw": None,
        "playoff_status_label": "In Cut" if qualified else "Outside",
        "playoff_delta_label": "Top 2" if qualified else "1 win back",
        "playoff_magic_number": 5 if qualified else None,
        "playoff_magic_number_label": "5" if qualified else "-",
        "remaining_games": 8,
        "max_possible_games_won": 30,
        "group_games_back": None,
        "group_games_won": 10,
        "group_games_lost": 5,
        "group_win_pct": 66.7,
        "games_played": 20,
        "games_won": 21 - rank,
        "games_lost": rank - 1,
        "win_pct": 50.0,
        "goals": 50,
        "opponent_goals": 40,
        "goal_differential": 10,
        "shots": 200,
        "shot_pct": 25.0,
    }
    values.update(overrides)
    return values


def _hunt(teams: list[dict], divisions: list[dict] | None = None, **overrides) -> TierPlayoffHunt:
    values = {
        "tier_id": 1,
        "tier_name": "Premier",
        "tier_position": 9,
        "playoff_format": "CONF",
        "playoff_format_label": "Conferences",
        "playoff_format_source": "configured",
        "regular_season_complete": False,
        "groups": [
            {
                "label": "Lunar",
                "conference": "L",
                "accent": "lunar",
                "cutoff": 2,
                "cutline_rank": 2,
                "divisions": divisions or [],
                "teams": teams,
            }
        ],
    }
    values.update(overrides)
    return TierPlayoffHunt.model_validate(values)


def _stats_mixin() -> MagicMock:
    return MagicMock(playoff_team_line=StatsMixIn.playoff_team_line)


async def _embed(hunt: TierPlayoffHunt) -> discord.Embed:
    return await StatsMixIn.create_playoff_hunt_embed(_stats_mixin(), hunt, season=28)


async def test_embed_draws_the_cut_line_under_the_last_spot():
    teams = [_team(1, "Alpha", True), _team(2, "Bravo", True), _team(3, "Charlie", False)]
    embed = await _embed(_hunt(teams))

    assert embed.title == "S28 Premier Playoff Hunt"
    field = embed.fields[0]
    assert field.name == "Lunar · 2 spots"
    lines = (field.value or "").split("\n")
    assert lines[2] == PLAYOFF_CUT_LINE
    assert lines[0] == "` 1   20-0` **Alpha** · Top 2"
    assert lines[3] == "` 3   18-2` Charlie · 1 win back"


async def test_embed_has_no_cut_line_when_nobody_is_outside():
    teams = [_team(1, "Alpha", True), _team(2, "Bravo", True)]
    embed = await _embed(_hunt(teams))

    assert PLAYOFF_CUT_LINE not in (embed.fields[0].value or "")


async def test_embed_description_is_season_progress_only():
    hunt = _hunt([_team(1, "Alpha", True)], playoff_format_source="inferred", regular_season_complete=True)
    embed = await _embed(hunt)

    assert embed.description == "Regular season complete."


async def test_embed_skips_empty_groups():
    hunt = _hunt([])
    embed = await _embed(hunt)

    assert embed.fields == []


def test_team_line_tags_division_and_names_how_the_spot_was_won():
    leader = (
        _hunt([_team(1, "Alpha", True, playoff_qualifier_reason="division", division="O", playoff_delta_label="Leads Ocean")])
        .groups[0]
        .teams[0]
    )
    wildcard = _hunt([_team(2, "Bravo", True, playoff_qualifier_reason="wildcard", division="M")]).groups[0].teams[0]
    outside = _hunt([_team(3, "Charlie", False, division="O")]).groups[0].teams[0]

    assert StatsMixIn.playoff_team_line(leader, show_division=True) == "` 1   20-0` **Alpha** (O) · Division Leader"
    assert StatsMixIn.playoff_team_line(wildcard, show_division=True) == "` 2   19-1` **Bravo** (M) · Wildcard"
    assert StatsMixIn.playoff_team_line(outside, show_division=True) == "` 3   18-2` Charlie (O) · 1 win back"


async def test_footer_spells_out_division_letters():
    divisions = [{"division": "O", "label": "Ocean"}, {"division": "M", "label": "Mountain"}]
    embed = await _embed(_hunt([_team(1, "Alpha", True, division="O")], divisions=divisions))

    assert embed.footer.text == "Bold: in a playoff spot · (M) Mountain · (O) Ocean"


async def test_footer_has_no_division_legend_without_divisions():
    embed = await _embed(_hunt([_team(1, "Alpha", True)]))

    assert embed.footer.text == "Bold: in a playoff spot"


def test_team_line_escapes_markdown_in_team_names():
    team = _hunt([_team(3, "Under_Score*", False)]).groups[0].teams[0]

    assert StatsMixIn.playoff_team_line(team) == "` 3   18-2` Under\\_Score\\* · 1 win back"


# /playoffs command: tier resolution

playoffs_cmd = command_callback(StatsMixIn._playoffs_cmd)


def _interaction(user_id: int = 42) -> MagicMock:
    interaction = MagicMock()
    interaction.guild = MagicMock(spec=discord.Guild)
    interaction.user.id = user_id
    interaction.response.defer = AsyncMock()
    interaction.followup.send = AsyncMock()
    return interaction


def _cmd_cog(players=None) -> MagicMock:
    cog = MagicMock()
    cog.players = AsyncMock(return_value=players if players is not None else [])
    cog.tier_id_by_name = AsyncMock(return_value=7)
    cog.current_season = AsyncMock(return_value=SimpleNamespace(number=28))
    cog.tier_playoff_hunt = AsyncMock(return_value=SimpleNamespace(tier_name="Elite", groups=[SimpleNamespace(teams=[object()])]))
    cog.create_playoff_hunt_embed = AsyncMock(return_value=discord.Embed(title="hunt"))
    return cog


def _league_player(tier_id: int | None, tier_name: str = "Elite") -> SimpleNamespace:
    tier = SimpleNamespace(id=tier_id, name=tier_name) if tier_id is not None else None
    return SimpleNamespace(tier=tier)


@pytest.fixture(autouse=True)
def _no_tier_color():
    with patch("rsc.stats.stats.tier_color_by_name", AsyncMock(return_value=discord.Color.blue())):
        yield


class TestPlayoffsCommandTier:
    async def test_explicit_tier_skips_player_lookup(self):
        cog = _cmd_cog()

        await playoffs_cmd(cog, _interaction(), tier="Elite")

        cog.players.assert_not_called()
        cog.tier_id_by_name.assert_awaited_once()
        assert cog.tier_playoff_hunt.await_args.kwargs["tier_id"] == 7

    async def test_no_tier_uses_callers_tier(self):
        cog = _cmd_cog(players=[_league_player(3)])

        await playoffs_cmd(cog, _interaction(user_id=42))

        cog.players.assert_awaited_once()
        kwargs = cog.players.await_args.kwargs
        assert kwargs["discord_id"] == 42
        assert kwargs["season_number"] is None
        cog.tier_id_by_name.assert_not_called()
        assert cog.tier_playoff_hunt.await_args.kwargs["tier_id"] == 3

    async def test_no_tier_with_season_uses_tier_from_that_season(self):
        cog = _cmd_cog(players=[_league_player(5)])

        await playoffs_cmd(cog, _interaction(), season=26)

        assert cog.players.await_args.kwargs["season_number"] == 26
        assert cog.tier_playoff_hunt.await_args.kwargs == {"tier_id": 5, "season": 26}

    @pytest.mark.parametrize("players", [[], [_league_player(None)]], ids=["not-a-league-player", "no-tier"])
    async def test_no_tier_and_none_found_errors(self, players):
        cog = _cmd_cog(players=players)
        interaction = _interaction()

        await playoffs_cmd(cog, interaction)

        embed = interaction.followup.send.await_args.kwargs["embed"]
        assert "can't determine your tier" in embed.description
        assert "`tier`" in embed.description
        cog.tier_playoff_hunt.assert_not_called()

    async def test_player_lookup_api_error_is_reported(self):
        cog = _cmd_cog()
        cog.players.side_effect = RscException(ApiException(status=500, reason="Server Error"))
        interaction = _interaction()

        await playoffs_cmd(cog, interaction)

        interaction.followup.send.assert_awaited_once()
        cog.tier_playoff_hunt.assert_not_called()
