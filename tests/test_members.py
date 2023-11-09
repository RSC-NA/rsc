import pytest
import logging
from datetime import datetime

from rscapi.exceptions import ApiException
from rscapi.models.member import Member
from rscapi.models.league_player import LeaguePlayer
from rscapi.models.members_list200_response import MembersList200Response
from rscapi.models.player_season_stats import PlayerSeasonStats

log = logging.getLevelName(__name__)

NOW = datetime.now().strftime("%Y-%m-%d")

DISCORD_ID = 138778232802508801 # nickm

@pytest.mark.asyncio
class TestMembers:
    @pytest.mark.xfail
    async def test_members_accounts(self, MemberApi):
        r = await MemberApi.members_accounts(1)
        assert r.isinstance(r, Member)

    @pytest.mark.xfail
    async def test_members_contract_status(self, MemberApi):
        r = await MemberApi.members_contract_status(DISCORD_ID, 1)
        assert isinstance(r, LeaguePlayer)

    @pytest.mark.xfail
    async def test_members_list(self, MemberApi):
        r = await MemberApi.members_list(rsc_name="nickm", discord_username="nickm", limit=1, offset=0)
        assert isinstance(r, MembersList200Response)
        assert r.count == 1
        assert isinstance(r.results[0], Member)

    async def test_members_postseason_stats(self, MemberApi):
        with pytest.raises(ApiException):
            await MemberApi.members_postseason_stats(1, 1)
        # assert isinstance(r,PlayerSeasonStats)

    @pytest.mark.xfail
    async def test_members_read(self, MemberApi):
        r = await MemberApi.members_read(DISCORD_ID)
        assert isinstance(r, Member)

    async def test_members_stats(self, MemberApi):
        r = await MemberApi.members_stats(DISCORD_ID, 1)
        assert isinstance(r, PlayerSeasonStats)