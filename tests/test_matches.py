import pytest
import logging
from datetime import datetime

from rscapi.models.match import Match
from rscapi.models.team import Team
from rscapi.models.match_results import MatchResults
from rscapi.models.matches_list200_response import MatchesList200Response
from rscapi.models.match_list import MatchList

log = logging.getLevelName(__name__)

NOW = datetime.now().strftime("%Y-%m-%d")

@pytest.mark.asyncio
class TestMatches:
    async def test_matches_find_match(self, MatchApi):
        r = await MatchApi.matches_find_match(league=1, limit=1)
        assert r
        assert isinstance(r[0], Match)
        assert isinstance(r[0].home_team, Team)
        assert isinstance(r[0].away_team, Team)
        assert isinstance(r[0].results, MatchResults)
        r = await MatchApi.matches_find_match(
            league=1,
            date__lt=NOW,
            date__gt=NOW,
            season=18,
            season_number=18,
            home_team="test",
            away_team="test",
            day=1,
            match_type="REG",
            match_format="BO3",
            limit=1,
            offset=0,
            teams="test",
            preseason=0,
        )
        assert not r

    async def test_matches_list(self, MatchApi):
        r = await MatchApi.matches_list(league="1", limit=1)
        assert isinstance(r, MatchesList200Response)
        assert r.count > 1
        assert isinstance(r.results[0], MatchList)
        r = await MatchApi.matches_list(
            league="1",
            date__lt=NOW,
            date__gt=NOW,
            season="18",
            season_number="18",
            home_team="test",
            away_team="test",
            day="1",
            match_type="REG",
            match_format="BO3",
            limit=1,
            offset=0,
        )
        assert isinstance(r, MatchesList200Response)
        assert r.count == 0

    async def test_matches_read(self, MatchApi):
        r = await MatchApi.matches_read(1)
        assert isinstance(r, Match)
        assert isinstance(r.home_team, Team)
        assert isinstance(r.away_team, Team)
        assert isinstance(r.results, MatchResults)

    async def test_matches_results(self, MatchApi):
        r = await MatchApi.matches_results(1)
        assert isinstance(r, MatchResults)