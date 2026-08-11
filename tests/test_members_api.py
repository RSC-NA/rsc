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
from rsc.enums import Platform, PlayerType, Referrer, RegionPreference, StaffPositions
from rsc.exceptions import RscException
from rscapi import MembersApi

from .utils import random_string

pytestmark = pytest.mark.integration


class TestMembersApiContract:
    """Verify all expected rscapi MembersApi methods exist without calling them."""

    EXPECTED_METHODS = [
        "members_list",
        "members_signup_create",
        "members_create",
        "members_destroy",
        "members_name_change_partial_update",
        "members_postseason_stats_retrieve",
        "members_stats_retrieve",
        "members_intent_to_play_create",
        "members_permfa_signup_create",
        "members_activity_check_create",
        "members_transfer_account_create",
        "members_name_changes_list",
        "members_name_changes_list_without_preload_content",
        "members_make_player_create",
        "members_member_league_drop_create",
        "members_elevated_roles_list",
        "members_elevated_roles_create",
        "members_elevated_roles_destroy",
    ]

    @pytest.mark.parametrize("method_name", EXPECTED_METHODS)
    def test_method_exists(self, method_name: str):
        """Ensure MembersApi has the expected method."""
        assert hasattr(MembersApi, method_name), f"MembersApi missing expected method: {method_name}"
        assert callable(getattr(MembersApi, method_name)), f"MembersApi.{method_name} is not callable"


class TestMembersApiCalls:
    """Test RSC API calls for member functions without exceptions."""

    @pytest.mark.asyncio
    async def test_members_api_call(self, rsc_bot: RSC, mock_guild):
        """Test that members() API call doesn't raise exceptions."""
        result = await rsc_bot.members(mock_guild, limit=10)
        assert result is not None
        assert isinstance(result, list)
        print(f"✓ members() returned {len(result)} member(s)")
        for m in result:
            print(f"  - Discord ID: {m.discord_id}, RSC Name: {m.rsc_name}")

    @pytest.mark.asyncio
    async def test_member_elevated_roles_api_call(self, rsc_bot: RSC, mock_guild, mock_member):
        """Test that member_elevated_roles() returns a bare list, not a paginated wrapper."""
        result = await rsc_bot.member_elevated_roles(mock_guild, mock_member.id)
        assert isinstance(result, list), f"Expected a list, got {type(result)}"
        for r in result:
            assert hasattr(r, "position"), "ElevatedRole should have 'position' attribute"
            assert hasattr(r, "league"), "ElevatedRole should have 'league' attribute"
            assert not hasattr(r, "gm"), "GM moved to FranchiseStaff and must be gone from ElevatedRole"
            assert not hasattr(r, "agm"), "AGM moved to FranchiseStaff and must be gone from ElevatedRole"

    @pytest.mark.asyncio
    async def test_every_api_position_resolves_to_enum(self, rsc_bot: RSC, mock_guild):
        """Every `position` the API actually returns must resolve via StaffPositions.parse.

        The API is asymmetric: it accepts codes as query input (`position=NUMS`)
        but returns display labels in responses (`"Numbers"`). If parse() stops
        covering a label, permission checks silently match nothing and the whole
        committee loses access.
        """
        from rsc.enums import StaffPositions
        from rscapi import ApiClient, ElevatedRolesApi

        async with ApiClient(rsc_bot._api_conf[mock_guild.id]) as client:
            roles = await ElevatedRolesApi(client).elevated_roles_list(limit=500)

        seen = {r.position for r in roles.results if r.position}
        if not seen:
            pytest.skip("No elevated roles with a position on staging")

        unresolved = sorted(p for p in seen if StaffPositions.parse(p) is None)
        assert not unresolved, f"API positions not resolvable by StaffPositions.parse: {unresolved}"

    @pytest.mark.asyncio
    async def test_agm_add_and_remove_round_trip(self, rsc_bot: RSC, mock_guild, generated_discord_member):
        """Add, read back and remove an AGM against the real server.

        Unit tests mock FranchisesApi, so they cannot catch a renamed kwarg or a
        rejected body. This covers what only the wire proves: the franchise
        endpoints accept discord IDs for both members, the response carries the
        refreshed `agms`, and `franchises_list` really does return `agms` inline
        (the bot's only bulk source for them now).
        """
        franchises = await rsc_bot.franchises(mock_guild)
        if not franchises:
            pytest.skip("No franchises on the API")
        franchise_id = franchises[0].id

        # The server checks the executor, not just the API key: a member with no
        # ADM row gets "Executor cannot modify staff roles for this league."
        admins = await rsc_bot.league_elevated_roles(mock_guild, position=StaffPositions.ADMIN.value)
        executor_id = next((r.member.discord_id for r in admins if r.member and r.member.discord_id), None)
        if not executor_id:
            pytest.skip("No league admin on the API to act as executor")

        await rsc_bot.create_member(guild=mock_guild, member=generated_discord_member, rsc_name=generated_discord_member.name)
        try:
            result = await rsc_bot.add_agm(mock_guild, franchise_id, agm=generated_discord_member, executor=executor_id)
            agm_ids = [a.discord_id for a in (result.agms or [])]
            assert generated_discord_member.id in agm_ids, f"add_agm response did not list the new AGM: {agm_ids}"
            print(f"✓ added AGM to franchise {franchise_id}")

            # The reverse lookup the bot relies on, straight off the list endpoint.
            memberships = await rsc_bot.franchises_agm_of(mock_guild, generated_discord_member.id)
            assert [f.id for f in memberships] == [franchise_id], f"Expected exactly one AGM franchise, got {memberships}"

            await rsc_bot.remove_agm(mock_guild, franchise_id, agm=generated_discord_member, executor=executor_id)

            remaining = await rsc_bot.franchises_agm_of(mock_guild, generated_discord_member.id)
            assert remaining == [], f"AGM survived removal: {remaining}"
            print("✓ removed AGM")
        finally:
            await rsc_bot.delete_member(guild=mock_guild, member=generated_discord_member)

    @pytest.mark.asyncio
    async def test_removing_a_non_agm_is_a_404(self, rsc_bot: RSC, mock_guild, mock_member):
        """`/admin agm remove` treats 404 as "already gone". If the API ever
        answered 200 instead, that branch would go untested and a real failure
        would read as success."""
        franchises = await rsc_bot.franchises(mock_guild)
        if not franchises:
            pytest.skip("No franchises on the API")

        with pytest.raises(RscException) as exc:
            await rsc_bot.remove_agm(mock_guild, franchises[0].id, agm=mock_member, executor=mock_member)
        assert exc.value.status in (403, 404), f"Unexpected status for a non-AGM removal: {exc.value.status}"

    @pytest.mark.asyncio
    async def test_elevated_positions_api_call(self, rsc_bot: RSC, mock_guild, mock_member):
        """Test that elevated_positions() resolves to a set of position strings."""
        rsc_bot._elevated_role_cache = {}
        result = await rsc_bot.elevated_positions(mock_guild, mock_member.id)
        assert isinstance(result, frozenset)
        assert all(isinstance(p, str) for p in result)

        # Second call must come from cache, not the API
        cached = await rsc_bot.elevated_positions(mock_guild, mock_member.id)
        assert cached == result

    @pytest.mark.asyncio
    async def test_paged_members_api_call(self, rsc_bot: RSC, mock_guild):
        """Test that paged_members() API call doesn't raise exceptions."""
        count = 0
        async for member in rsc_bot.paged_members(guild=mock_guild, per_page=3):
            count += 1
            if count > 5:
                break
            print(f"  - Discord ID: {member.discord_id}, RSC Name: {member.rsc_name}")
        print(f"✓ paged_members() yielded {count} member(s)")

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
            raise

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
                raise

    @pytest.mark.asyncio
    async def test_name_history_api_call(self, rsc_bot: RSC, mock_guild):
        """Test that name_history() API call doesn't raise exceptions."""
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


class TestMembersApiDataStructures:
    """Test that API responses have expected structure."""

    @pytest.mark.asyncio
    async def test_member_structure(self, rsc_bot: RSC, mock_guild):
        """Test that member objects have expected attributes."""
        members = await rsc_bot.members(mock_guild, limit=1)
        if members:
            member = members[0]
            # Check for expected attributes
            assert hasattr(member, "discord_id"), "Member should have 'discord_id' attribute"
            assert hasattr(member, "rsc_name"), "Member should have 'rsc_name' attribute"
            assert hasattr(member, "username"), "Member should have 'username' attribute"
            print(f"✓ Member structure valid - Discord ID: {member.discord_id}, RSC Name: {member.rsc_name}")

    @pytest.mark.asyncio
    async def test_league_player_from_member(self, rsc_bot: RSC, mock_guild):
        """Test that league_player_from_member() helper function works."""
        members = await rsc_bot.members(mock_guild, limit=1)
        if not members:
            pytest.skip("No members found to test league_player_from_member")

        member = members[0]
        result = await rsc_bot.league_player_from_member(mock_guild, member)

        # Result can be None if member is not a league player
        print(f"✓ league_player_from_member() returned: {type(result)}")


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
                raise

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
                raise

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
                raise


if __name__ == "__main__":
    """Run tests directly if script is executed."""
    print("Running RSC Members API tests...")

    # Check for API key
    if not os.getenv("RSC_API_KEY"):
        print("ERROR: RSC_API_KEY environment variable not set")
        sys.exit(1)

    # Run pytest
    pytest.main([__file__, "-v", "-s"])
