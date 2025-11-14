import sys
from pathlib import Path

import pytest

# Add the project root to the path so we can import the modules
project_root = Path(__file__).parent.parent
sys.path.insert(0, str(project_root))

from rsc.core import RSC
from rsc.exceptions import RscException


class TestSeasonsApiCalls:
    """Test RSC API calls for season functions without exceptions."""

    @pytest.mark.asyncio
    async def test_seasons_api_call(self, rsc_bot: RSC, mock_guild):
        """Test that seasons() API call doesn't raise exceptions."""
        try:
            result = await rsc_bot.seasons(mock_guild)
            assert result is not None
            assert isinstance(result, list)
            print(f"✓ seasons() returned {len(result)} season(s)")
            for s in result:
                print(f"  - ID: {s.id}, Number: {s.number}")
        except RscException as e:
            pytest.fail(f"seasons() raised RscException: {e}")
        except Exception as e:
            pytest.fail(f"seasons() raised unexpected exception: {e}")

    @pytest.mark.asyncio
    async def test_current_season_api_call(self, rsc_bot: RSC, mock_guild):
        """Test that current_season() API call doesn't raise exceptions."""
        try:
            result = await rsc_bot.current_season(mock_guild)
            if result:
                print(f"✓ current_season() returned season: {result.number}")
                print(f"  - ID: {result.id} Number: {result.number}")
            else:
                print("✓ current_season() returned None (no current season)")
        except RscException as e:
            pytest.fail(f"current_season() raised RscException: {e}")
        except Exception as e:
            pytest.fail(f"current_season() raised unexpected exception: {e}")

    @pytest.mark.asyncio
    async def test_next_season_api_call(self, rsc_bot: RSC, mock_guild):
        """Test that next_season() API call doesn't raise exceptions."""
        try:
            result = await rsc_bot.next_season(mock_guild)
            if result:
                print(f"✓ next_season() returned season: {result.number}")
                print(f"  - ID: {result.id}, Number: {result.number}")
            else:
                print("✓ next_season() returned None (no next season)")
        except RscException as e:
            if e.status == 404:
                print("✓ next_season() correctly handled no next season (404)")
            else:
                pytest.fail(f"next_season() raised unexpected RscException: {e}")
        except Exception as e:
            pytest.fail(f"next_season() raised unexpected exception: {e}")

    @pytest.mark.asyncio
    async def test_season_by_number_api_call(self, rsc_bot: RSC, mock_guild):
        """Test that season_by_number() API call doesn't raise exceptions."""
        try:
            seasons = await rsc_bot.seasons(mock_guild)
            if not seasons:
                pytest.skip("No seasons found to test season_by_number")

            season = seasons[0]
            if season.number is None:
                pytest.skip("Season has no number")

            result = await rsc_bot.season_by_id(mock_guild, season.id)
            if result:
                print(f"✓ season_by_id() succeeded for season {season.id}")
                print(f"  - ID: {result.id}, Nuymber: {result.number}")
            else:
                print(f"✓ season_by_number() returned None for season {season.number}")

        except RscException as e:
            pytest.fail(f"season_by_number() raised RscException: {e}")
        except Exception as e:
            pytest.fail(f"season_by_number() raised unexpected exception: {e}")


class TestSeasonsApiDataStructures:
    """Test that API responses have expected structure."""

    @pytest.mark.asyncio
    async def test_season_structure(self, rsc_bot: RSC, mock_guild):
        """Test that season objects have expected attributes."""
        try:
            seasons = await rsc_bot.seasons(mock_guild)
            if not seasons:
                pytest.skip("No seasons found to test structure")

            season = seasons[0]
            assert hasattr(season, "id"), "Season should have 'id' attribute"
            assert hasattr(season, "number"), "Season should have 'number' attribute"
            print(f"✓ Season structure valid - ID: {season.id}, Number: {season.number}")
        except Exception as e:
            pytest.fail(f"Season structure test failed: {e}")


if __name__ == "__main__":
    pytest.main([__file__, "-v", "-s"])
