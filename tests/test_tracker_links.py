import logging
import pytest

from rscapi.models.tracker_link import TrackerLink
from rscapi.models.player_season_stats_in_depth import PlayerSeasonStatsInDepth
from rscapi.models.league_player import LeaguePlayer
from rscapi.models.team_season_stats import TeamSeasonStats
from rscapi.models.team import Team

log = logging.getLevelName(__name__)

RSCID = "RSC002982"

@pytest.mark.asyncio
class TestTrackers:
    @pytest.mark.xfail
    async def test_trackers_links_links_stats(self, TrackerApi):
        r = await TrackerApi.tracker_links_links_stats(member=RSCID)
        assert r
        assert isinstance(r[0], TrackerLink)

    @pytest.mark.xfail
    async def test_trackers_links_list(self, TrackerApi):
        r = await TrackerApi.tracker_links_list(member="nickm")
        assert r
        assert isinstance(r[0], TrackerLink)

    @pytest.mark.xfail
    async def test_trackers_links_next(self, TrackerApi):
        r = await TrackerApi.tracker_links_next(member="nickm", limit=1)
        assert r
        assert isinstance(r[0], TrackerLink)

    @pytest.mark.xfail
    async def test_trackers_links_read(self, TrackerApi):
        r = await TrackerApi.tracker_links_read(1)
        assert isinstance(r, TrackerLink)


