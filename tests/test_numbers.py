import logging
import pytest

from rscapi.models.player_mmr import PlayerMMR

log = logging.getLevelName(__name__)

RSC_ID = "RSC002892" # nickm

@pytest.mark.asyncio
class TestNumbers:
    async def test_numbers_list(self, NumberApi):
        r = await NumberApi.numbers_mmr_list(rscid=RSC_ID)
        assert r
        assert isinstance(r[0], PlayerMMR)

    @pytest.mark.xfail
    async def test_numbers_read(self, NumberApi):
        r = await NumberApi.numbers_mmr_read(1)
        print(r)
        assert isinstance(r, PlayerMMR)
