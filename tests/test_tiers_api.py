import sys
from pathlib import Path

import pytest

# Add the project root to the path so we can import the modules
project_root = Path(__file__).parent.parent
sys.path.insert(0, str(project_root))

from rsc.core import RSC
from rsc.exceptions import RscException


class TestTiersApiCalls:
    """Test RSC API calls for tier functions without exceptions."""

    @pytest.mark.asyncio
    async def test_tiers_api_call(self, rsc_bot: RSC, mock_guild):
        """Test that tiers() API call doesn't raise exceptions."""
        try:
            result = await rsc_bot.tiers(mock_guild)
            assert result is not None
            assert isinstance(result, list)
            print(f"✓ tiers() returned {len(result)} tier(s)")
            for t in result:
                print(f"  - ID: {t.id}, Name: {t.name}, Color: {t.color}")
        except RscException as e:
            pytest.fail(f"tiers() raised RscException: {e}")
        except Exception as e:
            pytest.fail(f"tiers() raised unexpected exception: {e}")

    @pytest.mark.asyncio
    async def test_tier_by_name_api_call(self, rsc_bot: RSC, mock_guild):
        """Test that tier_by_name() API call doesn't raise exceptions."""
        try:
            tiers = await rsc_bot.tiers(mock_guild)
            if not tiers:
                pytest.skip("No tiers found to test tier_by_name")

            tier = tiers[0]
            if not tier.name:
                pytest.skip("Tier has no name")

            result = await rsc_bot.tier_id_by_name(mock_guild, tier.name)
            if result:
                print(f"✓ tier_by_name() succeeded for tier {tier.name}")
                print(f"  - ID: {result}")
            else:
                print(f"✓ tier_by_name() returned None for tier {tier.name}")

        except RscException as e:
            pytest.fail(f"tier_by_name() raised RscException: {e}")
        except Exception as e:
            pytest.fail(f"tier_by_name() raised unexpected exception: {e}")

    @pytest.mark.asyncio
    async def test_tier_by_id_api_call(self, rsc_bot: RSC, mock_guild):
        """Test that tier_by_id() API call doesn't raise exceptions."""
        try:
            tiers = await rsc_bot.tiers(mock_guild)
            if not tiers:
                pytest.skip("No tiers found to test tier_by_id")

            tier = tiers[0]
            if not tier.id:
                pytest.skip("Tier has no ID")

            result = await rsc_bot.tier_by_id(mock_guild, tier.id)
            if result:
                print(f"✓ tier_by_id() succeeded for tier {tier.id}")
                print(f"  - ID: {result.id}, Name: {result.name}")
            else:
                print(f"✓ tier_by_id() returned None for tier {tier.id}")

        except RscException as e:
            pytest.fail(f"tier_by_id() raised RscException: {e}")
        except Exception as e:
            pytest.fail(f"tier_by_id() raised unexpected exception: {e}")

    @pytest.mark.asyncio
    @pytest.mark.skip(reason="Creating tiers may have side effects; enable when safe to test.")
    async def test_create_tier_api_call(self, rsc_bot: RSC, mock_guild):
        """Test that create_tier() API call doesn't raise exceptions."""
        try:
            result = await rsc_bot.create_tier(mock_guild, "test_tier", "test_color")
            print(f"✓ create_tier() succeeded for tier test_tier")
            print(f"  - ID: {result.id}, Name: {result.name}")
        except RscException as e:
            pytest.fail(f"create_tier() raised RscException: {e}")
        except Exception as e:
            pytest.fail(f"create_tier() raised unexpected exception: {e}")

    @pytest.mark.asyncio
    @pytest.mark.skip(reason="Deleting tiers may have side effects; enable when safe to test.")
    async def test_delete_tier_api_call(self, rsc_bot: RSC, mock_guild):
        """Test that delete_tier() API call doesn't raise exceptions."""
        try:
            result = await rsc_bot.delete_tier(mock_guild, "test_tier")
            print(f"✓ delete_tier() succeeded for tier test_tier")
        except RscException as e:
            pytest.fail(f"delete_tier() raised RscException: {e}")
        except Exception as e:
            pytest.fail(f"delete_tier() raised unexpected exception: {e}")


class TestTiersApiDataStructures:
    """Test that API responses have expected structure."""

    @pytest.mark.asyncio
    async def test_tier_structure(self, rsc_bot: RSC, mock_guild):
        """Test that tier objects have expected attributes."""
        try:
            tiers = await rsc_bot.tiers(mock_guild)
            if not tiers:
                pytest.skip("No tiers found to test structure")

            tier = tiers[0]
            assert hasattr(tier, "id"), "Tier should have 'id' attribute"
            assert hasattr(tier, "name"), "Tier should have 'name' attribute"
            assert hasattr(tier, "color"), "Tier should have 'color' attribute"
            print(f"✓ Tier structure valid - ID: {tier.id}, Name: {tier.name}")
        except Exception as e:
            pytest.fail(f"Tier structure test failed: {e}")


if __name__ == "__main__":
    pytest.main([__file__, "-v", "-s"])
