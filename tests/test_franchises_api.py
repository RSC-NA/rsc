import os
import sys
from pathlib import Path

import pytest

# Add the project root to the path so we can import the modules
project_root = Path(__file__).parent.parent
sys.path.insert(0, str(project_root))

from rsc.core import RSC
from rsc.exceptions import RscException


class TestFranchisesApiCalls:
    """Test RSC API calls for franchise functions without exceptions."""

    @pytest.mark.asyncio
    async def test_franchises_api_call(self, rsc_bot: RSC, mock_guild):
        """Test that franchises() API call doesn't raise exceptions."""
        try:
            result = await rsc_bot.franchises(mock_guild)
            assert result is not None
            assert isinstance(result, list)
            print(f"✓ franchises() returned {len(result)} franchise(s)")
            for f in result:
                gm_name = f.gm.rsc_name if f.gm else "None"
                print(f"  - ID: {f.id}, Name: {f.name}, GM: {gm_name}")
        except RscException as e:
            pytest.fail(f"franchises() raised RscException: {e}")
        except Exception as e:
            pytest.fail(f"franchises() raised unexpected exception: {e}")

    @pytest.mark.asyncio
    async def test_franchise_logo_api_call(self, rsc_bot: RSC, mock_guild):
        """Test that franchise_logo() API call doesn't raise exceptions."""
        try:
            # Get a franchise first
            franchises = await rsc_bot.franchises(mock_guild)
            if not franchises:
                pytest.skip("No franchises found to test logo")

            franchise = franchises[0]
            if not franchise.id:
                pytest.skip("Franchise has no ID")

            result = await rsc_bot.franchise_logo(mock_guild, franchise.id)
            if result:
                print(f"✓ franchise_logo() returned URL: {result}")
            else:
                print("✓ franchise_logo() returned None (no logo)")

        except RscException as e:
            pytest.fail(f"franchise_logo() raised RscException: {e}")
        except Exception as e:
            pytest.fail(f"franchise_logo() raised unexpected exception: {e}")


class TestFranchisesApiDataStructures:
    """Test that API responses have expected structure."""

    @pytest.mark.asyncio
    async def test_franchise_structure(self, rsc_bot: RSC, mock_guild):
        """Test that franchise objects have expected attributes."""
        try:
            franchises = await rsc_bot.franchises(mock_guild)
            if not franchises:
                pytest.skip("No franchises found to test logo")

            franchise = franchises[0]

            # Check for expected attributes
            assert hasattr(franchise, "id"), "Franchise should have 'id' attribute"
            assert hasattr(franchise, "name"), "Franchise should have 'name' attribute"
            assert hasattr(franchise, "prefix"), "Franchise should have 'prefix' attribute"
            assert hasattr(franchise, "gm"), "Franchise should have 'gm' attribute"
            print(f"✓ Franchise structure valid - ID: {franchise.id}, Name: {franchise.name}")
        except Exception as e:
            pytest.fail(f"Franchise structure test failed: {e}")


class TestFranchisesApiHelperFunctions:
    """Test helper functions that use the API."""

    @pytest.mark.asyncio
    async def test_franchise_gm_by_name(self, rsc_bot: RSC, mock_guild):
        """Test that franchise_gm_by_name() helper function works."""
        try:
            franchises = await rsc_bot.franchises(mock_guild)
            if not franchises:
                pytest.skip("No franchises found to test franchise_gm_by_name")

            franchise = franchises[0]
            if not franchise.name:
                pytest.skip("Franchise has no name")

            result = await rsc_bot.franchise_gm_by_name(mock_guild, franchise.name)
            if result:
                print(f"✓ franchise_gm_by_name() returned GM: {result.rsc_name}")
            else:
                print("✓ franchise_gm_by_name() returned None (no GM)")

        except ValueError as e:
            print(f"✓ franchise_gm_by_name() correctly handled multiple matches: {e}")
        except Exception as e:
            pytest.fail(f"franchise_gm_by_name() failed: {e}")

    @pytest.mark.asyncio
    async def test_fetch_franchise(self, rsc_bot: RSC, mock_guild):
        """Test that fetch_franchise() helper function works."""
        try:
            franchises = await rsc_bot.franchises(mock_guild)
            if not franchises:
                pytest.skip("No franchises found to test fetch_franchise")

            franchise = franchises[0]
            if not franchise.name:
                pytest.skip("Franchise has no name")

            result = await rsc_bot.fetch_franchise(mock_guild, franchise.name)
            if result:
                print(f"✓ fetch_franchise() returned franchise: {result.name}")
            else:
                print("✓ fetch_franchise() returned None")

        except ValueError as e:
            print(f"✓ fetch_franchise() correctly handled multiple matches: {e}")
        except Exception as e:
            pytest.fail(f"fetch_franchise() failed: {e}")

    @pytest.mark.asyncio
    async def test_franchise_name_to_id(self, rsc_bot: RSC, mock_guild):
        """Test that franchise_name_to_id() helper function works."""
        try:
            franchises = await rsc_bot.franchises(mock_guild)
            if not franchises:
                pytest.skip("No franchises found to test franchise_name_to_id")

            franchise = franchises[0]
            if not franchise.name:
                pytest.skip("Franchise has no name")

            result = await rsc_bot.franchise_name_to_id(mock_guild, franchise.name)
            assert isinstance(result, int)
            assert result == franchise.id
            print(f"✓ franchise_name_to_id() returned ID: {result}")

        except AttributeError as e:
            pytest.fail(f"franchise_name_to_id() raised AttributeError: {e}")
        except Exception as e:
            pytest.fail(f"franchise_name_to_id() failed: {e}")

    @pytest.mark.asyncio
    async def test_full_logo_url(self, rsc_bot: RSC, mock_guild):
        """Test that full_logo_url() helper function works."""
        try:
            test_path = "/media/logos/test.png"
            result = await rsc_bot.full_logo_url(mock_guild, test_path)
            assert isinstance(result, str)
            assert result.endswith(test_path)
            print(f"✓ full_logo_url() returned: {result}")

        except RuntimeError as e:
            # Expected if API host not configured
            print(f"✓ full_logo_url() correctly handled missing host: {e}")
        except Exception as e:
            pytest.fail(f"full_logo_url() failed: {e}")


if __name__ == "__main__":
    """Run tests directly if script is executed."""
    print("Running RSC Franchises API tests...")

    # Check for API key
    if not os.getenv("RSC_API_KEY"):
        print("ERROR: RSC_API_KEY environment variable not set")
        sys.exit(1)

    # Run pytest
    pytest.main([__file__, "-v", "-s"])
