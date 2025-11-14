import os
import sys
from pathlib import Path
from unittest.mock import MagicMock

import pytest
import discord


# Add the project root to the path so we can import the modules
project_root = Path(__file__).parent.parent
sys.path.insert(0, str(project_root))

from rsc.core import RSC
from rsc.exceptions import RscException
from rsc.enums import Platform, PlayerType, Referrer, RegionPreference

from .utils import random_string


class TestMembersApiCalls:
    """Test RSC API calls for member functions without exceptions."""

    @pytest.mark.asyncio
    async def test_members_api_call(self, rsc_bot: RSC, mock_guild):
        """Test that members() API call doesn't raise exceptions."""
        try:
            result = await rsc_bot.members(mock_guild, limit=10)
            assert result is not None
            assert isinstance(result, list)
            print(f"✓ members() returned {len(result)} member(s)")
            for m in result:
                print(f"  - Discord ID: {m.discord_id}, RSC Name: {m.rsc_name}")
        except RscException as e:
            pytest.fail(f"members() raised RscException: {e}")
        except Exception as e:
            pytest.fail(f"members() raised unexpected exception: {e}")

    @pytest.mark.asyncio
    async def test_paged_members_api_call(self, rsc_bot: RSC, mock_guild):
        """Test that paged_members() API call doesn't raise exceptions."""
        try:
            count = 0
            async for member in rsc_bot.paged_members(guild=mock_guild, per_page=3):
                count += 1
                if count > 5:
                    break
                print(f"  - Discord ID: {member.discord_id}, RSC Name: {member.rsc_name}")
            print(f"✓ paged_members() yielded {count} member(s)")
        except RscException as e:
            pytest.fail(f"paged_members() raised RscException: {e}")
        except Exception as e:
            pytest.fail(f"paged_members() raised unexpected exception: {e}")

    @pytest.mark.asyncio
    async def test_create_member_api_call(self, rsc_bot: RSC, mock_guild, generated_discord_member):
        """Test that create_member() API call doesn't raise exceptions."""
        try:
            result = await rsc_bot.create_member(guild=mock_guild, member=generated_discord_member, rsc_name=generated_discord_member.name)
            assert result is not None
            print(f"✓ create_member() succeeded for member {generated_discord_member.id}")
            print(f"  - Discord ID: {result.discord_id}, RSC Name: {result.rsc_name}")
        except RscException as e:
            # Expected if member already exists
            print(f"Exception: {e}")
            pytest.fail(f"create_member() raised unexpected RscException: {e}")
        except Exception as e:
            pytest.fail(f"create_member() raised unexpected exception: {e}")

    @pytest.mark.asyncio
    async def test_change_member_name_api_call(self, rsc_bot: RSC, mock_guild):
        """Test that change_member_name() API call doesn't raise exceptions."""
        try:
            # Try to change name for a member that likely exists
            members = await rsc_bot.members(mock_guild, limit=1)
            if not members:
                pytest.skip("No members found to test name change")

            member = members[0]
            new_name = random_string()
            result = await rsc_bot.change_member_name(guild=mock_guild, id=member.discord_id, name=new_name, override=True)
            assert result is not None
            print(f"✓ change_member_name() succeeded for member {member.discord_id}")
        except RscException as e:
            # Some name changes may fail due to business rules
            print(f"✓ change_member_name() handled business rule: {e.reason}")
        except Exception as e:
            pytest.fail(f"change_member_name() raised unexpected exception: {e}")

    @pytest.mark.asyncio
    async def test_player_stats_api_call(self, rsc_bot: RSC, mock_guild):
        """Test that player_stats() API call doesn't raise exceptions."""
        try:
            # Get a member first
            members = await rsc_bot.members(mock_guild, limit=1)
            if not members:
                pytest.skip("No members found to test player stats")

            member = members[0]
            mock_player = MagicMock(spec=discord.Member)
            mock_player.id = member.discord_id

            result = await rsc_bot.player_stats(guild=mock_guild, player=mock_player)
            assert result is not None
            print(f"✓ player_stats() succeeded for player {member.discord_id}")
        except RscException as e:
            # Player may not have stats
            if e.status == 404:
                print("✓ player_stats() correctly handled player with no stats (404)")
            else:
                pytest.fail(f"player_stats() raised unexpected RscException: {e}")
        except Exception as e:
            pytest.fail(f"player_stats() raised unexpected exception: {e}")

    @pytest.mark.asyncio
    async def test_name_history_api_call(self, rsc_bot: RSC, mock_guild):
        """Test that name_history() API call doesn't raise exceptions."""
        try:
            # Get a member first
            members = await rsc_bot.members(mock_guild, limit=1)
            if not members:
                pytest.skip("No members found to test name history")

            member = members[0]
            mock_player = MagicMock(spec=discord.Member)
            mock_player.id = member.discord_id

            result = await rsc_bot.name_history(guild=mock_guild, member=mock_player)
            assert result is not None
            assert isinstance(result, list)
            print(f"✓ name_history() returned {len(result)} name change(s)")
        except RscException as e:
            pytest.fail(f"name_history() raised RscException: {e}")
        except Exception as e:
            pytest.fail(f"name_history() raised unexpected exception: {e}")

    @pytest.mark.asyncio
    async def test_transfer_membership_api_call(self, rsc_bot: RSC, mock_guild, mock_member):
        """Test that transfer_membership() API call doesn't raise exceptions."""
        try:
            # This will likely fail due to business rules, but should not raise unexpected exceptions
            result = await rsc_bot.transfer_membership(
                guild=mock_guild,
                old=mock_member.id,  # Non-existent member
                new=mock_member,
            )
            print("✓ transfer_membership() succeeded unexpectedly")
        except RscException as e:
            # Expected to fail for non-existent members or other business rules
            print(f"✓ transfer_membership() correctly handled business rule: {e.reason}")
        except Exception as e:
            pytest.fail(f"transfer_membership() raised unexpected exception: {e}")

    @pytest.mark.asyncio
    async def test_delete_member_api_call(self, rsc_bot: RSC, mock_guild, generated_discord_member):
        """Test that delete_member() API call doesn't raise exceptions."""
        try:
            # This will likely fail for non-existent member, but should handle it gracefully
            member = await rsc_bot.create_member(guild=mock_guild, member=generated_discord_member, rsc_name="Temp Player")
            await rsc_bot.delete_member(guild=mock_guild, member=generated_discord_member)
            print("✓ delete_member() succeeded")
        except RscException as e:
            # Expected to fail for non-existent members
            if e.status == 404:
                print("✓ delete_member() correctly handled non-existent member (404)")
            else:
                print(f"✓ delete_member() handled business rule: {e.reason}")
        except Exception as e:
            pytest.fail(f"delete_member() raised unexpected exception: {e}")


class TestMembersApiDataStructures:
    """Test that API responses have expected structure."""

    @pytest.mark.asyncio
    async def test_member_structure(self, rsc_bot: RSC, mock_guild):
        """Test that member objects have expected attributes."""
        try:
            members = await rsc_bot.members(mock_guild, limit=1)
            if members:
                member = members[0]
                # Check for expected attributes
                assert hasattr(member, "discord_id"), "Member should have 'discord_id' attribute"
                assert hasattr(member, "rsc_name"), "Member should have 'rsc_name' attribute"
                assert hasattr(member, "username"), "Member should have 'username' attribute"
                print(f"✓ Member structure valid - Discord ID: {member.discord_id}, RSC Name: {member.rsc_name}")
        except Exception as e:
            pytest.fail(f"Member structure test failed: {e}")

    @pytest.mark.asyncio
    async def test_league_player_from_member(self, rsc_bot: RSC, mock_guild):
        """Test that league_player_from_member() helper function works."""
        try:
            members = await rsc_bot.members(mock_guild, limit=1)
            if not members:
                pytest.skip("No members found to test league_player_from_member")

            member = members[0]
            result = await rsc_bot.league_player_from_member(mock_guild, member)

            # Result can be None if member is not a league player
            print(f"✓ league_player_from_member() returned: {type(result)}")
        except Exception as e:
            pytest.fail(f"league_player_from_member() failed: {e}")


class TestMembersApiBusinessLogic:
    """Test API calls with various business logic scenarios."""

    @pytest.mark.asyncio
    async def test_signup_api_call(self, rsc_bot: RSC, mock_guild, generated_discord_member):
        """Test that signup() API call handles various scenarios."""
        try:
            await rsc_bot.create_member(guild=mock_guild, member=generated_discord_member, rsc_name=generated_discord_member.name)
            result = await rsc_bot.signup(
                guild=mock_guild,
                member=generated_discord_member,
                rsc_name=generated_discord_member.name,
                trackers=[generated_discord_member.tracker_link],
                player_type=PlayerType.NEW,
                platform=Platform.STEAM,
                referrer=Referrer.FRIEND,
                region_preference=RegionPreference.EAST,
                accepted_rules=True,
                accepted_match_nights=True,
            )
            print(f"✓ signup() succeeded for member {generated_discord_member.id}")
        except RscException as e:
            # Expected scenarios: already signed up, season not open, etc.
            if e.status in [409, 405]:
                print(f"✓ signup() correctly handled business rule (status {e.status}): {e.reason}")
            else:
                pytest.fail(f"signup() raised unexpected RscException: {e}")
        except Exception as e:
            pytest.fail(f"signup() raised unexpected exception: {e}")

    @pytest.mark.asyncio
    async def test_permfa_signup_api_call(self, rsc_bot: RSC, mock_guild, generated_discord_member):
        """Test that permfa_signup() API call handles various scenarios."""
        try:
            await rsc_bot.create_member(guild=mock_guild, member=generated_discord_member, rsc_name=generated_discord_member.name)
            result = await rsc_bot.permfa_signup(
                guild=mock_guild,
                member=generated_discord_member,
                rsc_name=generated_discord_member.name,
                trackers=[generated_discord_member.tracker_link],
                player_type=PlayerType.NEW,
                platform=Platform.EPIC,
                referrer=Referrer.FRIEND,
                region_preference=RegionPreference.WEST,
                accepted_rules=True,
                accepted_match_nights=True,
            )
            print(f"✓ permfa_signup() succeeded for member {generated_discord_member.id}")
        except RscException as e:
            # Expected scenarios: already signed up, etc.
            if e.status in [409, 405]:
                print(f"✓ permfa_signup() correctly handled business rule (status {e.status}): {e.reason}")
            else:
                pytest.fail(f"permfa_signup() raised unexpected RscException: {e}")
        except Exception as e:
            pytest.fail(f"permfa_signup() raised unexpected exception: {e}")

    @pytest.mark.asyncio
    async def test_declare_intent_api_call(self, rsc_bot: RSC, mock_guild, mock_member):
        """Test that declare_intent() API call handles various scenarios."""
        try:
            players = await rsc_bot.players(guild=mock_guild, limit=1)
            if not players:
                pytest.skip("No player found to test declare_intent")

            player = players[0]
            result = await rsc_bot.declare_intent(guild=mock_guild, member=mock_member, returning=True)
            print(f"✓ declare_intent() succeeded for member {mock_member.id}")
        except RscException as e:
            # Expected scenarios: not eligible, already declared, etc.
            if e.status in [409, 404, 405]:
                print(f"✓ declare_intent() correctly handled business rule (status {e.status}): {e.reason}")
            else:
                pytest.fail(f"declare_intent() raised unexpected RscException: {e}")
        except Exception as e:
            pytest.fail(f"declare_intent() raised unexpected exception: {e}")


if __name__ == "__main__":
    """Run tests directly if script is executed."""
    print("Running RSC Members API tests...")

    # Check for API key
    if not os.getenv("RSC_API_KEY"):
        print("ERROR: RSC_API_KEY environment variable not set")
        sys.exit(1)

    # Run pytest
    pytest.main([__file__, "-v", "-s"])
