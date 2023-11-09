import logging
import pytest

from rscapi.models.tier import Tier
from rscapi.models.player_season_stats_in_depth import PlayerSeasonStatsInDepth
from rscapi.models.league_player import LeaguePlayer
from rscapi.models.team_season_stats import TeamSeasonStats
from rscapi.models.team import Team

log = logging.getLevelName(__name__)

@pytest.mark.asyncio
class TestTiers:
    async def test_tiers_(self, TierApi):
        r = await TierApi.tiers_list(name="Premier", league="1")
        assert r
        assert isinstance(r[0], Tier)

    async def test_tiers_player_stats(self, TierApi):
        r = await TierApi.tiers_player_stats(1, 1, season=18)
        assert r
        assert isinstance(r[0], PlayerSeasonStatsInDepth)

    @pytest.mark.xfail
    async def test_tiers_players(self, TierApi):
        r = await TierApi.tiers_players(1, 1, season=18)
        assert r
        assert isinstance(r[0], LeaguePlayer)

    @pytest.mark.skip
    async def test_tiers_postseason_player_stats(self, TierApi):
        r = await TierApi.tiers_postseason_player_stats(1, 1, season=18)
        assert r
        assert isinstance(r[0], PlayerSeasonStatsInDepth)

    @pytest.mark.skip
    async def test_tiers_postseason_team_stats(self, TierApi):
        r = await TierApi.tiers_postseason_team_stats(1, 1, season=18)
        assert r
        assert isinstance(r[0], PlayerSeasonStatsInDepth)

    async def test_tiers_read(self, TierApi):
        r = await TierApi.tiers_read(1)

    async def test_tiers_team_stats(self, TierApi):
        r = await TierApi.tiers_team_stats(1, 1, season=18)
        assert r
        assert isinstance(r[0], TeamSeasonStats)

    async def test_tiers_teams(self, TierApi):
        r = await TierApi.tiers_teams(1, 1, season=18)
        assert r
        assert isinstance(r[0], Team)

