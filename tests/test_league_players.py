import pytest
import logging

from rscapi.models.league_player import LeaguePlayer
from rscapi.models.league_players_list200_response import LeaguePlayersList200Response
from rscapi.models.player_season_stats import PlayerSeasonStats
from rscapi.models.league import League
from rscapi.models.player_team import PlayerTeam
from rscapi.models.league_player_member import LeaguePlayerMember

log = logging.getLevelName(__name__)


@pytest.mark.asyncio
class TestLeaguePlayers:
    async def test_league_players_list(self, LeaguePlayerApi):
        r = await LeaguePlayerApi.league_players_list(league="1", limit=1)
        assert isinstance(r, LeaguePlayersList200Response)
        assert r.count
        assert isinstance(r.results[0], LeaguePlayer)
        r = await LeaguePlayerApi.league_players_list(
            status="FA",
            name="test",
            tier="1",
            tier_name="test",
            season="18",
            season_number="18",
            league="1",
            team_name="test",
            limit=1,
            offset=0,
        )
        assert isinstance(r, LeaguePlayersList200Response)
        assert r.count == 0 

    @pytest.mark.xfail
    async def test_league_players_postseason_stats(self, LeaguePlayerApi):
        r = await LeaguePlayerApi.league_players_postseason_stats(1)
        assert isinstance(r, PlayerSeasonStats)

    async def test_league_players_read(self, LeaguePlayerApi):
        r = await LeaguePlayerApi.league_players_read(1)
        assert isinstance(r, LeaguePlayer)
        assert isinstance(r.league, League)
        assert isinstance(r.team, PlayerTeam)
        assert isinstance(r.player, LeaguePlayerMember)

    async def test_league_players_stats(self, LeaguePlayerApi):
        r = await LeaguePlayerApi.league_players_stats(1)
        assert isinstance(r, PlayerSeasonStats)