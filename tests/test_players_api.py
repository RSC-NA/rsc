import sys
from pathlib import Path

import pytest

# Add the project root to the path so we can import the modules
project_root = Path(__file__).parent.parent
sys.path.insert(0, str(project_root))

from rsc.core import RSC
from rsc.exceptions import RscException
from rsc.enums import Status


class TestPlayersApiCalls:
    """Test RSC API calls for player functions without exceptions."""

    @pytest.mark.asyncio
    async def test_players_api_call(self, rsc_bot: RSC, mock_guild):
        """Test that players() API call doesn't raise exceptions."""
        try:
            result = await rsc_bot.players(mock_guild, limit=10)
            assert result is not None
            assert isinstance(result, list)
            print(f"✓ players() returned {len(result)} player(s)")
            for p in result:
                status = Status(p.status).full_name if p.status else "Unknown"
                print(f"  - ID: {p.id}, Name: {p.player.name}, Status: {status}")
        except RscException as e:
            pytest.fail(f"players() raised RscException: {e}")
        except Exception as e:
            pytest.fail(f"players() raised unexpected exception: {e}")

    @pytest.mark.asyncio
    async def test_players_with_filters_api_call(self, rsc_bot: RSC, mock_guild):
        """Test that players() API call with filters doesn't raise exceptions."""
        try:
            # Test filtering by status
            result = await rsc_bot.players(mock_guild, status=Status.ROSTERED, limit=5)
            print(f"✓ players(status=ROSTERED) returned {len(result)} player(s)")

            # Test filtering by discord ID
            players = await rsc_bot.players(mock_guild, limit=1)
            if players and players[0].player.discord_id:
                result = await rsc_bot.players(mock_guild, discord_id=players[0].player.discord_id)
                print(f"✓ players(discord_id) returned {len(result)} player(s)")

        except RscException as e:
            pytest.fail(f"players() with filters raised RscException: {e}")
        except Exception as e:
            pytest.fail(f"players() with filters raised unexpected exception: {e}")

    @pytest.mark.asyncio
    async def test_paged_players_api_call(self, rsc_bot: RSC, mock_guild):
        """Test that paged_players() API call doesn't raise exceptions."""
        try:
            count = 0
            async for player in rsc_bot.paged_players(guild=mock_guild, per_page=3):
                count += 1
                if count > 5:
                    break
                status = Status(player.status).full_name if player.status else "Unknown"
                print(f"  - Player: {player.player.name}, Status: {status}")
            print(f"✓ paged_players() yielded {count} player(s)")
        except RscException as e:
            pytest.fail(f"paged_players() raised RscException: {e}")
        except Exception as e:
            pytest.fail(f"paged_players() raised unexpected exception: {e}")

    @pytest.mark.asyncio
    async def test_total_players_api_call(self, rsc_bot: RSC, mock_guild):
        """Test that total_players() API call doesn't raise exceptions."""
        try:
            result = await rsc_bot.total_players(mock_guild)
            assert isinstance(result, int)
            assert result >= 0
            print(f"✓ total_players() returned {result}")
        except RscException as e:
            pytest.fail(f"total_players() raised RscException: {e}")
        except Exception as e:
            pytest.fail(f"total_players() raised unexpected exception: {e}")

    @pytest.mark.asyncio
    async def test_player_intents_api_call(self, rsc_bot: RSC, mock_guild):
        """Test that player_intents() API call doesn't raise exceptions."""
        try:
            # Get current season for intents
            season = await rsc_bot.current_season(mock_guild)
            if not season or not season.id:
                pytest.skip("No current season found for intents test")

            result = await rsc_bot.player_intents(mock_guild, season_id=season.id)
            assert isinstance(result, list)
            print(f"✓ player_intents() returned {len(result)} intent(s)")

        except RscException as e:
            pytest.fail(f"player_intents() raised RscException: {e}")
        except Exception as e:
            pytest.fail(f"player_intents() raised unexpected exception: {e}")


class TestPlayersApiDataStructures:
    """Test that API responses have expected structure."""

    @pytest.mark.asyncio
    async def test_player_structure(self, rsc_bot: RSC, mock_guild):
        """Test that player objects have expected attributes."""
        try:
            players = await rsc_bot.players(mock_guild, limit=1)
            if not players:
                pytest.skip("No players found to test structure")

            player = players[0]
            assert hasattr(player, "id"), "Player should have 'id' attribute"
            assert hasattr(player, "player"), "Player should have 'player' attribute"
            assert hasattr(player, "status"), "Player should have 'status' attribute"
            print(f"✓ Player structure valid - ID: {player.id}, Name: {player.player.name}")
        except Exception as e:
            pytest.fail(f"Player structure test failed: {e}")


if __name__ == "__main__":
    pytest.main([__file__, "-v", "-s"])
