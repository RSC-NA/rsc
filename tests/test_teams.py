from unittest.mock import AsyncMock, MagicMock, patch

import discord
import pytest
from rscapi.exceptions import ApiException, BadRequestException, NotFoundException
from rscapi.models.team import Team
from rscapi.models.team_list import TeamList

from rsc.enums import Status, SubStatus
from rsc.exceptions import RscException
from rsc.teams.teams import TeamMixIn

GUILD_ID = 395806681994493964


def _create_mixin(**attrs):
    saved = TeamMixIn.__abstractmethods__
    TeamMixIn.__abstractmethods__ = frozenset()
    try:
        m = object.__new__(TeamMixIn)
    finally:
        TeamMixIn.__abstractmethods__ = saved
    for k, v in attrs.items():
        setattr(m, k, v)
    return m


def _make_team_list(id=1, name="Team Alpha", tier_name="Premier", tier_pos=1, franchise_name="Eagles", gm_discord_id=999):
    t = MagicMock(spec=TeamList)
    t.id = id
    t.name = name
    t.tier = MagicMock()
    t.tier.name = tier_name
    t.tier.position = tier_pos
    t.franchise = MagicMock()
    t.franchise.id = 10
    t.franchise.name = franchise_name
    t.franchise.gm = MagicMock()
    t.franchise.gm.discord_id = gm_discord_id
    return t


def _make_league_player(discord_id=111, name="Player1", team_name="Team Alpha", tier_name="Premier", tier_pos=1, captain=False, status=Status.ROSTERED, sub_status=None, franchise_name="Eagles", franchise_id=10, gm_discord_id=999, gm_name="TestGM", tier_id=1):
    p = MagicMock()
    p.id = discord_id
    p.captain = captain
    p.status = status
    p.sub_status = sub_status
    p.player = MagicMock()
    p.player.discord_id = discord_id
    p.player.name = name
    p.tier = MagicMock()
    p.tier.name = tier_name
    p.tier.position = tier_pos
    p.tier.id = tier_id
    p.team = MagicMock()
    p.team.name = team_name
    p.team.franchise = MagicMock()
    p.team.franchise.id = franchise_id
    p.team.franchise.name = franchise_name
    p.team.franchise.gm = MagicMock()
    p.team.franchise.gm.discord_id = gm_discord_id
    p.team.franchise.gm.rsc_name = gm_name
    return p


# --- Autocomplete ---


class TestTeamsAutocomplete:
    async def test_returns_matching_choices(self, mock_guild):
        mixin = _create_mixin(_team_cache={mock_guild.id: ["Alpha", "Bravo", "Charlie"]})
        interaction = MagicMock(spec=discord.Interaction)
        interaction.guild_id = mock_guild.id

        choices = await mixin.teams_autocomplete(interaction, "alph")
        names = [c.name for c in choices]
        assert "Alpha" in names
        assert "Bravo" not in names

    async def test_returns_first_25_on_empty_input(self, mock_guild):
        teams = [f"Team{i}" for i in range(30)]
        mixin = _create_mixin(_team_cache={mock_guild.id: teams})
        interaction = MagicMock(spec=discord.Interaction)
        interaction.guild_id = mock_guild.id

        choices = await mixin.teams_autocomplete(interaction, "")
        assert len(choices) == 25

    async def test_returns_empty_when_no_guild(self):
        mixin = _create_mixin(_team_cache={})
        interaction = MagicMock(spec=discord.Interaction)
        interaction.guild_id = None

        choices = await mixin.teams_autocomplete(interaction, "test")
        assert choices == []

    async def test_returns_empty_when_cache_missing(self, mock_guild):
        mixin = _create_mixin(_team_cache={})
        interaction = MagicMock(spec=discord.Interaction)
        interaction.guild_id = mock_guild.id

        choices = await mixin.teams_autocomplete(interaction, "test")
        assert choices == []

    async def test_limits_to_25(self, mock_guild):
        teams = [f"Team{i}" for i in range(30)]
        mixin = _create_mixin(_team_cache={mock_guild.id: teams})
        interaction = MagicMock(spec=discord.Interaction)
        interaction.guild_id = mock_guild.id

        choices = await mixin.teams_autocomplete(interaction, "Team")
        assert len(choices) == 25


# --- teams_in_same_tier ---


class TestTeamsInSameTier:
    async def test_returns_true_for_same_tier(self):
        t1 = _make_team_list(name="A", tier_name="Premier")
        t2 = _make_team_list(name="B", tier_name="Premier")
        mixin = _create_mixin()
        assert await mixin.teams_in_same_tier([t1, t2]) is True

    async def test_returns_false_for_different_tiers(self):
        t1 = _make_team_list(name="A", tier_name="Premier")
        t2 = _make_team_list(name="B", tier_name="Master")
        mixin = _create_mixin()
        assert await mixin.teams_in_same_tier([t1, t2]) is False

    async def test_returns_true_for_single_team(self):
        t1 = _make_team_list(name="A", tier_name="Premier")
        mixin = _create_mixin()
        assert await mixin.teams_in_same_tier([t1]) is True

    async def test_works_with_team_model(self):
        t1 = MagicMock(spec=Team)
        t1.tier = "Premier"
        t1.name = "A"
        t2 = MagicMock(spec=Team)
        t2.tier = "Premier"
        t2.name = "B"
        mixin = _create_mixin()
        assert await mixin.teams_in_same_tier([t1, t2]) is True

    async def test_raises_when_team_list_has_no_tier(self):
        t = _make_team_list(name="A")
        t.tier = None
        mixin = _create_mixin()
        with pytest.raises(ValueError, match="no tier"):
            await mixin.teams_in_same_tier([t])


# --- team_id_by_name ---


class TestTeamIdByName:
    async def test_returns_id(self, mock_guild):
        t = _make_team_list(id=42, name="Alpha")
        mixin = _create_mixin(
            _api_conf={mock_guild.id: MagicMock()},
            _league={mock_guild.id: 1},
            _team_cache={},
        )
        with patch("rsc.teams.teams.ApiClient") as mock_client:
            mock_api = AsyncMock()
            mock_api.teams_list.return_value = [t]
            mock_client.return_value.__aenter__ = AsyncMock(return_value=MagicMock())
            mock_client.return_value.__aexit__ = AsyncMock(return_value=False)
            with patch("rsc.teams.teams.TeamsApi", return_value=mock_api):
                result = await mixin.team_id_by_name(mock_guild, "Alpha")

        assert result == 42

    async def test_raises_when_not_found(self, mock_guild):
        mixin = _create_mixin(
            _api_conf={mock_guild.id: MagicMock()},
            _league={mock_guild.id: 1},
            _team_cache={},
        )
        with patch("rsc.teams.teams.ApiClient") as mock_client:
            mock_api = AsyncMock()
            mock_api.teams_list.return_value = []
            mock_client.return_value.__aenter__ = AsyncMock(return_value=MagicMock())
            mock_client.return_value.__aexit__ = AsyncMock(return_value=False)
            with patch("rsc.teams.teams.TeamsApi", return_value=mock_api):
                with pytest.raises(ValueError, match="No team found"):
                    await mixin.team_id_by_name(mock_guild, "None")

    async def test_exact_match_when_multiple(self, mock_guild):
        t1 = _make_team_list(id=1, name="Alpha")
        t2 = _make_team_list(id=2, name="Alpha Prime")
        mixin = _create_mixin(
            _api_conf={mock_guild.id: MagicMock()},
            _league={mock_guild.id: 1},
            _team_cache={},
        )
        with patch("rsc.teams.teams.ApiClient") as mock_client:
            mock_api = AsyncMock()
            mock_api.teams_list.return_value = [t1, t2]
            mock_client.return_value.__aenter__ = AsyncMock(return_value=MagicMock())
            mock_client.return_value.__aexit__ = AsyncMock(return_value=False)
            with patch("rsc.teams.teams.TeamsApi", return_value=mock_api):
                result = await mixin.team_id_by_name(mock_guild, "Alpha")

        assert result == 1

    async def test_raises_when_multiple_no_exact_match(self, mock_guild):
        t1 = _make_team_list(id=1, name="Alpha A")
        t2 = _make_team_list(id=2, name="Alpha B")
        mixin = _create_mixin(
            _api_conf={mock_guild.id: MagicMock()},
            _league={mock_guild.id: 1},
            _team_cache={},
        )
        with patch("rsc.teams.teams.ApiClient") as mock_client:
            mock_api = AsyncMock()
            mock_api.teams_list.return_value = [t1, t2]
            mock_client.return_value.__aenter__ = AsyncMock(return_value=MagicMock())
            mock_client.return_value.__aexit__ = AsyncMock(return_value=False)
            with patch("rsc.teams.teams.TeamsApi", return_value=mock_api):
                with pytest.raises(ValueError, match="More than one"):
                    await mixin.team_id_by_name(mock_guild, "Alpha")

    async def test_raises_when_no_id(self, mock_guild):
        t = _make_team_list(id=None, name="Alpha")
        mixin = _create_mixin(
            _api_conf={mock_guild.id: MagicMock()},
            _league={mock_guild.id: 1},
            _team_cache={},
        )
        with patch("rsc.teams.teams.ApiClient") as mock_client:
            mock_api = AsyncMock()
            mock_api.teams_list.return_value = [t]
            mock_client.return_value.__aenter__ = AsyncMock(return_value=MagicMock())
            mock_client.return_value.__aexit__ = AsyncMock(return_value=False)
            with patch("rsc.teams.teams.TeamsApi", return_value=mock_api):
                with pytest.raises(ValueError, match="no ID"):
                    await mixin.team_id_by_name(mock_guild, "Alpha")


# --- team_captain ---


class TestTeamCaptain:
    async def test_returns_captain(self, mock_guild):
        p1 = _make_league_player(discord_id=111, name="P1", captain=False, team_name="Alpha")
        p2 = _make_league_player(discord_id=222, name="Captain", captain=True, team_name="Alpha")
        mixin = _create_mixin()
        mixin.players = AsyncMock(return_value=[p1, p2])

        result = await mixin.team_captain(mock_guild, "Alpha")
        assert result is p2

    async def test_returns_none_when_no_captain(self, mock_guild):
        p1 = _make_league_player(discord_id=111, captain=False, team_name="Alpha")
        mixin = _create_mixin()
        mixin.players = AsyncMock(return_value=[p1])

        result = await mixin.team_captain(mock_guild, "Alpha")
        assert result is None

    async def test_returns_none_when_no_players(self, mock_guild):
        mixin = _create_mixin()
        mixin.players = AsyncMock(return_value=[])

        result = await mixin.team_captain(mock_guild, "Alpha")
        assert result is None

    async def test_filters_by_team_name(self, mock_guild):
        p1 = _make_league_player(discord_id=111, captain=True, team_name="Bravo")
        mixin = _create_mixin()
        mixin.players = AsyncMock(return_value=[p1])

        result = await mixin.team_captain(mock_guild, "Alpha")
        assert result is None


# --- tier_captains ---


class TestTierCaptains:
    async def test_returns_captains_sorted(self, mock_guild):
        p1 = _make_league_player(discord_id=111, name="Cpt1", captain=True, team_name="Bravo", status=Status.ROSTERED)
        p2 = _make_league_player(discord_id=222, name="Cpt2", captain=True, team_name="Alpha", status=Status.ROSTERED)
        p3 = _make_league_player(discord_id=333, name="NotCpt", captain=False, team_name="Charlie", status=Status.ROSTERED)
        mixin = _create_mixin()
        mixin.players = AsyncMock(return_value=[p1, p2, p3])

        result = await mixin.tier_captains(mock_guild, "Premier")
        assert len(result) == 2
        assert result[0].team.name == "Alpha"
        assert result[1].team.name == "Bravo"

    async def test_returns_empty_when_no_players(self, mock_guild):
        mixin = _create_mixin()
        mixin.players = AsyncMock(return_value=[])

        result = await mixin.tier_captains(mock_guild, "Premier")
        assert result == []


# --- franchise_captains ---


class TestFranchiseCaptains:
    async def test_returns_captains_sorted_by_tier_pos(self, mock_guild):
        p1 = _make_league_player(discord_id=111, captain=True, tier_pos=1, status=Status.ROSTERED)
        p2 = _make_league_player(discord_id=222, captain=True, tier_pos=3, status=Status.ROSTERED)
        mixin = _create_mixin()
        mixin.players = AsyncMock(return_value=[p1, p2])

        result = await mixin.franchise_captains(mock_guild, "Eagles")
        assert len(result) == 2
        # Sorted by tier.position descending
        assert result[0].tier.position == 3
        assert result[1].tier.position == 1

    async def test_returns_empty_when_no_players(self, mock_guild):
        mixin = _create_mixin()
        mixin.players = AsyncMock(return_value=[])

        result = await mixin.franchise_captains(mock_guild, "Eagles")
        assert result == []


# --- build_franchise_teams_embed ---


class TestBuildFranchiseTeamsEmbed:
    async def test_builds_embed(self, mock_guild):
        t1 = _make_team_list(name="Team A", tier_name="Premier", tier_pos=2)
        t2 = _make_team_list(name="Team B", tier_name="Master", tier_pos=1)
        mixin = _create_mixin()
        mixin.franchise_logo = AsyncMock(return_value=None)

        embed = await mixin.build_franchise_teams_embed(mock_guild, [t1, t2])
        assert isinstance(embed, discord.Embed)
        assert "Eagles" in embed.title

    async def test_raises_on_empty_teams(self, mock_guild):
        mixin = _create_mixin()
        with pytest.raises(ValueError, match="No teams"):
            await mixin.build_franchise_teams_embed(mock_guild, [])

    async def test_raises_when_team_has_no_name(self, mock_guild):
        t = _make_team_list(name=None)
        mixin = _create_mixin()
        with pytest.raises(AttributeError, match="no name"):
            await mixin.build_franchise_teams_embed(mock_guild, [t])


# --- API wrappers ---


class TestTeamsApi:
    async def test_returns_teams(self, mock_guild):
        t1 = _make_team_list(name="Alpha")
        mixin = _create_mixin(
            _api_conf={mock_guild.id: MagicMock()},
            _league={mock_guild.id: 1},
            _team_cache={},
        )
        with patch("rsc.teams.teams.ApiClient") as mock_client:
            mock_api = AsyncMock()
            mock_api.teams_list.return_value = [t1]
            mock_client.return_value.__aenter__ = AsyncMock(return_value=MagicMock())
            mock_client.return_value.__aexit__ = AsyncMock(return_value=False)
            with patch("rsc.teams.teams.TeamsApi", return_value=mock_api):
                result = await mixin.teams(mock_guild)

        assert len(result) == 1

    async def test_populates_cache(self, mock_guild):
        t1 = _make_team_list(name="Alpha")
        t2 = _make_team_list(name="Bravo")
        mixin = _create_mixin(
            _api_conf={mock_guild.id: MagicMock()},
            _league={mock_guild.id: 1},
            _team_cache={},
        )
        with patch("rsc.teams.teams.ApiClient") as mock_client:
            mock_api = AsyncMock()
            mock_api.teams_list.return_value = [t1, t2]
            mock_client.return_value.__aenter__ = AsyncMock(return_value=MagicMock())
            mock_client.return_value.__aexit__ = AsyncMock(return_value=False)
            with patch("rsc.teams.teams.TeamsApi", return_value=mock_api):
                await mixin.teams(mock_guild)

        assert "Alpha" in mixin._team_cache[mock_guild.id]
        assert "Bravo" in mixin._team_cache[mock_guild.id]

    async def test_raises_when_team_has_no_name(self, mock_guild):
        t = MagicMock(spec=TeamList)
        t.name = None
        mixin = _create_mixin(
            _api_conf={mock_guild.id: MagicMock()},
            _league={mock_guild.id: 1},
            _team_cache={},
        )
        with patch("rsc.teams.teams.ApiClient") as mock_client:
            mock_api = AsyncMock()
            mock_api.teams_list.return_value = [t]
            mock_client.return_value.__aenter__ = AsyncMock(return_value=MagicMock())
            mock_client.return_value.__aexit__ = AsyncMock(return_value=False)
            with patch("rsc.teams.teams.TeamsApi", return_value=mock_api):
                with pytest.raises(AttributeError, match="no name"):
                    await mixin.teams(mock_guild)

    async def test_raises_rsc_exception_on_api_error(self, mock_guild):
        mixin = _create_mixin(
            _api_conf={mock_guild.id: MagicMock()},
            _league={mock_guild.id: 1},
            _team_cache={},
        )
        with patch("rsc.teams.teams.ApiClient") as mock_client:
            mock_api = AsyncMock()
            mock_api.teams_list.side_effect = ApiException(status=500, reason="Error")
            mock_client.return_value.__aenter__ = AsyncMock(return_value=MagicMock())
            mock_client.return_value.__aexit__ = AsyncMock(return_value=False)
            with patch("rsc.teams.teams.TeamsApi", return_value=mock_api):
                with pytest.raises(RscException):
                    await mixin.teams(mock_guild)


class TestTeamByIdApi:
    async def test_returns_team(self, mock_guild):
        t = MagicMock(spec=Team)
        t.id = 5
        mixin = _create_mixin(_api_conf={mock_guild.id: MagicMock()})

        with patch("rsc.teams.teams.ApiClient") as mock_client:
            mock_api = AsyncMock()
            mock_api.teams_read.return_value = t
            mock_client.return_value.__aenter__ = AsyncMock(return_value=MagicMock())
            mock_client.return_value.__aexit__ = AsyncMock(return_value=False)
            with patch("rsc.teams.teams.TeamsApi", return_value=mock_api):
                result = await mixin.team_by_id(mock_guild, 5)

        assert result.id == 5

    async def test_raises_rsc_exception_on_api_error(self, mock_guild):
        mixin = _create_mixin(_api_conf={mock_guild.id: MagicMock()})

        with patch("rsc.teams.teams.ApiClient") as mock_client:
            mock_api = AsyncMock()
            mock_api.teams_read.side_effect = ApiException(status=404, reason="Not Found")
            mock_client.return_value.__aenter__ = AsyncMock(return_value=MagicMock())
            mock_client.return_value.__aexit__ = AsyncMock(return_value=False)
            with patch("rsc.teams.teams.TeamsApi", return_value=mock_api):
                with pytest.raises(RscException):
                    await mixin.team_by_id(mock_guild, 999)


class TestNextMatchApi:
    async def test_returns_match(self, mock_guild):
        match = MagicMock()
        mixin = _create_mixin(_api_conf={mock_guild.id: MagicMock()})

        with patch("rsc.teams.teams.ApiClient") as mock_client:
            mock_api = AsyncMock()
            mock_api.teams_next_match.return_value = match
            mock_client.return_value.__aenter__ = AsyncMock(return_value=MagicMock())
            mock_client.return_value.__aexit__ = AsyncMock(return_value=False)
            with patch("rsc.teams.teams.TeamsApi", return_value=mock_api):
                result = await mixin.next_match(mock_guild, 1)

        assert result is match

    async def test_returns_none_on_not_found(self, mock_guild):
        mixin = _create_mixin(_api_conf={mock_guild.id: MagicMock()})

        with patch("rsc.teams.teams.ApiClient") as mock_client:
            mock_api = AsyncMock()
            mock_api.teams_next_match.side_effect = NotFoundException(status=404, reason="Not Found")
            mock_client.return_value.__aenter__ = AsyncMock(return_value=MagicMock())
            mock_client.return_value.__aexit__ = AsyncMock(return_value=False)
            with patch("rsc.teams.teams.TeamsApi", return_value=mock_api):
                result = await mixin.next_match(mock_guild, 999)

        assert result is None

    async def test_raises_rsc_exception_on_other_error(self, mock_guild):
        mixin = _create_mixin(_api_conf={mock_guild.id: MagicMock()})

        with patch("rsc.teams.teams.ApiClient") as mock_client:
            mock_api = AsyncMock()
            mock_api.teams_next_match.side_effect = ApiException(status=500, reason="Error")
            mock_client.return_value.__aenter__ = AsyncMock(return_value=MagicMock())
            mock_client.return_value.__aexit__ = AsyncMock(return_value=False)
            with patch("rsc.teams.teams.TeamsApi", return_value=mock_api):
                with pytest.raises(RscException):
                    await mixin.next_match(mock_guild, 1)


class TestSeasonMatchesApi:
    async def test_returns_sorted_matches(self, mock_guild):
        m1 = MagicMock()
        m1.day = 3
        m2 = MagicMock()
        m2.day = 1
        mixin = _create_mixin(_api_conf={mock_guild.id: MagicMock()})

        with patch("rsc.teams.teams.ApiClient") as mock_client:
            mock_api = AsyncMock()
            mock_api.teams_season_matches.return_value = [m1, m2]
            mock_client.return_value.__aenter__ = AsyncMock(return_value=MagicMock())
            mock_client.return_value.__aexit__ = AsyncMock(return_value=False)
            with patch("rsc.teams.teams.TeamsApi", return_value=mock_api):
                result = await mixin.season_matches(mock_guild, id=1, season=25)

        assert result[0].day == 1
        assert result[1].day == 3


class TestCreateTeamApi:
    async def test_creates_team(self, mock_guild):
        created = MagicMock()
        mixin = _create_mixin(
            _api_conf={mock_guild.id: MagicMock()},
            _league={mock_guild.id: 1},
        )

        with patch("rsc.teams.teams.ApiClient") as mock_client:
            mock_api = AsyncMock()
            mock_api.teams_create.return_value = created
            mock_client.return_value.__aenter__ = AsyncMock(return_value=MagicMock())
            mock_client.return_value.__aexit__ = AsyncMock(return_value=False)
            with patch("rsc.teams.teams.TeamsApi", return_value=mock_api):
                result = await mixin.create_team(mock_guild, name="New Team", franchise="Eagles", tier="Premier")

        assert result is created

    async def test_raises_rsc_exception_on_api_error(self, mock_guild):
        mixin = _create_mixin(
            _api_conf={mock_guild.id: MagicMock()},
            _league={mock_guild.id: 1},
        )

        with patch("rsc.teams.teams.ApiClient") as mock_client:
            mock_api = AsyncMock()
            mock_api.teams_create.side_effect = ApiException(status=400, reason="Bad Request")
            mock_client.return_value.__aenter__ = AsyncMock(return_value=MagicMock())
            mock_client.return_value.__aexit__ = AsyncMock(return_value=False)
            with patch("rsc.teams.teams.TeamsApi", return_value=mock_api):
                with pytest.raises(RscException):
                    await mixin.create_team(mock_guild, name="Bad", franchise="X", tier="Y")


class TestDeleteTeamApi:
    async def test_deletes_team(self, mock_guild):
        mixin = _create_mixin(_api_conf={mock_guild.id: MagicMock()})

        with patch("rsc.teams.teams.ApiClient") as mock_client:
            mock_api = AsyncMock()
            mock_api.teams_delete.return_value = None
            mock_client.return_value.__aenter__ = AsyncMock(return_value=MagicMock())
            mock_client.return_value.__aexit__ = AsyncMock(return_value=False)
            with patch("rsc.teams.teams.TeamsApi", return_value=mock_api):
                await mixin.delete_team(mock_guild, team_id=5)

        mock_api.teams_delete.assert_awaited_once_with(5)

    async def test_raises_rsc_exception_on_api_error(self, mock_guild):
        mixin = _create_mixin(_api_conf={mock_guild.id: MagicMock()})

        with patch("rsc.teams.teams.ApiClient") as mock_client:
            mock_api = AsyncMock()
            mock_api.teams_delete.side_effect = ApiException(status=404, reason="Not Found")
            mock_client.return_value.__aenter__ = AsyncMock(return_value=MagicMock())
            mock_client.return_value.__aexit__ = AsyncMock(return_value=False)
            with patch("rsc.teams.teams.TeamsApi", return_value=mock_api):
                with pytest.raises(RscException):
                    await mixin.delete_team(mock_guild, team_id=999)
