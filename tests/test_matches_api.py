import sys
from pathlib import Path

import pytest

# Add the project root to the path so we can import the modules
project_root = Path(__file__).parent.parent
sys.path.insert(0, str(project_root))

from rsc.core import RSC
from rsc.exceptions import RscException
from rscapi.models import MatchResults

from .utils import random_string


class TestMatchesApiCalls:
    """Test RSC API calls for match functions without exceptions."""

    @pytest.mark.asyncio
    async def test_matches_api_call(self, rsc_bot: RSC, mock_guild):
        """Test that matches() API call doesn't raise exceptions."""
        try:
            result = await rsc_bot.matches(mock_guild, limit=5)
            assert result is not None
            assert isinstance(result, list)
            print(f"✓ matches() returned {len(result)} match(es)")
            for m in result:
                home_team = m.home_team if m.home_team else "Unknown"
                away_team = m.away_team if m.away_team else "Unknown"
                print(f"  - ID: {m.id}, Home: {home_team}, Away: {away_team}")
        except RscException as e:
            pytest.fail(f"matches() raised RscException: {e}")
        except Exception as e:
            pytest.fail(f"matches() raised unexpected exception: {e}")

    @pytest.mark.asyncio
    async def test_matches_with_filters_api_call(self, rsc_bot: RSC, mock_guild):
        """Test that matches() API call with filters doesn't raise exceptions."""
        try:
            # Get current season for filtering
            season = await rsc_bot.current_season(mock_guild)
            if season and season.id:
                result = await rsc_bot.matches(mock_guild, season=season.id, limit=5)
                print(f"✓ matches(season={season.id}) returned {len(result)} match(es)")

            # Test filtering by team
            teams = await rsc_bot.teams(mock_guild)
            if teams and teams[0].name:
                result = await rsc_bot.matches(mock_guild, team_name=teams[0].name, limit=5)
                print(f"✓ matches(team_name='{teams[0].name}') returned {len(result)} match(es)")

        except RscException as e:
            pytest.fail(f"matches() with filters raised RscException: {e}")
        except Exception as e:
            pytest.fail(f"matches() with filters raised unexpected exception: {e}")

    @pytest.mark.asyncio
    async def test_match_by_id_api_call(self, rsc_bot: RSC, mock_guild):
        """Test that match_by_id() API call doesn't raise exceptions."""
        try:
            matches = await rsc_bot.matches(mock_guild, limit=1)
            if not matches:
                pytest.skip("No matches found to test match_by_id")

            match = matches[0]
            if not match.id:
                pytest.skip("Match has no ID")

            result = await rsc_bot.match_by_id(mock_guild, match.id)
            if result:
                print(f"✓ match_by_id() succeeded for match {match.id}")
                home_team = result.home_team.name if result.home_team else "Unknown"
                away_team = result.away_team.name if result.away_team else "Unknown"
                print(f"  - Home: {home_team}, Away: {away_team}")
            else:
                print(f"✓ match_by_id() returned None for match {match.id}")

        except RscException as e:
            pytest.fail(f"match_by_id() raised RscException: {e}")
        except Exception as e:
            pytest.fail(f"match_by_id() raised unexpected exception: {e}")

    @pytest.mark.asyncio
    async def test_upload_match_media_api_call(self, rsc_bot: RSC, mock_guild, mock_member):
        """Test that upload_match_media() API call doesn't raise exceptions."""
        try:
            matches = await rsc_bot.matches(mock_guild, limit=1)
            if not matches:
                pytest.skip("No matches found to test media upload")

            match = matches[0]
            if not match.id:
                pytest.skip("Match has no ID")

            # Test with fake ballchasing URL
            rand_str = random_string()
            bc_group = f"fake-{rand_str}"

            await rsc_bot.report_match(mock_guild, match.id, home_score=2, away_score=2, ballchasing_group=bc_group, executor=mock_member)
            print(f"✓ upload_match_media() succeeded for match {match.id}")

        except RscException as e:
            # Expected to fail with fake URL
            if e.status in [400, 404]:
                print(f"✓ upload_match_media() correctly handled invalid URL (status {e.status})")
            else:
                pytest.fail(f"upload_match_media() raised unexpected RscException: {e}")
        except Exception as e:
            pytest.fail(f"upload_match_media() raised unexpected exception: {e}")

    @pytest.mark.asyncio
    async def test_fetch_match_results_success(self, rsc_bot: RSC, mock_guild, mock_member):
        """Test that match_results() API call doesn't raise exceptions and returns expected data."""
        MATCH_ID = 31488  # Example match ID to test results fetching

        # Test valid match results fetching
        results: MatchResults = await rsc_bot.match_results(mock_guild, MATCH_ID)
        if not results:
            pytest.fail(f"No match results found for ID {MATCH_ID}")

        assert isinstance(results, MatchResults), f"Expected MatchResults type, got {type(results)}"
        assert isinstance(results.home_wins, int), "home_score should be an integer"
        assert isinstance(results.away_wins, int), "away_score should be an integer"
        assert isinstance(results.ballchasing_group, str) , "Ballchasing group should be a string"
        print(f"✓ match_results() succeeded for match ID {MATCH_ID}")


    @pytest.mark.asyncio
    async def test_fetch_match_results_not_found(self, rsc_bot: RSC, mock_guild):
        """Test that match_results() API call correctly handles 404 Not Found."""
        # Test NotFound 404 handling
        INVALID_MATCH_ID = 2  # Assuming this ID does not exist
        try:
            result = await rsc_bot.match_results(mock_guild, INVALID_MATCH_ID)
            pytest.fail(f"match_results() should have raised RscException for invalid ID {INVALID_MATCH_ID}")
        except RscException as e:
            print(f"Match results status code for invalid ID {INVALID_MATCH_ID}: {e.status} {e.reason}")
            if e.status == 404:
                print(f"✓ match_results() correctly raised 404 for invalid ID {INVALID_MATCH_ID}")
            else:
                pytest.fail(f"match_results() raised unexpected RscException status {e.status} for invalid ID {INVALID_MATCH_ID}")




class TestMatchesApiDataStructures:
    """Test that API responses have expected structure."""

    @pytest.mark.asyncio
    async def test_match_structure(self, rsc_bot: RSC, mock_guild):
        """Test that match objects have expected attributes."""
        try:
            matches = await rsc_bot.matches(mock_guild, limit=1)
            if not matches:
                pytest.skip("No matches found to test structure")

            match = matches[0]
            assert hasattr(match, "id"), "Match should have 'id' attribute"
            assert hasattr(match, "home_team"), "Match should have 'home_team' attribute"
            assert hasattr(match, "away_team"), "Match should have 'away_team' attribute"
            print(f"✓ Match structure valid - ID: {match.id}")
        except Exception as e:
            pytest.fail(f"Match structure test failed: {e}")


if __name__ == "__main__":
    pytest.main([__file__, "-v", "-s"])
