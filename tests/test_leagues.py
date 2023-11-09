import pytest
import logging

from rscapi.models.season import Season
from rscapi.models.season_league import SeasonLeague
from rscapi.models.league import League
from rscapi.models.league_data import LeagueData
from rscapi.models.league_player_member import LeaguePlayerMember

log = logging.getLevelName(__name__)


@pytest.mark.asyncio
class TestLeague:
    @pytest.mark.xfail
    async def test_leagues_current_season(self, LeagueApi):
        r = await LeagueApi.leagues_current_season("1")
        assert isinstance(r, Season)
        assert isinstance(r.league, SeasonLeague)

    async def test_leagues_list(self, LeagueApi):
        r = await LeagueApi.leagues_list()
        assert r
        assert isinstance(r[0], League)

    async def test_leagues_read(self, LeagueApi):
        r = await LeagueApi.leagues_read(1)
        assert isinstance(r, League)
        assert isinstance(r.league_data, LeagueData)

    @pytest.mark.xfail
    async def test_leagues_seasons(self, LeagueApi):
        r = await LeagueApi.leagues_seasons("1")
        assert r
        assert isinstance(r[0], Season)
        assert isinstance(r[0].league, SeasonLeague)