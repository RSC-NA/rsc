from unittest.mock import AsyncMock, MagicMock, patch

import discord
import pytest
from rscapi.exceptions import ApiException
from rscapi.models.season import Season

from rsc.exceptions import LeagueNotConfigured, RscException
from rsc.seasons.seasons import SeasonsMixIn

GUILD_ID = 395806681994493964


def _create_mixin(**attrs):
    saved = SeasonsMixIn.__abstractmethods__
    SeasonsMixIn.__abstractmethods__ = frozenset()
    try:
        m = object.__new__(SeasonsMixIn)
    finally:
        SeasonsMixIn.__abstractmethods__ = saved
    for k, v in attrs.items():
        setattr(m, k, v)
    return m


def _make_season(id=1, number=25, league_id=1):
    s = MagicMock(spec=Season)
    s.id = id
    s.number = number
    s.league = MagicMock()
    s.league.id = league_id
    return s


# --- next_season ---


class TestNextSeason:
    async def test_returns_latest_season(self, mock_guild):
        s1 = _make_season(id=1, number=24)
        s2 = _make_season(id=2, number=25)
        s3 = _make_season(id=3, number=23)
        mixin = _create_mixin(
            _api_conf={mock_guild.id: MagicMock()},
            _league={mock_guild.id: 1},
        )
        with patch("rsc.seasons.seasons.ApiClient") as mock_client:
            mock_api = AsyncMock()
            mock_api.seasons_list.return_value = [s1, s2, s3]
            mock_client.return_value.__aenter__ = AsyncMock(return_value=MagicMock())
            mock_client.return_value.__aexit__ = AsyncMock(return_value=False)
            with patch("rsc.seasons.seasons.SeasonsApi", return_value=mock_api):
                result = await mixin.next_season(mock_guild)

        assert result is s2

    async def test_returns_none_when_no_seasons(self, mock_guild):
        mixin = _create_mixin(
            _api_conf={mock_guild.id: MagicMock()},
            _league={mock_guild.id: 1},
        )
        with patch("rsc.seasons.seasons.ApiClient") as mock_client:
            mock_api = AsyncMock()
            mock_api.seasons_list.return_value = []
            mock_client.return_value.__aenter__ = AsyncMock(return_value=MagicMock())
            mock_client.return_value.__aexit__ = AsyncMock(return_value=False)
            with patch("rsc.seasons.seasons.SeasonsApi", return_value=mock_api):
                result = await mixin.next_season(mock_guild)

        assert result is None

    async def test_returns_none_when_no_league_seasons(self, mock_guild):
        s1 = _make_season(id=1, number=24, league_id=99)
        mixin = _create_mixin(
            _api_conf={mock_guild.id: MagicMock()},
            _league={mock_guild.id: 1},
        )
        with patch("rsc.seasons.seasons.ApiClient") as mock_client:
            mock_api = AsyncMock()
            mock_api.seasons_list.return_value = [s1]
            mock_client.return_value.__aenter__ = AsyncMock(return_value=MagicMock())
            mock_client.return_value.__aexit__ = AsyncMock(return_value=False)
            with patch("rsc.seasons.seasons.SeasonsApi", return_value=mock_api):
                result = await mixin.next_season(mock_guild)

        assert result is None

    async def test_raises_when_no_league(self, mock_guild):
        mixin = _create_mixin(
            _api_conf={mock_guild.id: MagicMock()},
            _league={mock_guild.id: None},
        )
        with pytest.raises(LeagueNotConfigured):
            await mixin.next_season(mock_guild)


# --- seasons API ---


class TestSeasonsApi:
    async def test_returns_seasons(self, mock_guild):
        s1 = _make_season(id=1, number=25)
        mixin = _create_mixin(
            _api_conf={mock_guild.id: MagicMock()},
            _league={mock_guild.id: 1},
        )
        with patch("rsc.seasons.seasons.ApiClient") as mock_client:
            mock_api = AsyncMock()
            mock_api.seasons_list.return_value = [s1]
            mock_client.return_value.__aenter__ = AsyncMock(return_value=MagicMock())
            mock_client.return_value.__aexit__ = AsyncMock(return_value=False)
            with patch("rsc.seasons.seasons.SeasonsApi", return_value=mock_api):
                result = await mixin.seasons(mock_guild)

        assert len(result) == 1
        assert result[0] is s1

    async def test_passes_filters(self, mock_guild):
        mixin = _create_mixin(
            _api_conf={mock_guild.id: MagicMock()},
            _league={mock_guild.id: 1},
        )
        with patch("rsc.seasons.seasons.ApiClient") as mock_client:
            mock_api = AsyncMock()
            mock_api.seasons_list.return_value = []
            mock_client.return_value.__aenter__ = AsyncMock(return_value=MagicMock())
            mock_client.return_value.__aexit__ = AsyncMock(return_value=False)
            with patch("rsc.seasons.seasons.SeasonsApi", return_value=mock_api):
                await mixin.seasons(mock_guild, number=25, current=True)

        mock_api.seasons_list.assert_awaited_once_with(league=1, number=25, current=True)

    async def test_raises_rsc_exception_on_api_error(self, mock_guild):
        mixin = _create_mixin(
            _api_conf={mock_guild.id: MagicMock()},
            _league={mock_guild.id: 1},
        )
        with patch("rsc.seasons.seasons.ApiClient") as mock_client:
            mock_api = AsyncMock()
            mock_api.seasons_list.side_effect = ApiException(status=500, reason="Error")
            mock_client.return_value.__aenter__ = AsyncMock(return_value=MagicMock())
            mock_client.return_value.__aexit__ = AsyncMock(return_value=False)
            with patch("rsc.seasons.seasons.SeasonsApi", return_value=mock_api):
                with pytest.raises(RscException):
                    await mixin.seasons(mock_guild)


class TestSeasonByIdApi:
    async def test_returns_season(self, mock_guild):
        s = _make_season(id=5, number=25)
        mixin = _create_mixin(_api_conf={mock_guild.id: MagicMock()})

        with patch("rsc.seasons.seasons.ApiClient") as mock_client:
            mock_api = AsyncMock()
            mock_api.seasons_read.return_value = s
            mock_client.return_value.__aenter__ = AsyncMock(return_value=MagicMock())
            mock_client.return_value.__aexit__ = AsyncMock(return_value=False)
            with patch("rsc.seasons.seasons.SeasonsApi", return_value=mock_api):
                result = await mixin.season_by_id(mock_guild, 5)

        assert result is s
        mock_api.seasons_read.assert_awaited_once_with(5)

    async def test_raises_rsc_exception_on_api_error(self, mock_guild):
        mixin = _create_mixin(_api_conf={mock_guild.id: MagicMock()})

        with patch("rsc.seasons.seasons.ApiClient") as mock_client:
            mock_api = AsyncMock()
            mock_api.seasons_read.side_effect = ApiException(status=404, reason="Not Found")
            mock_client.return_value.__aenter__ = AsyncMock(return_value=MagicMock())
            mock_client.return_value.__aexit__ = AsyncMock(return_value=False)
            with patch("rsc.seasons.seasons.SeasonsApi", return_value=mock_api):
                with pytest.raises(RscException):
                    await mixin.season_by_id(mock_guild, 999)


class TestPlayerIntentsApi:
    async def test_returns_intents(self, mock_guild):
        intent = MagicMock()
        mixin = _create_mixin(_api_conf={mock_guild.id: MagicMock()})

        with patch("rsc.seasons.seasons.ApiClient") as mock_client:
            mock_api = AsyncMock()
            mock_api.seasons_player_intents.return_value = [intent]
            mock_client.return_value.__aenter__ = AsyncMock(return_value=MagicMock())
            mock_client.return_value.__aexit__ = AsyncMock(return_value=False)
            with patch("rsc.seasons.seasons.SeasonsApi", return_value=mock_api):
                result = await mixin.player_intents(mock_guild, season_id=1)

        assert result == [intent]

    async def test_passes_player_discord_id(self, mock_guild, mock_member):
        mixin = _create_mixin(_api_conf={mock_guild.id: MagicMock()})

        with patch("rsc.seasons.seasons.ApiClient") as mock_client:
            mock_api = AsyncMock()
            mock_api.seasons_player_intents.return_value = []
            mock_client.return_value.__aenter__ = AsyncMock(return_value=MagicMock())
            mock_client.return_value.__aexit__ = AsyncMock(return_value=False)
            with patch("rsc.seasons.seasons.SeasonsApi", return_value=mock_api):
                await mixin.player_intents(mock_guild, season_id=1, player=mock_member, returning=True, missing=False)

        mock_api.seasons_player_intents.assert_awaited_once_with(
            1,
            discord_id=mock_member.id,
            returning=True,
            missing=False,
        )

    async def test_passes_none_when_no_player(self, mock_guild):
        mixin = _create_mixin(_api_conf={mock_guild.id: MagicMock()})

        with patch("rsc.seasons.seasons.ApiClient") as mock_client:
            mock_api = AsyncMock()
            mock_api.seasons_player_intents.return_value = []
            mock_client.return_value.__aenter__ = AsyncMock(return_value=MagicMock())
            mock_client.return_value.__aexit__ = AsyncMock(return_value=False)
            with patch("rsc.seasons.seasons.SeasonsApi", return_value=mock_api):
                await mixin.player_intents(mock_guild, season_id=1)

        mock_api.seasons_player_intents.assert_awaited_once_with(
            1,
            discord_id=None,
            returning=None,
            missing=None,
        )

    async def test_raises_rsc_exception_on_api_error(self, mock_guild):
        mixin = _create_mixin(_api_conf={mock_guild.id: MagicMock()})

        with patch("rsc.seasons.seasons.ApiClient") as mock_client:
            mock_api = AsyncMock()
            mock_api.seasons_player_intents.side_effect = ApiException(status=500, reason="Error")
            mock_client.return_value.__aenter__ = AsyncMock(return_value=MagicMock())
            mock_client.return_value.__aexit__ = AsyncMock(return_value=False)
            with patch("rsc.seasons.seasons.SeasonsApi", return_value=mock_api):
                with pytest.raises(RscException):
                    await mixin.player_intents(mock_guild, season_id=1)


class TestFranchiseStandingsApi:
    async def test_returns_standings(self, mock_guild):
        standing = MagicMock()
        mixin = _create_mixin(_api_conf={mock_guild.id: MagicMock()})

        with patch("rsc.seasons.seasons.ApiClient") as mock_client:
            mock_api = AsyncMock()
            mock_api.seasons_franchise_standings.return_value = [standing]
            mock_client.return_value.__aenter__ = AsyncMock(return_value=MagicMock())
            mock_client.return_value.__aexit__ = AsyncMock(return_value=False)
            with patch("rsc.seasons.seasons.SeasonsApi", return_value=mock_api):
                result = await mixin.franchise_standings(mock_guild, season_id=1)

        assert result == [standing]

    async def test_raises_rsc_exception_on_api_error(self, mock_guild):
        mixin = _create_mixin(_api_conf={mock_guild.id: MagicMock()})

        with patch("rsc.seasons.seasons.ApiClient") as mock_client:
            mock_api = AsyncMock()
            mock_api.seasons_franchise_standings.side_effect = ApiException(status=404, reason="Not Found")
            mock_client.return_value.__aenter__ = AsyncMock(return_value=MagicMock())
            mock_client.return_value.__aexit__ = AsyncMock(return_value=False)
            with patch("rsc.seasons.seasons.SeasonsApi", return_value=mock_api):
                with pytest.raises(RscException):
                    await mixin.franchise_standings(mock_guild, season_id=999)


class TestSeasonActivityChecksApi:
    async def test_returns_results(self, mock_guild):
        check = MagicMock()
        resp = MagicMock()
        resp.results = [check]
        mixin = _create_mixin(_api_conf={mock_guild.id: MagicMock()})

        with patch("rsc.seasons.seasons.ApiClient") as mock_client:
            mock_api = AsyncMock()
            mock_api.seasons_activity_check_list.return_value = resp
            mock_client.return_value.__aenter__ = AsyncMock(return_value=MagicMock())
            mock_client.return_value.__aexit__ = AsyncMock(return_value=False)
            with patch("rsc.seasons.seasons.SeasonsApi", return_value=mock_api):
                result = await mixin.season_activity_checks(mock_guild, season_id=1)

        assert result == [check]

    async def test_passes_all_filters(self, mock_guild):
        resp = MagicMock()
        resp.results = []
        mixin = _create_mixin(_api_conf={mock_guild.id: MagicMock()})

        with patch("rsc.seasons.seasons.ApiClient") as mock_client:
            mock_api = AsyncMock()
            mock_api.seasons_activity_check_list.return_value = resp
            mock_client.return_value.__aenter__ = AsyncMock(return_value=MagicMock())
            mock_client.return_value.__aexit__ = AsyncMock(return_value=False)
            with patch("rsc.seasons.seasons.SeasonsApi", return_value=mock_api):
                await mixin.season_activity_checks(
                    mock_guild,
                    season_id=1,
                    season_number=25,
                    discord_id=123,
                    completed=True,
                    returning=True,
                    missing=False,
                    limit=10,
                    offset=5,
                )

        mock_api.seasons_activity_check_list.assert_awaited_once_with(
            season=1,
            season_number=25,
            discord_id=123,
            completed=True,
            returning_status=True,
            missing=False,
            limit=10,
            offset=5,
        )

    async def test_raises_rsc_exception_on_api_error(self, mock_guild):
        mixin = _create_mixin(_api_conf={mock_guild.id: MagicMock()})

        with patch("rsc.seasons.seasons.ApiClient") as mock_client:
            mock_api = AsyncMock()
            mock_api.seasons_activity_check_list.side_effect = ApiException(status=500, reason="Error")
            mock_client.return_value.__aenter__ = AsyncMock(return_value=MagicMock())
            mock_client.return_value.__aexit__ = AsyncMock(return_value=False)
            with patch("rsc.seasons.seasons.SeasonsApi", return_value=mock_api):
                with pytest.raises(RscException):
                    await mixin.season_activity_checks(mock_guild)
