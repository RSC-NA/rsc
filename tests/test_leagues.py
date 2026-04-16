from datetime import datetime, timezone
from unittest.mock import AsyncMock, MagicMock, patch

import discord
import pytest
from rscapi.exceptions import ApiException

from rsc.enums import Status
from rsc.exceptions import RscException
from rsc.leagues.leagues import LeagueMixIn

GUILD_ID = 395806681994493964


def _create_mixin(**attrs):
    saved = LeagueMixIn.__abstractmethods__
    LeagueMixIn.__abstractmethods__ = frozenset()
    try:
        m = object.__new__(LeagueMixIn)
    finally:
        LeagueMixIn.__abstractmethods__ = saved
    for k, v in attrs.items():
        setattr(m, k, v)
    return m


# --- leagues API ---


class TestLeaguesApi:
    async def test_returns_leagues(self, mock_guild):
        leagues = [MagicMock(), MagicMock()]
        mixin = _create_mixin(_api_conf={mock_guild.id: MagicMock()})

        with patch("rsc.leagues.leagues.ApiClient") as mock_client:
            mock_api = AsyncMock()
            mock_api.leagues_list.return_value = leagues
            mock_client.return_value.__aenter__ = AsyncMock(return_value=MagicMock())
            mock_client.return_value.__aexit__ = AsyncMock(return_value=False)
            with patch("rsc.leagues.leagues.LeaguesApi", return_value=mock_api):
                result = await mixin.leagues(mock_guild)

        assert len(result) == 2

    async def test_raises_rsc_exception(self, mock_guild):
        mixin = _create_mixin(_api_conf={mock_guild.id: MagicMock()})

        with patch("rsc.leagues.leagues.ApiClient") as mock_client:
            mock_api = AsyncMock()
            mock_api.leagues_list.side_effect = ApiException(status=500, reason="Error")
            mock_client.return_value.__aenter__ = AsyncMock(return_value=MagicMock())
            mock_client.return_value.__aexit__ = AsyncMock(return_value=False)
            with patch("rsc.leagues.leagues.LeaguesApi", return_value=mock_api):
                with pytest.raises(RscException):
                    await mixin.leagues(mock_guild)


# --- league API ---


class TestLeagueApi:
    async def test_returns_league(self, mock_guild):
        league = MagicMock()
        mixin = _create_mixin(
            _api_conf={mock_guild.id: MagicMock()},
            _league={mock_guild.id: 1},
        )

        with patch("rsc.leagues.leagues.ApiClient") as mock_client:
            mock_api = AsyncMock()
            mock_api.leagues_read.return_value = league
            mock_client.return_value.__aenter__ = AsyncMock(return_value=MagicMock())
            mock_client.return_value.__aexit__ = AsyncMock(return_value=False)
            with patch("rsc.leagues.leagues.LeaguesApi", return_value=mock_api):
                result = await mixin.league(mock_guild)

        assert result is league


# --- league_by_id API ---


class TestLeagueByIdApi:
    async def test_returns_league(self, mock_guild):
        league = MagicMock()
        mixin = _create_mixin(_api_conf={mock_guild.id: MagicMock()})

        with patch("rsc.leagues.leagues.ApiClient") as mock_client:
            mock_api = AsyncMock()
            mock_api.leagues_read.return_value = league
            mock_client.return_value.__aenter__ = AsyncMock(return_value=MagicMock())
            mock_client.return_value.__aexit__ = AsyncMock(return_value=False)
            with patch("rsc.leagues.leagues.LeaguesApi", return_value=mock_api):
                result = await mixin.league_by_id(mock_guild, id=42)

        assert result is league


# --- current_season API ---


class TestCurrentSeasonApi:
    async def test_returns_season(self, mock_guild):
        season = MagicMock()
        mixin = _create_mixin(
            _api_conf={mock_guild.id: MagicMock()},
            _league={mock_guild.id: 1},
        )

        with patch("rsc.leagues.leagues.ApiClient") as mock_client:
            mock_api = AsyncMock()
            mock_api.leagues_current_season.return_value = season
            mock_client.return_value.__aenter__ = AsyncMock(return_value=MagicMock())
            mock_client.return_value.__aexit__ = AsyncMock(return_value=False)
            with patch("rsc.leagues.leagues.LeaguesApi", return_value=mock_api):
                result = await mixin.current_season(mock_guild)

        assert result is season


# --- league_seasons API ---


class TestLeagueSeasonsApi:
    async def test_returns_seasons(self, mock_guild):
        seasons = [MagicMock(), MagicMock()]
        mixin = _create_mixin(
            _api_conf={mock_guild.id: MagicMock()},
            _league={mock_guild.id: 1},
        )

        with patch("rsc.leagues.leagues.ApiClient") as mock_client:
            mock_api = AsyncMock()
            mock_api.leagues_seasons.return_value = seasons
            mock_client.return_value.__aenter__ = AsyncMock(return_value=MagicMock())
            mock_client.return_value.__aexit__ = AsyncMock(return_value=False)
            with patch("rsc.leagues.leagues.LeaguesApi", return_value=mock_api):
                result = await mixin.league_seasons(mock_guild)

        assert len(result) == 2


# --- players API ---


class TestPlayersApi:
    async def test_returns_players(self, mock_guild):
        resp = MagicMock()
        resp.results = [MagicMock()]
        mixin = _create_mixin(
            _api_conf={mock_guild.id: MagicMock()},
            _league={mock_guild.id: 1},
        )

        with patch("rsc.leagues.leagues.ApiClient") as mock_client:
            mock_api = AsyncMock()
            mock_api.league_players_list.return_value = resp
            mock_client.return_value.__aenter__ = AsyncMock(return_value=MagicMock())
            mock_client.return_value.__aexit__ = AsyncMock(return_value=False)
            with patch("rsc.leagues.leagues.LeaguePlayersApi", return_value=mock_api):
                result = await mixin.players(mock_guild)

        assert len(result) == 1

    async def test_raises_rsc_exception(self, mock_guild):
        mixin = _create_mixin(
            _api_conf={mock_guild.id: MagicMock()},
            _league={mock_guild.id: 1},
        )

        with patch("rsc.leagues.leagues.ApiClient") as mock_client:
            mock_api = AsyncMock()
            mock_api.league_players_list.side_effect = ApiException(status=500, reason="Error")
            mock_client.return_value.__aenter__ = AsyncMock(return_value=MagicMock())
            mock_client.return_value.__aexit__ = AsyncMock(return_value=False)
            with patch("rsc.leagues.leagues.LeaguePlayersApi", return_value=mock_api):
                with pytest.raises(RscException):
                    await mixin.players(mock_guild)

    async def test_passes_status_filter(self, mock_guild):
        resp = MagicMock()
        resp.results = []
        mixin = _create_mixin(
            _api_conf={mock_guild.id: MagicMock()},
            _league={mock_guild.id: 1},
        )

        with patch("rsc.leagues.leagues.ApiClient") as mock_client:
            mock_api = AsyncMock()
            mock_api.league_players_list.return_value = resp
            mock_client.return_value.__aenter__ = AsyncMock(return_value=MagicMock())
            mock_client.return_value.__aexit__ = AsyncMock(return_value=False)
            with patch("rsc.leagues.leagues.LeaguePlayersApi", return_value=mock_api):
                await mixin.players(mock_guild, status=Status.ROSTERED)

        call_kwargs = mock_api.league_players_list.call_args[1]
        assert call_kwargs["status"] == str(Status.ROSTERED)


# --- total_players API ---


class TestTotalPlayersApi:
    async def test_returns_count(self, mock_guild):
        resp = MagicMock()
        resp.count = 42
        mixin = _create_mixin(
            _api_conf={mock_guild.id: MagicMock()},
            _league={mock_guild.id: 1},
        )

        with patch("rsc.leagues.leagues.ApiClient") as mock_client:
            mock_api = AsyncMock()
            mock_api.league_players_list.return_value = resp
            mock_client.return_value.__aenter__ = AsyncMock(return_value=MagicMock())
            mock_client.return_value.__aexit__ = AsyncMock(return_value=False)
            with patch("rsc.leagues.leagues.LeaguePlayersApi", return_value=mock_api):
                result = await mixin.total_players(mock_guild)

        assert result == 42


# --- update_league_player ---


class TestUpdateLeaguePlayer:
    async def test_updates_player(self, mock_guild, mock_executor):
        updated = MagicMock()
        mixin = _create_mixin(
            _api_conf={mock_guild.id: MagicMock()},
            _league={mock_guild.id: 1},
        )

        with patch("rsc.leagues.leagues.ApiClient") as mock_client:
            mock_api = AsyncMock()
            mock_api.league_players_partial_update.return_value = updated
            mock_client.return_value.__aenter__ = AsyncMock(return_value=MagicMock())
            mock_client.return_value.__aexit__ = AsyncMock(return_value=False)
            with patch("rsc.leagues.leagues.LeaguePlayersApi", return_value=mock_api):
                result = await mixin.update_league_player(
                    mock_guild,
                    player_id=1,
                    executor=mock_executor,
                    base_mmr=1000,
                    current_mmr=1050,
                )

        assert result is updated

    async def test_raises_on_invalid_contract_length(self, mock_guild, mock_executor):
        mixin = _create_mixin(
            _api_conf={mock_guild.id: MagicMock()},
            _league={mock_guild.id: 1},
        )

        with pytest.raises(ValueError, match="Contract Length"):
            await mixin.update_league_player(
                mock_guild,
                player_id=1,
                executor=mock_executor,
                contract_length=5,
            )

    async def test_raises_rsc_exception_on_api_error(self, mock_guild, mock_executor):
        mixin = _create_mixin(
            _api_conf={mock_guild.id: MagicMock()},
            _league={mock_guild.id: 1},
        )

        with patch("rsc.leagues.leagues.ApiClient") as mock_client:
            mock_api = AsyncMock()
            mock_api.league_players_partial_update.side_effect = ApiException(status=400, reason="Bad")
            mock_client.return_value.__aenter__ = AsyncMock(return_value=MagicMock())
            mock_client.return_value.__aexit__ = AsyncMock(return_value=False)
            with patch("rsc.leagues.leagues.LeaguePlayersApi", return_value=mock_api):
                with pytest.raises(RscException):
                    await mixin.update_league_player(
                        mock_guild,
                        player_id=1,
                        executor=mock_executor,
                        base_mmr=500,
                    )

    async def test_sets_status(self, mock_guild, mock_executor):
        updated = MagicMock()
        mixin = _create_mixin(
            _api_conf={mock_guild.id: MagicMock()},
            _league={mock_guild.id: 1},
        )

        with patch("rsc.leagues.leagues.ApiClient") as mock_client:
            mock_api = AsyncMock()
            mock_api.league_players_partial_update.return_value = updated
            mock_client.return_value.__aenter__ = AsyncMock(return_value=MagicMock())
            mock_client.return_value.__aexit__ = AsyncMock(return_value=False)
            with patch("rsc.leagues.leagues.LeaguePlayersApi", return_value=mock_api):
                result = await mixin.update_league_player(
                    mock_guild,
                    player_id=1,
                    executor=mock_executor,
                    status=Status.IR,
                )

        assert result is updated
