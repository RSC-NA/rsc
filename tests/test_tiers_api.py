import sys
from pathlib import Path

import pytest

# Add the project root to the path so we can import the modules
project_root = Path(__file__).parent.parent
sys.path.insert(0, str(project_root))

from rsc.core import RSC
from rscapi import TiersApi

pytestmark = pytest.mark.integration


class TestTiersApiContract:
    """Verify all expected rscapi TiersApi methods exist without calling them."""

    EXPECTED_METHODS = [
        "tiers_list",
        "tiers_retrieve",
        "tiers_standings_list",
        "tiers_create",
        "tiers_destroy",
    ]

    @pytest.mark.parametrize("method_name", EXPECTED_METHODS)
    def test_method_exists(self, method_name: str):
        """Ensure TiersApi has the expected method."""
        assert hasattr(TiersApi, method_name), f"TiersApi missing expected method: {method_name}"
        assert callable(getattr(TiersApi, method_name)), f"TiersApi.{method_name} is not callable"


class TestTiersApiCalls:
    """Test RSC API calls for tier functions without exceptions."""

    @pytest.mark.asyncio
    async def test_tiers_api_call(self, rsc_bot: RSC, mock_guild):
        """Test that tiers() API call doesn't raise exceptions."""
        result = await rsc_bot.tiers(mock_guild)
        assert result is not None
        assert isinstance(result, list)

    @pytest.mark.asyncio
    async def test_tier_by_name_api_call(self, rsc_bot: RSC, mock_guild):
        """Test that tier_by_name() API call doesn't raise exceptions."""
        tiers = await rsc_bot.tiers(mock_guild)
        if not tiers:
            pytest.skip("No tiers found to test tier_by_name")

        tier = tiers[0]
        if not tier.name:
            pytest.skip("Tier has no name")

        await rsc_bot.tier_id_by_name(mock_guild, tier.name)

    @pytest.mark.asyncio
    async def test_tier_by_id_api_call(self, rsc_bot: RSC, mock_guild):
        """Test that tier_by_id() API call doesn't raise exceptions."""
        tiers = await rsc_bot.tiers(mock_guild)
        if not tiers:
            pytest.skip("No tiers found to test tier_by_id")

        tier = tiers[0]
        if not tier.id:
            pytest.skip("Tier has no ID")

        await rsc_bot.tier_by_id(mock_guild, tier.id)

    @pytest.mark.asyncio
    @pytest.mark.skip(reason="Creating tiers may have side effects; enable when safe to test.")
    async def test_create_tier_api_call(self, rsc_bot: RSC, mock_guild):
        """Test that create_tier() API call doesn't raise exceptions."""
        await rsc_bot.create_tier(mock_guild, "test_tier", "test_color")

    @pytest.mark.asyncio
    @pytest.mark.skip(reason="Deleting tiers may have side effects; enable when safe to test.")
    async def test_delete_tier_api_call(self, rsc_bot: RSC, mock_guild):
        """Test that delete_tier() API call doesn't raise exceptions."""
        await rsc_bot.delete_tier(mock_guild, "test_tier")


class TestTiersApiDataStructures:
    """Test that API responses have expected structure."""

    @pytest.mark.asyncio
    async def test_tier_structure(self, rsc_bot: RSC, mock_guild):
        """Test that tier objects have expected attributes."""
        tiers = await rsc_bot.tiers(mock_guild)
        if not tiers:
            pytest.skip("No tiers found to test structure")

        tier = tiers[0]
        assert hasattr(tier, "id"), "Tier should have 'id' attribute"
        assert hasattr(tier, "name"), "Tier should have 'name' attribute"
        assert hasattr(tier, "color"), "Tier should have 'color' attribute"


if __name__ == "__main__":
    pytest.main([__file__, "-v", "-s"])
