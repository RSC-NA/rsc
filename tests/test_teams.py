import logging
import pytest

from rscapi.exceptions import ApiException
from rscapi.models.team_list import TeamList
from rscapi.models.match import Match
from rscapi.models.player import Player
from rscapi.models.team_season_stats import TeamSeasonStats
from rscapi.models.team import Team

log = logging.getLevelName(__name__)

RSC_ID = "RSC002892"

@pytest.mark.asyncio
class TestTeams:
    async def test_teams(self, TeamApi):
        r = await TeamApi.teams_list(tier="Premier", league="1")
        assert r
        assert isinstance(r[0], TeamList)
        r = await TeamApi.teams_list(seasons="18", franchise="test", name="test", tier="Premier", league="1")
        assert not r

    async def test_teams_match(self, TeamApi):
        r = await TeamApi.teams_match("1", 1, preseason=0)
        assert isinstance(r, Match)

    async def test_teams_next_match(self, TeamApi):
        with pytest.raises(ApiException):
            await TeamApi.teams_next_match("1337") 

    async def test_teams_players(self, TeamApi):
        r = await TeamApi.teams_players("1")
        assert r
        assert isinstance(r[0], Player)

    async def test_teams_postseason_stats(self, TeamApi):
        r = await TeamApi.teams_postseason_stats("1", season=18)
        assert isinstance(r, TeamSeasonStats)

    async def test_teams_read(self, TeamApi):
        r = await TeamApi.teams_read("1")
        assert isinstance(r, Team)

    async def test_teams_season_matches(self, TeamApi):
        r = await TeamApi.teams_season_matches("1", preseason=False, season=18)
        assert r
        assert isinstance(r[0], Match)

    async def test_teams_stats(self, TeamApi):
        r = await TeamApi.teams_stats("1", season=18)
        assert isinstance(r, TeamSeasonStats)
