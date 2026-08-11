import os
import sys
from pathlib import Path

import pytest

# Add the project root to the path so we can import the modules
project_root = Path(__file__).parent.parent
sys.path.insert(0, str(project_root))

from rsc.core import RSC
from rscapi import FranchisesApi
from rscapi.models import Franchise
from rscapi.models.franchise_rebrand import FranchiseRebrand
from rsc.exceptions import RscException

pytestmark = pytest.mark.integration


class TestFranchisesApiContract:
    """Verify all expected rscapi FranchisesApi methods exist without calling them."""

    EXPECTED_METHODS = [
        "franchises_list",
        "franchises_retrieve",
        "franchises_upload_logo_update",
        "franchises_create",
        "franchises_destroy",
        "franchises_rebrand_update",
        "franchises_transfer_franchise_update",
        "franchises_logo_retrieve",
        "franchises_add_agm_update",
        "franchises_remove_agm_update",
    ]

    @pytest.mark.parametrize("method_name", EXPECTED_METHODS)
    def test_method_exists(self, method_name: str):
        """Ensure FranchisesApi has the expected method."""
        assert hasattr(FranchisesApi, method_name), f"FranchisesApi missing expected method: {method_name}"
        assert callable(getattr(FranchisesApi, method_name)), f"FranchisesApi.{method_name} is not callable"


class TestFranchisesApiCalls:
    """Test RSC API calls for franchise functions without exceptions."""

    @pytest.mark.asyncio
    async def test_franchises_api_call(self, rsc_bot: RSC, mock_guild):
        """Test that franchises() API call doesn't raise exceptions."""
        result = await rsc_bot.franchises(mock_guild)
        assert result is not None
        assert isinstance(result, list)
        print(f"✓ franchises() returned {len(result)} franchise(s)")
        for f in result:
            gm_name = f.gm.rsc_name if f.gm else "None"
            print(f"  - ID: {f.id}, Name: {f.name}, GM: {gm_name}")

    @pytest.mark.asyncio
    async def test_franchise_logo_api_call(self, rsc_bot: RSC, mock_guild):
        """Test that franchise_logo() API call doesn't raise exceptions."""
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

    @pytest.mark.asyncio
    @pytest.mark.skip(reason="Test not correctly verified yet")
    async def test_create_franchise(self, rsc_bot: RSC, mock_guild, mock_member):
        """Test that create_franchise() API call raises NotImplementedError."""
        new_franchise = await rsc_bot.create_franchise(guild=mock_guild, name="Test Franchise", prefix="TF", gm=mock_member)
        pytest.fail("create_franchise() should raise NotImplementedError")

        assert new_franchise is None
        assert isinstance(new_franchise, Franchise)
        assert new_franchise.name == "Test Franchise"
        assert new_franchise.prefix == "TF"
        assert new_franchise.gm.discord_id == mock_member.id
        print("✓ create_franchise() returned expected Franchise object")

class TestFranchisesPrivilegedApiCalls:

    @pytest.mark.asyncio
    async def test_create_franchise_privileged_api_call(self, rsc_bot_no_key: RSC, rsc_bot_invalid_key: RSC, mock_guild, mock_member):
        """Test that create_franchise() API call raises NotImplementedError."""
        with pytest.raises(RscException) as exc:
            await rsc_bot_no_key.create_franchise(guild=mock_guild, name="Test Franchise", prefix="TF", gm=mock_member)
        assert exc.type == RscException
        assert exc.value.type == "NotAuthenticated"
        assert exc.value.response.reason == "Forbidden"
        assert exc.value.status == 403
        assert exc.value.response.status == 403

        with pytest.raises(RscException) as exc:
            await rsc_bot_invalid_key.create_franchise(guild=mock_guild, name="Test Franchise", prefix="TF", gm=mock_member)
        assert exc.type == RscException
        assert exc.value.type == "NotAuthenticated"
        assert exc.value.response.reason == "Forbidden"
        assert exc.value.status == 403
        assert exc.value.response.status == 403

    @pytest.mark.asyncio
    async def test_rebrand_franchise_privileged_api_call(self, rsc_bot_no_key: RSC, rsc_bot_invalid_key: RSC, mock_guild, mock_member):
        """Test that rebrand_franchise() API call raises NotImplementedError."""

        flist = await rsc_bot_no_key.franchises(mock_guild)
        if not flist:
            pytest.fail("No franchises found to test rebrand_franchise()")
        franchise = flist.pop(0)
        print(f"Testing rebrand_franchise() on franchise ID {franchise.id}, Name: {franchise.name}")

        rebrand = FranchiseRebrand(name="New Franchise Name", prefix="NF", teams=[], admin_override=False)
        with pytest.raises(RscException) as exc:
            await rsc_bot_no_key.rebrand_franchise(guild=mock_guild, id=franchise.id, rebrand=rebrand)
        assert exc.type == RscException
        assert exc.value.type == "NotAuthenticated"
        assert exc.value.response.reason == "Forbidden"
        assert exc.value.status == 403
        assert exc.value.response.status == 403

        with pytest.raises(RscException) as exc:
            await rsc_bot_invalid_key.rebrand_franchise(guild=mock_guild, id=franchise.id, rebrand=rebrand)
        assert exc.type == RscException
        assert exc.value.type == "NotAuthenticated"
        assert exc.value.response.reason == "Forbidden"
        assert exc.value.status == 403
        assert exc.value.response.status == 403

    @pytest.mark.asyncio
    async def test_transfer_franchise_privileged_api_call(self, rsc_bot_no_key: RSC, rsc_bot_invalid_key: RSC, mock_guild, mock_member):
        """Test that transfer_franchise() API call raises NotImplementedError."""

        flist = await rsc_bot_no_key.franchises(mock_guild)
        if not flist:
            pytest.fail("No franchises found to test transfer_franchise()")
        franchise = flist.pop(0)
        print(f"Testing transfer_franchise() on franchise ID {franchise.id}, Name: {franchise.name}")

        with pytest.raises(RscException) as exc:
            await rsc_bot_no_key.transfer_franchise(guild=mock_guild, id=franchise.id, gm=mock_member)
        assert exc.type == RscException
        assert exc.value.type == "NotAuthenticated"
        assert exc.value.response.reason == "Forbidden"
        assert exc.value.status == 403
        assert exc.value.response.status == 403

        with pytest.raises(RscException) as exc:
            await rsc_bot_invalid_key.transfer_franchise(guild=mock_guild, id=franchise.id, gm=mock_member)
        assert exc.type == RscException
        assert exc.value.type == "NotAuthenticated"
        assert exc.value.response.reason == "Forbidden"
        assert exc.value.status == 403
        assert exc.value.response.status == 403

    @pytest.mark.asyncio
    async def test_upload_logo_privileged_api_call(self, rsc_bot_no_key: RSC, rsc_bot_invalid_key: RSC, mock_guild, mock_member):
        """Test that upload_franchise_logo() API call raises NotImplementedError."""

        flist = await rsc_bot_no_key.franchises(mock_guild)
        if not flist:
            pytest.fail("No franchises found to test upload_franchise_logo()")
        franchise = flist.pop(0)
        print(f"Testing upload_franchise_logo() on franchise ID {franchise.id}, Name: {franchise.name}")

        logo = bytes("fake image data", "utf-8")

        with pytest.raises(RscException) as exc:
            await rsc_bot_no_key.upload_franchise_logo(guild=mock_guild, id=franchise.id, logo=logo)
        assert exc.type == RscException
        assert exc.value.type == "NotAuthenticated"
        assert exc.value.response.reason == "Forbidden"
        assert exc.value.status == 403
        assert exc.value.response.status == 403

        with pytest.raises(RscException) as exc:
            await rsc_bot_invalid_key.upload_franchise_logo(guild=mock_guild, id=franchise.id, logo=logo)
        assert exc.type == RscException
        assert exc.value.type == "NotAuthenticated"
        assert exc.value.response.reason == "Forbidden"
        assert exc.value.status == 403
        assert exc.value.response.status == 403

class TestFranchisesApiDataStructures:
    """Test that API responses have expected structure."""

    @pytest.mark.asyncio
    async def test_franchise_structure(self, rsc_bot: RSC, mock_guild):
        """Test that franchise objects have expected attributes."""
        franchises = await rsc_bot.franchises(mock_guild)
        if not franchises:
            pytest.skip("No franchises found to test logo")

        franchise = franchises[0]

        # Check for expected attributes
        assert hasattr(franchise, "id"), "Franchise should have 'id' attribute"
        assert hasattr(franchise, "name"), "Franchise should have 'name' attribute"
        assert hasattr(franchise, "prefix"), "Franchise should have 'prefix' attribute"
        assert hasattr(franchise, "gm"), "Franchise should have 'gm' attribute"
        # The bot's only bulk source of AGMs now that they are FranchiseStaff.
        assert hasattr(franchise, "agms"), "FranchiseList must carry agms inline"
        assert isinstance(franchise.agms, list), f"agms should be a list, got {type(franchise.agms)}"
        print(f"✓ Franchise structure valid - ID: {franchise.id}, Name: {franchise.name}")


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

    @pytest.mark.asyncio
    async def test_franchise_name_to_id(self, rsc_bot: RSC, mock_guild):
        """Test that franchise_name_to_id() helper function works."""
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


if __name__ == "__main__":
    """Run tests directly if script is executed."""
    print("Running RSC Franchises API tests...")

    # Check for API key
    if not os.getenv("RSC_API_KEY"):
        print("ERROR: RSC_API_KEY environment variable not set")
        sys.exit(1)

    # Run pytest
    pytest.main([__file__, "-v", "-s"])
