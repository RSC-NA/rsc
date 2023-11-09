import logging
import pytest

from rscapi.models.franchise_standings import FranchiseStandings
from rscapi.models.season import Season

log = logging.getLevelName(__name__)

RSC_ID = "RSC002892"

@pytest.mark.asyncio
class TestSeasons:
    async def test_seasons_franchise_standings(self, SeasonApi):
        r = await SeasonApi.seasons_franchise_standings(1)
        assert r
        assert isinstance(r[0], FranchiseStandings)

    @pytest.mark.xfail
    async def test_seasons_league_season(self, SeasonApi):
        r = await SeasonApi.seasons_league_season(1)
        assert r
        assert isinstance(r[0], Season)

    @pytest.mark.xfail
    async def test_seasons_list(self, SeasonApi):
        r = await SeasonApi.seasons_list()
        assert r
        assert isinstance(r[0], Season)

    @pytest.mark.xfail
    async def test_seasons_read(self, SeasonApi):
        r = await SeasonApi.seasons_read(1)
        assert isinstance(r, Season)