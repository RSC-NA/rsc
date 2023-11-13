import pytest
import logging

from rscapi.models.franchise_list import FranchiseList
from rscapi.models.franchise import Franchise
from rscapi.models.franchise_gm import FranchiseGM

log = logging.getLevelName(__name__)


@pytest.mark.asyncio
class TestFranchises:
    async def test_franchises_list(self, FranchiseApi):
        data = await FranchiseApi.franchises_list(league=1)
        assert len(data) > 0
        assert isinstance(data[0], FranchiseList)
        assert isinstance(data[0].gm, FranchiseGM)
        data = await FranchiseApi.franchises_list(
            league=1,
            prefix="test",
            gm_name="test",
            name="test",
            tier="1",
            tier_name="test",
        )
        assert not data

    async def test_franchises_read(self, FranchiseApi):
        data = await FranchiseApi.franchises_read(1)
        print(data)
        assert isinstance(data, FranchiseList)
        assert isinstance(data.gm, FranchiseGM)
