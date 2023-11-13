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

@pytest.mark.asyncio
class TestMembers:
    async def test_members_accounts(self, MemberApi):
        r = await MemberApi.members_accounts(1)
        assert r.isinstance(r, Member)

    async def test_members_contract_status(self, MemberApi, discord_id):
        r = await MemberApi.members_contract_status(discord_id, 1)
        assert isinstance(r, LeaguePlayer)

    async def test_members_list(self, MemberApi):
        r = await MemberApi.members_list(discord_username="nickm", limit=1, offset=0)
        assert isinstance(r, MembersList200Response)
        assert r.count == 1
        assert isinstance(r.results[0], Member)
        # r = await MemberApi.members_list(rsc_name="nickm", discord_username="nickm", limit=1, offset=0)
        # assert isinstance(r, MembersList200Response)
        # assert r.count == 1
        # assert isinstance(r.results[0], Member)

    async def test_members_postseason_stats(self, MemberApi):
        with pytest.raises(ApiException):
            await MemberApi.members_postseason_stats(1, 1)
        # assert isinstance(r,PlayerSeasonStats)

    async def test_members_read(self, MemberApi, discord_id):
        r = await MemberApi.members_read(discord_id)
        assert isinstance(r, Member)

    async def test_members_stats(self, MemberApi, discord_id):
        r = await MemberApi.members_stats(discord_id, 1)
        assert isinstance(r, PlayerSeasonStats)