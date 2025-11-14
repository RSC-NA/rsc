import sys
from pathlib import Path

import pytest

# Add the project root to the path so we can import the modules
project_root = Path(__file__).parent.parent
sys.path.insert(0, str(project_root))

from rsc.core import RSC
from rsc.exceptions import RscException


class TestTeamsApiCalls:
    """Test RSC API calls for team functions without exceptions."""

    @pytest.mark.asyncio
    async def test_teams_api_call(self, rsc_bot: RSC, mock_guild):
        """Test that teams() API call doesn't raise exceptions."""
        try:
            result = await rsc_bot.teams(mock_guild)
            assert result is not None
            assert isinstance(result, list)
            print(f"✓ teams() returned {len(result)} team(s)")
            for t in result:
                print(f"  - ID: {t.id}, Name: {t.name}, Franchise: {t.franchise.name if t.franchise else 'None'}")
        except RscException as e:
            pytest.fail(f"teams() raised RscException: {e}")
        except Exception as e:
            pytest.fail(f"teams() raised unexpected exception: {e}")

    @pytest.mark.asyncio
    async def test_teams_with_filters_api_call(self, rsc_bot: RSC, mock_guild):
        """Test that teams() API call with filters doesn't raise exceptions."""
        try:
            # Get first team to test filters
            all_teams = await rsc_bot.teams(mock_guild)
            if not all_teams:
                pytest.skip("No teams found to test filters")

            team = all_teams[0]

            # Test filtering by name
            if team.name:
                result = await rsc_bot.teams(mock_guild, name=team.name)
                print(f"✓ teams(name='{team.name}') returned {len(result)} team(s)")

            # Test filtering by franchise
            if team.franchise and team.franchise.name:
                result = await rsc_bot.teams(mock_guild, franchise=team.franchise.name)
                print(f"✓ teams(franchise='{team.franchise.name}') returned {len(result)} team(s)")

        except RscException as e:
            pytest.fail(f"teams() with filters raised RscException: {e}")
        except Exception as e:
            pytest.fail(f"teams() with filters raised unexpected exception: {e}")

    @pytest.mark.asyncio
    async def test_team_by_id_api_call(self, rsc_bot: RSC, mock_guild):
        """Test that team_by_id() API call doesn't raise exceptions."""
        try:
            teams = await rsc_bot.teams(mock_guild)
            if not teams:
                pytest.skip("No teams found to test team_by_id")

            team = teams[0]
            if not team.id:
                pytest.skip("Team has no ID")

            result = await rsc_bot.team_by_id(mock_guild, team.id)
            if result:
                print(f"✓ team_by_id() succeeded for team {team.id}")
                print(f"  - Name: {result.name}")
            else:
                print(f"✓ team_by_id() returned None for team {team.id}")

        except RscException as e:
            pytest.fail(f"team_by_id() raised RscException: {e}")
        except Exception as e:
            pytest.fail(f"team_by_id() raised unexpected exception: {e}")

    @pytest.mark.asyncio
    @pytest.mark.skip(reason="Creating teams may have side effects; enable when safe to test.")
    async def test_create_team_api_call(self, rsc_bot: RSC, mock_guild):
        """Test that create_team() API call doesn't raise exceptions."""
        try:
            # Define a new team data
            new_team_data = {
                "name": "Test Team",
                "franchise": "Test Franchise",
                "players": [],  # Assuming we can create a team without players for this test
            }

            # Create the team
            result = await rsc_bot.create_team(mock_guild, **new_team_data)
            assert result is not None
            assert result.name == new_team_data["name"]
            assert result.franchise == new_team_data["franchise"]
            print(f"✓ create_team() succeeded - ID: {result.id}, Name: {result.name}")

            # Clean up - delete the team we just created
            await rsc_bot.delete_team(mock_guild, result.id)
            print(f"✓ Team {result.id} deleted successfully")

        except RscException as e:
            pytest.fail(f"create_team() raised RscException: {e}")
        except Exception as e:
            pytest.fail(f"create_team() raised unexpected exception: {e}")

    @pytest.mark.asyncio
    @pytest.mark.skip(reason="Deleting teams may have side effects; enable when safe to test.")
    async def test_delete_team_api_call(self, rsc_bot: RSC, mock_guild):
        """Test that delete_team() API call doesn't raise exceptions."""
        try:
            teams = await rsc_bot.teams(mock_guild)
            if not teams:
                pytest.skip("No teams found to test delete_team")

            team = teams[0]
            if not team.id:
                pytest.skip("Team has no ID")

            # Delete the team
            await rsc_bot.delete_team(mock_guild, team.id)
            print(f"✓ delete_team() succeeded for team {team.id}")

            # Verify the team is deleted
            result = await rsc_bot.team_by_id(mock_guild, team.id)
            assert result is None
            print(f"✓ Team {team.id} is successfully deleted")

        except RscException as e:
            pytest.fail(f"delete_team() raised RscException: {e}")
        except Exception as e:
            pytest.fail(f"delete_team() raised unexpected exception: {e}")


class TestTeamsApiDataStructures:
    """Test that API responses have expected structure."""

    @pytest.mark.asyncio
    async def test_team_structure(self, rsc_bot: RSC, mock_guild):
        """Test that team objects have expected attributes."""
        try:
            teams = await rsc_bot.teams(mock_guild)
            if not teams:
                pytest.skip("No teams found to test structure")

            team = teams[0]
            assert hasattr(team, "id"), "Team should have 'id' attribute"
            assert hasattr(team, "name"), "Team should have 'name' attribute"
            assert hasattr(team, "franchise"), "Team should have 'franchise' attribute"
            print(f"✓ Team structure valid - ID: {team.id}, Name: {team.name}")
        except Exception as e:
            pytest.fail(f"Team structure test failed: {e}")


class TestTeamsApiHelperFunctions:
    """Test helper functions that use the API."""

    @pytest.mark.asyncio
    async def test_team_captain_from_team_name(self, rsc_bot: RSC, mock_guild):
        """Test that team_captain_from_team_name() helper function works."""
        try:
            teams = await rsc_bot.teams(mock_guild)
            if not teams:
                pytest.skip("No teams found to test captain lookup")

            team = teams[0]
            if not team.name:
                pytest.skip("Team has no name")

            result = await rsc_bot.team_captain(mock_guild, team.name)
            if result:
                print(f"✓ team_captain() returned captain: {result.player.discord_id}")
            else:
                print("✓ team_captain() returned None (no captain)")

        except ValueError as e:
            print(f"✓ team_captain() correctly handled multiple matches: {e}")
        except Exception as e:
            pytest.fail(f"team_captain() failed: {e}")

    @pytest.mark.asyncio
    async def test_teams_by_franchise_name(self, rsc_bot: RSC, mock_guild):
        """Test that teams_by_franchise_name() helper function works."""
        try:
            franchises = await rsc_bot.franchises(mock_guild)
            if not franchises:
                pytest.skip("No franchises found to test teams lookup")

            franchise = franchises[0]
            if not franchise.name:
                pytest.skip("Franchise has no name")

            result = await rsc_bot.teams(mock_guild, franchise=franchise.name)
            assert isinstance(result, list)
            print(f"✓ teams_by_franchise_name() returned {len(result)} team(s)")

        except Exception as e:
            pytest.fail(f"teams_by_franchise_name() failed: {e}")


if __name__ == "__main__":
    pytest.main([__file__, "-v", "-s"])
