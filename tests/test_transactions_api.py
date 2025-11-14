import sys
from pathlib import Path

import pytest

# Add the project root to the path so we can import the modules
project_root = Path(__file__).parent.parent
sys.path.insert(0, str(project_root))

from rsc.core import RSC
from rsc.exceptions import RscException
from rsc.enums import TransactionType
from rscapi.models.franchise_identifier import FranchiseIdentifier


class TestTransactionsApiCalls:
    """Test RSC API calls for transaction functions without exceptions."""

    @pytest.mark.asyncio
    @pytest.mark.skip(reason="Skipping transaction tests to avoid changing API data")
    async def test_sign_api_call(self, rsc_bot: RSC, mock_guild, mock_member):
        """Test that sign() API call doesn't raise exceptions."""
        try:
            # Get a team to sign to
            teams = await rsc_bot.teams(mock_guild)
            if not teams:
                pytest.skip("No teams found to test sign")

            team = teams[0]
            if not team.name:
                pytest.skip("Team has no name")

            result = await rsc_bot.sign(
                guild=mock_guild, player=mock_member, team=team.name, executor=mock_member, notes="Development Bot Pytest", override=True
            )
            print(f"✓ sign() succeeded for player {mock_member.id}")
        except RscException as e:
            if e.status in [400, 404, 409]:
                print(f"✓ sign() correctly handled business rule (status {e.status}): {e.reason}")
            else:
                pytest.fail(f"sign() raised unexpected RscException: {e}")
        except Exception as e:
            pytest.fail(f"sign() raised unexpected exception: {e}")

    @pytest.mark.asyncio
    @pytest.mark.skip(reason="Skipping transaction tests to avoid changing API data")
    async def test_cut_api_call(self, rsc_bot: RSC, mock_guild, mock_member):
        """Test that cut() API call doesn't raise exceptions."""
        try:
            result = await rsc_bot.cut(
                guild=mock_guild, player=mock_member, executor=mock_member, notes="Development Bot Pytest", override=True
            )
            print(f"✓ cut() succeeded for player {mock_member.id}")
        except RscException as e:
            if e.status in [400, 404, 409]:
                print(f"✓ cut() correctly handled business rule (status {e.status}): {e.reason}")
            else:
                pytest.fail(f"cut() raised unexpected RscException: {e}")
        except Exception as e:
            pytest.fail(f"cut() raised unexpected exception: {e}")

    @pytest.mark.asyncio
    @pytest.mark.skip(reason="Skipping transaction tests to avoid changing API data")
    async def test_resign_api_call(self, rsc_bot: RSC, mock_guild, mock_member):
        """Test that resign() API call doesn't raise exceptions."""
        try:
            # Get a team to resign to
            teams = await rsc_bot.teams(mock_guild)
            if not teams:
                pytest.skip("No teams found to test resign")

            team = teams[0]
            if not team.name:
                pytest.skip("Team has no name")

            result = await rsc_bot.resign(
                guild=mock_guild, player=mock_member, team=team.name, executor=mock_member, notes="Development Bot Pytest", override=True
            )
            print(f"✓ resign() succeeded for player {mock_member.id}")
        except RscException as e:
            if e.status in [400, 404, 409]:
                print(f"✓ resign() correctly handled business rule (status {e.status}): {e.reason}")
            else:
                pytest.fail(f"resign() raised unexpected RscException: {e}")
        except Exception as e:
            pytest.fail(f"resign() raised unexpected exception: {e}")

    @pytest.mark.asyncio
    @pytest.mark.skip(reason="Skipping transaction tests to avoid changing API data")
    async def test_set_captain_api_call(self, rsc_bot: RSC, mock_guild):
        """Test that set_captain() API call doesn't raise exceptions."""
        try:
            # Get a player to test with
            players = await rsc_bot.players(mock_guild, limit=1)
            if not players:
                pytest.skip("No players found to test set_captain")

            player = players[0]
            if not player.id:
                pytest.skip("Player has no ID")

            result = await rsc_bot.set_captain(mock_guild, player.id)
            print(f"✓ set_captain() succeeded for player {player.id}")
        except RscException as e:
            if e.status in [400, 404, 409]:
                print(f"✓ set_captain() correctly handled business rule (status {e.status}): {e.reason}")
            else:
                pytest.fail(f"set_captain() raised unexpected RscException: {e}")
        except Exception as e:
            pytest.fail(f"set_captain() raised unexpected exception: {e}")

    @pytest.mark.asyncio
    @pytest.mark.skip(reason="Skipping transaction tests to avoid changing API data")
    async def test_substitution_api_call(self, rsc_bot: RSC, mock_guild, mock_member, generated_discord_member):
        """Test that substitution() API call doesn't raise exceptions."""
        try:
            result = await rsc_bot.substitution(
                guild=mock_guild,
                player_in=generated_discord_member,
                player_out=mock_member,
                executor=mock_member,
                notes="Test substitution",
                override=True,
            )
            print("✓ substitution() succeeded")
        except RscException as e:
            if e.status in [400, 404, 409]:
                print(f"✓ substitution() correctly handled business rule (status {e.status}): {e.reason}")
            else:
                pytest.fail(f"substitution() raised unexpected RscException: {e}")
        except Exception as e:
            pytest.fail(f"substitution() raised unexpected exception: {e}")

    @pytest.mark.asyncio
    @pytest.mark.skip(reason="Skipping transaction tests to avoid changing API data")
    async def test_expire_sub_api_call(self, rsc_bot: RSC, mock_guild, mock_member):
        """Test that expire_sub() API call doesn't raise exceptions."""
        try:
            result = await rsc_bot.expire_sub(guild=mock_guild, player=mock_member, executor=mock_member)
            print(f"✓ expire_sub() succeeded for player {mock_member.id}")
        except RscException as e:
            if e.status in [400, 404, 409]:
                print(f"✓ expire_sub() correctly handled business rule (status {e.status}): {e.reason}")
            else:
                pytest.fail(f"expire_sub() raised unexpected RscException: {e}")
        except Exception as e:
            pytest.fail(f"expire_sub() raised unexpected exception: {e}")

    @pytest.mark.asyncio
    @pytest.mark.skip(reason="Skipping transaction tests to avoid changing API data")
    async def test_retire_api_call(self, rsc_bot: RSC, mock_guild, mock_member):
        """Test that retire() API call doesn't raise exceptions."""
        try:
            result = await rsc_bot.retire(
                guild=mock_guild, player=mock_member, executor=mock_member, notes="Development Bot Pytest", override=True
            )
            print(f"✓ retire() succeeded for player {mock_member.id}")
        except RscException as e:
            if e.status in [400, 404, 409]:
                print(f"✓ retire() correctly handled business rule (status {e.status}): {e.reason}")
            else:
                pytest.fail(f"retire() raised unexpected RscException: {e}")
        except Exception as e:
            pytest.fail(f"retire() raised unexpected exception: {e}")

    @pytest.mark.asyncio
    @pytest.mark.skip(reason="Skipping transaction tests to avoid changing API data")
    async def test_inactive_reserve_api_call(self, rsc_bot: RSC, mock_guild, mock_member):
        """Test that inactive_reserve() API call doesn't raise exceptions."""
        try:
            result = await rsc_bot.inactive_reserve(
                guild=mock_guild, player=mock_member, executor=mock_member, notes="Test IR", override=True, redshirt=False, remove=False
            )
            print(f"✓ inactive_reserve() succeeded for player {mock_member.id}")
        except RscException as e:
            if e.status in [400, 404, 409]:
                print(f"✓ inactive_reserve() correctly handled business rule (status {e.status}): {e.reason}")
            else:
                pytest.fail(f"inactive_reserve() raised unexpected RscException: {e}")
        except Exception as e:
            pytest.fail(f"inactive_reserve() raised unexpected exception: {e}")

    @pytest.mark.asyncio
    async def test_transaction_history_api_call(self, rsc_bot: RSC, mock_guild):
        """Test that transaction_history() API call doesn't raise exceptions."""
        try:
            result = await rsc_bot.transaction_history(mock_guild, limit=10)
            assert isinstance(result, list)
            print(f"✓ transaction_history() returned {len(result)} transaction(s)")
        except RscException as e:
            pytest.fail(f"transaction_history() raised RscException: {e}")
        except Exception as e:
            pytest.fail(f"transaction_history() raised unexpected exception: {e}")

    @pytest.mark.asyncio
    async def test_paged_transaction_history_api_call(self, rsc_bot: RSC, mock_guild):
        """Test that paged_transaction_history() API call doesn't raise exceptions."""
        try:
            count = 0
            async for transaction in rsc_bot.paged_transaction_history(guild=mock_guild, per_page=5):
                count += 1
                if count > 3:
                    break
                tx_type = TransactionType(transaction.type).name if transaction.type else "Unknown"
                print(f"  - Type: {tx_type}")
            print(f"✓ paged_transaction_history() yielded {count} transaction(s)")
        except RscException as e:
            pytest.fail(f"paged_transaction_history() raised RscException: {e}")
        except Exception as e:
            pytest.fail(f"paged_transaction_history() raised unexpected exception: {e}")

    @pytest.mark.asyncio
    async def test_transaction_history_by_id_api_call(self, rsc_bot: RSC, mock_guild):
        """Test that transaction_history_by_id() API call doesn't raise exceptions."""
        try:
            # Get a transaction first
            transactions = await rsc_bot.transaction_history(mock_guild, limit=1)
            if not transactions:
                pytest.skip("No transactions found to test transaction_history_by_id")

            transaction = transactions[0]
            if not transaction.id:
                pytest.skip("Transaction has no ID")

            result = await rsc_bot.transaction_history_by_id(mock_guild, transaction.id)
            print(f"✓ transaction_history_by_id() succeeded for transaction {transaction.id}")
        except RscException as e:
            pytest.fail(f"transaction_history_by_id() raised RscException: {e}")
        except Exception as e:
            pytest.fail(f"transaction_history_by_id() raised unexpected exception: {e}")

    @pytest.mark.asyncio
    @pytest.mark.skip(reason="Skipping transaction tests to avoid changing API data")
    async def test_trade_api_call(self, rsc_bot: RSC, mock_guild, mock_member):
        """Test that trade() API call doesn't raise exceptions."""
        try:
            # Create mock trade items
            franchises = await rsc_bot.franchises(mock_guild)
            if len(franchises) < 2:
                pytest.skip("Need at least 2 franchises to test trade")

            source_franchise = FranchiseIdentifier(
                id=franchises[0].id, name=franchises[0].name, gm=franchises[0].gm.discord_id if franchises[0].gm else None
            )

            dest_franchise = FranchiseIdentifier(
                id=franchises[1].id, name=franchises[1].name, gm=franchises[1].gm.discord_id if franchises[1].gm else None
            )

            # Mock trade item - this is just for testing API structure
            trade_items = []  # Empty list since this will likely fail anyway

            result = await rsc_bot.trade(guild=mock_guild, trades=trade_items, executor=mock_member, notes="Test trade", override=True)
            print("✓ trade() succeeded unexpectedly")
        except RscException as e:
            if e.status in [400, 404, 409]:
                print(f"✓ trade() correctly handled business rule (status {e.status}): {e.reason}")
            else:
                pytest.fail(f"trade() raised unexpected RscException: {e}")
        except Exception as e:
            pytest.fail(f"trade() raised unexpected exception: {e}")

    @pytest.mark.asyncio
    @pytest.mark.skip(reason="Skipping transaction tests to avoid changing API data")
    async def test_draft_api_call(self, rsc_bot: RSC, mock_guild, mock_member):
        """Test that draft() API call doesn't raise exceptions."""
        try:
            # Get a team for drafting
            teams = await rsc_bot.teams(mock_guild)
            if not teams:
                pytest.skip("No teams found to test draft")

            team = teams[0]
            if not team.name:
                pytest.skip("Team has no name")

            result = await rsc_bot.draft(
                guild=mock_guild, player=mock_member, executor=mock_member, team=team.name, round=1, pick=1, override=True
            )
            print(f"✓ draft() succeeded for player {mock_member.id}")
        except RscException as e:
            if e.status in [400, 404, 409]:
                print(f"✓ draft() correctly handled business rule (status {e.status}): {e.reason}")
            else:
                pytest.fail(f"draft() raised unexpected RscException: {e}")
        except Exception as e:
            pytest.fail(f"draft() raised unexpected exception: {e}")


class TestTransactionsApiDataStructures:
    """Test that API responses have expected structure."""

    @pytest.mark.asyncio
    async def test_transaction_response_structure(self, rsc_bot: RSC, mock_guild):
        """Test that transaction response objects have expected attributes."""
        try:
            transactions = await rsc_bot.transaction_history(mock_guild, limit=1)
            if not transactions:
                pytest.skip("No transactions found to test structure")

            transaction = transactions[0]
            assert hasattr(transaction, "id"), "Transaction should have 'id' attribute"
            assert hasattr(transaction, "type"), "Transaction should have 'type' attribute"
            assert hasattr(transaction, "executor"), "Transaction should have 'executor' attribute"
            print(f"✓ Transaction structure valid - ID: {transaction.id}")
        except Exception as e:
            pytest.fail(f"Transaction structure test failed: {e}")


class TestTransactionsApiHelperFunctions:
    """Test helper functions that use the API."""

    @pytest.mark.asyncio
    @pytest.mark.skip(reason="Not fully implemented; enable when ready.")
    async def test_parse_trade_text(self, rsc_bot: RSC, mock_guild):
        """Test that parse_trade_text() helper function works."""
        # This will likely fail since we don't have real trade data
        test_trade_text = "Test trade data"

        result = await rsc_bot.parse_trade_text(guild=mock_guild, data=test_trade_text)
        print(f"✓ parse_trade_text() returned {len(result)} trade item(s)")

if __name__ == "__main__":
    pytest.main([__file__, "-v", "-s"])
