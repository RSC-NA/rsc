import json
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock, patch
from zoneinfo import ZoneInfo

import discord
import pytest
from rscapi.exceptions import ApiException
from rscapi.models.player import Player
from rscapi.models.player_transaction_updates import PlayerTransactionUpdates
from rscapi.models.transaction_response import TransactionResponse
from rscapi.models.franchise_identifier import FranchiseIdentifier
from rscapi.models.draft_pick_trade import DraftPickTrade
from rscapi.models.franchise_futures_validation import FranchiseFuturesValidation
from rscapi.models.franchise_futures_validation_response import FranchiseFuturesValidationResponse
from rscapi.models.trade_franchise import TradeFranchise
from rscapi.models.trade_item import TradeItem
from rscapi.models.trade_object import TradeObject
from rscapi.models.trade_player import TradePlayer
from rscapi.models.league_player import LeaguePlayer

from rsc.enums import Status, TransactionType
from rsc.exceptions import (
    MalformedTransactionResponse,
    PastTransactionsEndDate,
    RscException,
    TradeParserException,
)
from rsc.transactions.views import TransactionCard
from rsc.transactions.transactions import (
    FUTURE_TRADE_REGEX,
    GM_TRADE_REGEX,
    PICK_TRADE_REGEX,
    PLAYER_TRADE_REGEX,
    RETIRE_MAX_ATTEMPTS,
    TransactionMixIn,
    defaults,
)
from rsc.types import Substitute
from rsc.utils import utils

from .utils import command_callback


def _create_mixin(**attrs):
    """Create a TransactionMixIn instance bypassing ABC restrictions."""
    # Temporarily clear abstract methods to allow instantiation
    saved = TransactionMixIn.__abstractmethods__
    TransactionMixIn.__abstractmethods__ = frozenset()
    try:
        m = object.__new__(TransactionMixIn)
    finally:
        TransactionMixIn.__abstractmethods__ = saved
    for k, v in attrs.items():
        setattr(m, k, v)
    return m


# Fixtures: mock_guild, mock_member, mock_executor, mock_player_out are provided by conftest.py


def _make_player(discord_id, name="TestPlayer"):
    p = MagicMock(spec=Player)
    p.discord_id = discord_id
    p.name = name
    return p


def _make_ptu(discord_id, name="TestPlayer", old_team=None, new_team=None, tier=None, franchise=None, status=None):
    ptu = MagicMock(spec=PlayerTransactionUpdates)
    ptu.player = MagicMock(spec=LeaguePlayer)
    ptu.player.player = _make_player(discord_id, name)
    ptu.player.tier = tier
    ptu.player.status = status
    ptu.player.team = MagicMock()
    ptu.player.team.franchise = franchise
    ptu.old_team = old_team
    ptu.new_team = new_team
    return ptu


def _make_transaction_response(
    type=None,
    player_updates=None,
    first_franchise=None,
    second_franchise=None,
    var_date=None,
    match_day=None,
    notes=None,
    id=1,
):
    resp = MagicMock(spec=TransactionResponse)
    resp.id = id
    resp.type = type
    resp.player_updates = player_updates
    resp.first_franchise = first_franchise
    resp.second_franchise = second_franchise
    resp.var_date = var_date
    resp.match_day = match_day
    resp.notes = notes
    return resp


def _make_franchise_identifier(name="TestFranchise", gm_discord_id=999, fid=1):
    f = MagicMock(spec=FranchiseIdentifier)
    f.id = fid
    f.name = name
    f.gm = MagicMock()
    f.gm.discord_id = gm_discord_id
    return f


def _make_league_player(discord_id, status=Status.ROSTERED):
    league_player = MagicMock(spec=LeaguePlayer)
    league_player.player = _make_player(discord_id)
    league_player.status = status
    league_player.team = MagicMock()
    league_player.team.franchise = _make_franchise_identifier("TestFranchise", 999)
    return league_player


def _make_member_remove_event(guild, user):
    event = MagicMock(spec=discord.RawMemberRemoveEvent)
    event.guild_id = guild.id
    event.user = user
    return event


def _make_futures_validation_response(franchise_name="Test Franchise", future_season=26, is_valid=False, violations=None):
    return FranchiseFuturesValidationResponse(
        franchise_name=franchise_name,
        future_season=future_season,
        is_valid=is_valid,
        violations=violations or ["Missing first-round pick"],
    )


# --- Regex Tests ---


class TestTradeRegexPatterns:
    """Test the regex patterns used for parsing trade text."""

    def test_gm_trade_regex_basic(self):
        match = GM_TRADE_REGEX.search("TestGM receives:")
        assert match is not None
        assert match.group("gm") == "TestGM"

    def test_gm_trade_regex_with_spaces(self):
        match = GM_TRADE_REGEX.search("Some GM Name receives:")
        assert match is not None
        assert match.group("gm") == "Some GM Name"

    def test_gm_trade_regex_no_match(self):
        match = GM_TRADE_REGEX.search("random text")
        assert match is None

    def test_player_trade_regex_simple(self):
        match = PLAYER_TRADE_REGEX.search("@SomePlayer")
        assert match is not None
        assert match.group("player") == "SomePlayer"

    def test_player_trade_regex_with_team(self):
        match = PLAYER_TRADE_REGEX.search("@SomePlayer to Team Alpha")
        assert match is not None
        assert match.group("player") == "SomePlayer"
        assert match.group("team") == "Team Alpha"

    def test_player_trade_regex_no_match(self):
        match = PLAYER_TRADE_REGEX.search("SomePlayer")
        assert match is None

    def test_pick_trade_regex_first_round(self):
        match = PICK_TRADE_REGEX.match("1st Round Elite (5)")
        assert match is not None
        assert match.group("round") == "1"
        assert match.group("tier") == "Elite"
        assert match.group("pick") == "5"

    def test_pick_trade_regex_second_round(self):
        match = PICK_TRADE_REGEX.match("2nd Round Premier (12)")
        assert match is not None
        assert match.group("round") == "2"
        assert match.group("tier") == "Premier"
        assert match.group("pick") == "12"

    def test_pick_trade_regex_third_round(self):
        match = PICK_TRADE_REGEX.match("3rd Round Challenger (1)")
        assert match is not None
        assert match.group("round") == "3"
        assert match.group("tier") == "Challenger"
        assert match.group("pick") == "1"

    def test_pick_trade_regex_with_gm(self):
        match = PICK_TRADE_REGEX.match("SomeGM's 1st Round Elite (3)")
        assert match is not None
        assert match.group("gm") == "SomeGM"
        assert match.group("round") == "1"
        assert match.group("tier") == "Elite"
        assert match.group("pick") == "3"

    def test_pick_trade_regex_no_match(self):
        match = PICK_TRADE_REGEX.match("random text here")
        assert match is None

    def test_future_trade_regex(self):
        match = FUTURE_TRADE_REGEX.match("SomeGM's S25 1st Round Elite")
        assert match is not None
        assert match.group("gm") == "SomeGM"
        assert match.group("season") == "25"
        assert match.group("round") == "1"
        assert match.group("tier") == "Elite"

    def test_future_trade_regex_no_match(self):
        match = FUTURE_TRADE_REGEX.match("1st Round Elite (5)")
        assert match is None


# --- league_player_from_transaction Tests ---


class TestLeaguePlayerFromTransaction:
    """Test the league_player_from_transaction helper method."""

    @pytest.fixture
    def mixin(self):
        """Create a minimal TransactionMixIn instance for testing methods."""
        m = _create_mixin()
        return m

    async def test_returns_matching_ptu(self, mixin, mock_member):
        ptu = _make_ptu(mock_member.id, "TestPlayer")
        response = _make_transaction_response(player_updates=[ptu])
        result = await mixin.league_player_from_transaction(response, mock_member)
        assert result is ptu

    async def test_returns_none_when_no_match(self, mixin, mock_member):
        ptu = _make_ptu(999999, "OtherPlayer")
        response = _make_transaction_response(player_updates=[ptu])
        result = await mixin.league_player_from_transaction(response, mock_member)
        assert result is None

    async def test_raises_on_no_player_updates(self, mixin, mock_member):
        response = _make_transaction_response(player_updates=None)
        with pytest.raises(ValueError, match="no Player Updates"):
            await mixin.league_player_from_transaction(response, mock_member)

    async def test_skips_none_entries(self, mixin, mock_member):
        ptu = _make_ptu(mock_member.id, "TestPlayer")
        response = _make_transaction_response(player_updates=[None, ptu])
        result = await mixin.league_player_from_transaction(response, mock_member)
        assert result is ptu

    async def test_multiple_updates_returns_correct_player(self, mixin, mock_member):
        ptu_other = _make_ptu(444444, "Other")
        ptu_target = _make_ptu(mock_member.id, "TestPlayer")
        response = _make_transaction_response(player_updates=[ptu_other, ptu_target])
        result = await mixin.league_player_from_transaction(response, mock_member)
        assert result is ptu_target


def _api_exception(status: int, detail: str = "boom") -> ApiException:
    exc = ApiException(status=status)
    exc.body = json.dumps({"detail": detail})
    return exc


class TestMemberRemoveListener:
    @pytest.fixture
    def mixin(self, mock_guild):
        mock_guild.me = MagicMock(spec=discord.Member)
        mock_guild.me.id = 444444444

        bot = MagicMock()
        bot.get_guild.return_value = mock_guild

        m = _create_mixin(bot=bot)
        # Populated by RSC.__init__ in production. The listener's readiness gate
        # reads both before touching the API.
        m._api_conf = {mock_guild.id: MagicMock()}
        m._league = {mock_guild.id: 1}
        m.players = AsyncMock()
        m.retire = AsyncMock()
        m._notifications_enabled = AsyncMock(return_value=True)
        m._gm_notifications_enabled = AsyncMock(return_value=True)
        m.timezone = AsyncMock(return_value=ZoneInfo("UTC"))
        m._trans_log_channel = AsyncMock(return_value=MagicMock(spec=discord.TextChannel))
        m.announce_to_transaction_committee = AsyncMock()
        m.announce_to_franchise_transactions = AsyncMock()
        m._try_post_embeds = AsyncMock()
        return m

    # Every non-playing status is a completed retirement. The API returns DR
    # (Dropped) as readily as FR (Former); demanding FR alone reported successful
    # retirements as failures and re-POSTed them.
    @pytest.mark.parametrize("retired_status", [Status.FORMER, Status.DROPPED, Status.BANNED])
    @patch("rsc.transactions.transactions.utils.get_audit_log_reason", new_callable=AsyncMock)
    async def test_verified_retire_sends_notifications(self, mock_audit_reason, retired_status, mixin, mock_guild, mock_member):
        mock_audit_reason.return_value = (None, "left")
        player_before_retire = _make_league_player(mock_member.id, status=Status.ROSTERED)
        player_update = _make_ptu(mock_member.id, status=retired_status)
        mixin.players.return_value = [player_before_retire]
        mixin.retire.return_value = _make_transaction_response(type=TransactionType.RETIRE, player_updates=[player_update])

        await mixin._transactions_on_member_remove(_make_member_remove_event(mock_guild, mock_member))

        mixin.retire.assert_awaited_once_with(
            mock_guild,
            player=mock_member,
            executor=mock_guild.me,
            notes="Player left the RSC discord server",
            override=True,
        )
        mock_audit_reason.assert_awaited_once_with(mock_guild, mock_member.id, discord.AuditLogAction.kick)
        mixin.announce_to_transaction_committee.assert_awaited_once()
        mixin.announce_to_franchise_transactions.assert_awaited_once()
        mixin._try_post_embeds.assert_not_awaited()

    @pytest.mark.parametrize("readback_status", [Status.FORMER, Status.DROPPED])
    @patch("rsc.transactions.transactions.utils.get_audit_log_reason", new_callable=AsyncMock)
    async def test_unverified_response_accepts_api_readback(self, mock_audit_reason, readback_status, mixin, mock_guild, mock_member):
        """A 200 whose payload does not verify must be re-read, not blindly re-POSTed."""
        mock_audit_reason.return_value = (None, None)
        bad_update = _make_ptu(mock_member.id, status=Status.FREE_AGENT)
        mixin.players.side_effect = [
            [_make_league_player(mock_member.id, status=Status.ROSTERED)],  # pre-retire lookup
            [_make_league_player(mock_member.id, status=readback_status)],  # read back after mismatch
        ]
        mixin.retire.return_value = _make_transaction_response(type=TransactionType.RETIRE, player_updates=[bad_update], id=1)

        await mixin._transactions_on_member_remove(_make_member_remove_event(mock_guild, mock_member))

        mixin.retire.assert_awaited_once()
        mixin.announce_to_transaction_committee.assert_awaited_once()

    @patch("rsc.transactions.transactions.asyncio.sleep", new_callable=AsyncMock)
    async def test_unverified_and_still_active_retries_to_the_cap(self, mock_sleep, mixin, mock_guild, mock_member):
        bad_update = _make_ptu(mock_member.id, status=Status.ROSTERED)
        mixin.players.return_value = [_make_league_player(mock_member.id, status=Status.ROSTERED)]
        mixin.retire.return_value = _make_transaction_response(type=TransactionType.RETIRE, player_updates=[bad_update], id=1)

        await mixin._transactions_on_member_remove(_make_member_remove_event(mock_guild, mock_member))

        assert mixin.retire.await_count == RETIRE_MAX_ATTEMPTS
        assert mock_sleep.await_count == RETIRE_MAX_ATTEMPTS - 1
        mixin.announce_to_transaction_committee.assert_not_awaited()
        mixin._try_post_embeds.assert_awaited_once()

    async def test_failed_retire_verification_skips_notifications(self, mixin, mock_guild, mock_member, caplog):
        player_before_retire = _make_league_player(mock_member.id, status=Status.ROSTERED)
        bad_update = _make_ptu(mock_member.id, status=Status.ROSTERED)
        mixin.players.return_value = [player_before_retire]
        mixin.retire.return_value = _make_transaction_response(type=TransactionType.RETIRE, player_updates=[bad_update], id=1)

        with (
            patch("rsc.transactions.transactions.asyncio.sleep", new_callable=AsyncMock),
            caplog.at_level("ERROR", logger="red.rsc.transactions"),
        ):
            await mixin._transactions_on_member_remove(_make_member_remove_event(mock_guild, mock_member))

        mixin._notifications_enabled.assert_not_awaited()
        mixin.announce_to_transaction_committee.assert_not_awaited()
        assert "unable to retire" in caplog.text

    @patch("rsc.transactions.transactions.utils.get_audit_log_reason", new_callable=AsyncMock)
    async def test_non_member_user_remove_still_reads_audit_log(self, mock_audit_reason, mixin, mock_guild):
        """`get_audit_log_reason` takes a bare ID, so an uncached user is not a reason to skip it."""
        mock_audit_reason.return_value = (None, None)
        user = MagicMock(spec=discord.User)
        user.id = 555555555
        user.name = "FormerUser"
        user.display_name = "FormerUser"
        user.mention = "<@555555555>"
        user.display_avatar = "https://example.com/avatar.png"

        player_before_retire = _make_league_player(user.id, status=Status.ROSTERED)
        player_update = _make_ptu(user.id, status=Status.FORMER)
        mixin.players.return_value = [player_before_retire]
        mixin.retire.return_value = _make_transaction_response(type=TransactionType.RETIRE, player_updates=[player_update])

        await mixin._transactions_on_member_remove(_make_member_remove_event(mock_guild, user))

        mock_audit_reason.assert_awaited_once_with(mock_guild, user.id, discord.AuditLogAction.kick)
        mixin.announce_to_transaction_committee.assert_awaited_once()
        mixin.announce_to_franchise_transactions.assert_awaited_once()

    # Failure paths that used to abort the retirement silently

    async def test_player_lookup_failure_is_not_treated_as_non_player(self, mixin, mock_guild, mock_member, caplog):
        mixin.players.side_effect = RscException(response=_api_exception(502))

        with caplog.at_level("ERROR", logger="red.rsc.transactions"):
            await mixin._transactions_on_member_remove(_make_member_remove_event(mock_guild, mock_member))

        mixin.retire.assert_not_awaited()
        mixin._try_post_embeds.assert_awaited_once()
        assert "pre-retire lookup failed" in caplog.text

    async def test_player_lookup_key_error_is_reported(self, mixin, mock_guild, mock_member, caplog):
        mixin.players.side_effect = KeyError(mock_guild.id)

        with caplog.at_level("ERROR", logger="red.rsc.transactions"):
            await mixin._transactions_on_member_remove(_make_member_remove_event(mock_guild, mock_member))

        mixin.retire.assert_not_awaited()
        mixin._try_post_embeds.assert_awaited_once()
        assert "pre-retire lookup failed" in caplog.text

    async def test_unprepared_guild_reports_instead_of_crashing(self, mixin, mock_guild, mock_member, caplog):
        """Listeners dispatch before on_ready finishes populating these caches."""
        mixin._league = {}

        with caplog.at_level("ERROR", logger="red.rsc.transactions"):
            await mixin._transactions_on_member_remove(_make_member_remove_event(mock_guild, mock_member))

        mixin.players.assert_not_awaited()
        mixin.retire.assert_not_awaited()
        mixin._try_post_embeds.assert_awaited_once()
        assert "guild is not prepared" in caplog.text

    @patch("rsc.transactions.transactions.utils.get_audit_log_reason", new_callable=AsyncMock)
    @patch("rsc.transactions.transactions.asyncio.sleep", new_callable=AsyncMock)
    async def test_retryable_api_error_retries_then_succeeds(self, mock_sleep, mock_audit_reason, mixin, mock_guild, mock_member):
        mock_audit_reason.return_value = (None, None)
        player_update = _make_ptu(mock_member.id, status=Status.FORMER)
        mixin.players.return_value = [_make_league_player(mock_member.id, status=Status.ROSTERED)]
        mixin.retire.side_effect = [
            RscException(response=_api_exception(502)),
            RscException(response=_api_exception(504)),
            _make_transaction_response(type=TransactionType.RETIRE, player_updates=[player_update]),
        ]

        await mixin._transactions_on_member_remove(_make_member_remove_event(mock_guild, mock_member))

        assert mixin.retire.await_count == 3
        assert mock_sleep.await_count == 2
        mixin.announce_to_transaction_committee.assert_awaited_once()
        mixin._try_post_embeds.assert_not_awaited()

    async def test_non_retryable_api_error_does_not_retry(self, mixin, mock_guild, mock_member, caplog):
        mixin.players.return_value = [_make_league_player(mock_member.id, status=Status.ROSTERED)]
        mixin.retire.side_effect = RscException(
            response=_api_exception(400, "Cannot admin override transaction for league you are not an admin in")
        )

        with caplog.at_level("ERROR", logger="red.rsc.transactions"):
            await mixin._transactions_on_member_remove(_make_member_remove_event(mock_guild, mock_member))

        mixin.retire.assert_awaited_once()
        mixin._try_post_embeds.assert_awaited_once()
        assert "will not be retried" in caplog.text

    @patch("rsc.transactions.transactions.utils.get_audit_log_reason", new_callable=AsyncMock)
    async def test_already_not_playing_is_a_success(self, mock_audit_reason, mixin, mock_guild, mock_member):
        """'not currently playing this season' means the desired end state already holds."""
        mock_audit_reason.return_value = (None, None)
        mixin.players.return_value = [_make_league_player(mock_member.id, status=Status.ROSTERED)]
        mixin.retire.side_effect = RscException(response=_api_exception(400, "TestPlayer is not currently playing this season."))

        await mixin._transactions_on_member_remove(_make_member_remove_event(mock_guild, mock_member))

        mixin.retire.assert_awaited_once()
        mixin._try_post_embeds.assert_not_awaited()

    async def test_listener_never_raises(self, mixin, mock_guild, mock_member, caplog):
        mixin.players.side_effect = RuntimeError("something completely unexpected")
        mixin._report_retire_failure = AsyncMock(side_effect=RuntimeError("and the report failed too"))

        with caplog.at_level("ERROR", logger="red.rsc.transactions"):
            await mixin._transactions_on_member_remove(_make_member_remove_event(mock_guild, mock_member))

        assert "leave handler crashed" in caplog.text

    # Notification gating

    @patch("rsc.transactions.transactions.utils.get_audit_log_reason", new_callable=AsyncMock)
    async def test_committee_notified_when_gm_notifications_disabled(self, mock_audit_reason, mixin, mock_guild, mock_member):
        """The two toggles gate different channels and must not imply each other."""
        mock_audit_reason.return_value = (None, None)
        mixin._gm_notifications_enabled.return_value = False
        mixin.players.return_value = [_make_league_player(mock_member.id, status=Status.ROSTERED)]
        mixin.retire.return_value = _make_transaction_response(
            type=TransactionType.RETIRE, player_updates=[_make_ptu(mock_member.id, status=Status.FORMER)]
        )

        await mixin._transactions_on_member_remove(_make_member_remove_event(mock_guild, mock_member))

        mixin.announce_to_transaction_committee.assert_awaited_once()
        mixin.announce_to_franchise_transactions.assert_not_awaited()

    @patch("rsc.transactions.transactions.utils.get_audit_log_reason", new_callable=AsyncMock)
    async def test_franchise_notified_without_a_log_channel(self, mock_audit_reason, mixin, mock_guild, mock_member):
        """The franchise channel does not depend on the transaction log channel."""
        mock_audit_reason.return_value = (None, None)
        mixin._notifications_enabled.return_value = False
        mixin._trans_log_channel.return_value = None
        mixin.players.return_value = [_make_league_player(mock_member.id, status=Status.ROSTERED)]
        mixin.retire.return_value = _make_transaction_response(
            type=TransactionType.RETIRE, player_updates=[_make_ptu(mock_member.id, status=Status.FORMER)]
        )

        await mixin._transactions_on_member_remove(_make_member_remove_event(mock_guild, mock_member))

        mixin.announce_to_transaction_committee.assert_not_awaited()
        mixin.announce_to_franchise_transactions.assert_awaited_once()

    @patch("rsc.transactions.transactions.utils.get_audit_log_reason", new_callable=AsyncMock)
    async def test_announcement_failure_does_not_raise(self, mock_audit_reason, mixin, mock_guild, mock_member):
        mock_audit_reason.return_value = (None, None)
        mixin.announce_to_transaction_committee.side_effect = discord.HTTPException(MagicMock(), "nope")
        mixin.players.return_value = [_make_league_player(mock_member.id, status=Status.ROSTERED)]
        mixin.retire.return_value = _make_transaction_response(
            type=TransactionType.RETIRE, player_updates=[_make_ptu(mock_member.id, status=Status.FORMER)]
        )

        await mixin._transactions_on_member_remove(_make_member_remove_event(mock_guild, mock_member))

        # The retire succeeded, so the franchise announcement still goes out.
        mixin.announce_to_franchise_transactions.assert_awaited_once()


# --- build_transaction_card Tests ---

IR_MOVE = "INACTIVE RESERVE · Elite"


def _team(name="Alpha", tier="Elite"):
    team = MagicMock()
    team.name = name
    team.tier = tier
    return team


class TestBuildTransactionCard:
    """Test the build_transaction_card method."""

    @pytest.fixture
    def mixin(self, mock_guild):
        m = _create_mixin()
        m.league_player_from_transaction = AsyncMock()
        m.franchise_logo = AsyncMock(return_value="https://cdn.example/hex.png")
        return m

    @pytest.fixture(autouse=True)
    def tier_colour(self):
        with patch("rsc.transactions.transactions.utils.tier_color_by_name", new_callable=AsyncMock) as mock:
            mock.return_value = discord.Colour.orange()
            yield mock

    async def _card(self, mixin, guild, member, action, *, old_team=None, new_team=None, first=None, second=None, player_out=None):
        ptu = _make_ptu(member.id, "Test_Player", old_team=old_team, new_team=new_team)
        mixin.league_player_from_transaction.return_value = ptu
        response = _make_transaction_response(type=action, player_updates=[ptu], first_franchise=first, second_franchise=second)
        return await mixin.build_transaction_card(guild, response, member, player_out=player_out)

    async def test_raises_on_missing_type(self, mixin, mock_guild, mock_member):
        response = _make_transaction_response(type=None)
        with pytest.raises(MalformedTransactionResponse, match="type not returned"):
            await mixin.build_transaction_card(mock_guild, response, mock_member)

    @pytest.mark.parametrize(
        ("action", "move", "summary", "banner"),
        [
            (TransactionType.CUT, "RELEASED · Elite", "leaves **Alpha** · Hex", "Released.png"),
            (TransactionType.IR_CUT, "RELEASED · Elite", "leaves **Alpha** · Hex", "Released.png"),
            (TransactionType.INACTIVE_RESERVE, IR_MOVE, "moves to Inactive Reserve on **Alpha** · Hex", "InactiveReserve.png"),
            (TransactionType.IR_RETURN, IR_MOVE, "returns from Inactive Reserve to **Alpha** · Hex", "InactiveReserve.png"),
        ],
    )
    async def test_old_team_types(self, mixin, mock_guild, mock_member, tier_colour, action, move, summary, banner):
        card = await self._card(mixin, mock_guild, mock_member, action, old_team=_team(), first=_make_franchise_identifier("Hex", 999))
        assert (card.move, card.name, card.summary) == (move, r"Test\_Player", summary)
        assert card.banner.name == banner
        assert (card.player_id, card.gm_id) == (mock_member.id, 999)
        assert card.colour == discord.Colour.orange()
        tier_colour.assert_awaited_once_with(mock_guild, "Elite")
        if action in (TransactionType.CUT, TransactionType.IR_CUT):
            # Releases show the free agent badge for the tier, like the old embed's author icon
            assert isinstance(card.logo, Path) and card.logo.name == "EliteFA_64x64.png"
        else:
            assert card.logo == "https://cdn.example/hex.png"

    @pytest.mark.parametrize(
        ("action", "move", "summary", "banner"),
        [
            (TransactionType.PICKUP, "SIGNED · Elite", "joins **Alpha** · Hex", "Signed.png"),
            (TransactionType.RESIGN, "RE-SIGNED · Elite", "re-signs with **Alpha** · Hex", "Resigned.png"),
            (TransactionType.TEMP_FA, "TEMPORARY CONTRACT · Elite", "joins **Alpha** · Hex", "Subbed.png"),
            (TransactionType.SUBSTITUTION, "TEMPORARY CONTRACT · Elite", "joins **Alpha** · Hex", "Subbed.png"),
        ],
    )
    async def test_new_team_types(self, mixin, mock_guild, mock_member, action, move, summary, banner):
        card = await self._card(mixin, mock_guild, mock_member, action, new_team=_team(), second=_make_franchise_identifier("Hex", 999))
        assert (card.move, card.summary) == (move, summary)
        assert card.banner.name == banner
        # The GM is named, and so pinged, on every type that has one
        assert card.gm_id == 999
        assert card.logo == "https://cdn.example/hex.png"

    async def test_retire_without_franchise(self, mixin, mock_guild, mock_member):
        card = await self._card(mixin, mock_guild, mock_member, TransactionType.RETIRE)
        # No tier, so the label is just the move
        assert (card.move, card.summary, card.gm_id) == ("RETIRED", "retires from the league", None)
        assert card.colour == discord.Colour.blue()
        assert card.logo == mock_guild.icon.url

    async def test_retire_with_franchise(self, mixin, mock_guild, mock_member):
        card = await self._card(mixin, mock_guild, mock_member, TransactionType.RETIRE, first=_make_franchise_identifier("Hex", 999))
        assert (card.summary, card.gm_id) == ("retires from the league · Hex", 999)

    async def test_player_out(self, mixin, mock_guild, mock_member, mock_player_out):
        card = await self._card(
            mixin,
            mock_guild,
            mock_member,
            TransactionType.SUBSTITUTION,
            new_team=_team(),
            second=_make_franchise_identifier(),
            player_out=mock_player_out,
        )
        assert card.player_out_id == mock_player_out.id

    async def test_missing_team_name(self, mixin, mock_guild, mock_member):
        team = _team(name=None)
        card = await self._card(mixin, mock_guild, mock_member, TransactionType.PICKUP, new_team=team, second=_make_franchise_identifier())
        assert card.summary.startswith("joins **Unknown team**")

    async def test_cut_malformed_no_old_team(self, mixin, mock_guild, mock_member):
        with pytest.raises(MalformedTransactionResponse):
            await self._card(mixin, mock_guild, mock_member, TransactionType.CUT)

    async def test_pickup_malformed_no_new_team(self, mixin, mock_guild, mock_member):
        with pytest.raises(MalformedTransactionResponse):
            await self._card(mixin, mock_guild, mock_member, TransactionType.PICKUP)

    async def test_raises_when_player_missing_from_response(self, mixin, mock_guild, mock_member):
        mixin.league_player_from_transaction.return_value = None
        response = _make_transaction_response(type=TransactionType.CUT, player_updates=[])
        with pytest.raises(MalformedTransactionResponse):
            await mixin.build_transaction_card(mock_guild, response, mock_member)


class TestTransactionBanner:
    @pytest.mark.parametrize(
        "action",
        [
            TransactionType.CUT,
            TransactionType.IR_CUT,
            TransactionType.PICKUP,
            TransactionType.RESIGN,
            TransactionType.TEMP_FA,
            TransactionType.SUBSTITUTION,
            TransactionType.RETIRE,
            TransactionType.INACTIVE_RESERVE,
            TransactionType.IR_RETURN,
        ],
    )
    def test_every_card_type_has_a_banner_on_disk(self, action):
        """The lookup raises NotImplementedError on an unhandled type, which no caller
        catches, so every type the card builder handles needs a real file."""
        assert utils.transaction_banner(action).is_file()


# --- send_cut_msg Tests ---


class TestSendCutMsg:
    @pytest.fixture
    def mixin(self):
        m = _create_mixin()
        m._trans_dms_enabled = AsyncMock()
        m._get_cut_message = AsyncMock()
        return m

    async def test_returns_none_when_dms_disabled(self, mixin, mock_guild, mock_member):
        mixin._trans_dms_enabled.return_value = False
        result = await mixin.send_cut_msg(mock_guild, mock_member)
        assert result is None

    async def test_returns_none_when_no_cut_message(self, mixin, mock_guild, mock_member):
        mixin._trans_dms_enabled.return_value = True
        mixin._get_cut_message.return_value = None
        result = await mixin.send_cut_msg(mock_guild, mock_member)
        assert result is None

    async def test_sends_dm_when_enabled(self, mixin, mock_guild, mock_member):
        mixin._trans_dms_enabled.return_value = True
        mixin._get_cut_message.return_value = "You have been cut."
        mock_msg = MagicMock(spec=discord.Message)
        mock_member.send = AsyncMock(return_value=mock_msg)

        result = await mixin.send_cut_msg(mock_guild, mock_member)
        assert result is mock_msg
        mock_member.send.assert_called_once()


# --- get_sub Tests ---


class TestGetSub:
    @pytest.fixture
    def mixin(self):
        m = _create_mixin()
        m._get_substitutes = AsyncMock()
        return m

    async def test_returns_matching_sub(self, mixin, mock_member):
        sub = Substitute(
            date="2025-01-01",
            franchise="TestFranchise",
            gm=999,
            player_in=mock_member.id,
            player_out=333,
            team="Team Alpha",
            tier="Elite",
        )
        mixin._get_substitutes.return_value = [sub]
        result = await mixin.get_sub(mock_member)
        assert result == sub

    async def test_returns_none_when_no_match(self, mixin, mock_member):
        sub = Substitute(
            date="2025-01-01",
            franchise="TestFranchise",
            gm=999,
            player_in=444444,
            player_out=333,
            team="Team Alpha",
            tier="Elite",
        )
        mixin._get_substitutes.return_value = [sub]
        result = await mixin.get_sub(mock_member)
        assert result is None

    async def test_returns_none_when_empty(self, mixin, mock_member):
        mixin._get_substitutes.return_value = []
        result = await mixin.get_sub(mock_member)
        assert result is None


# --- announce_transaction Tests ---


class TestAnnounceTransaction:
    @pytest.fixture
    def mixin(self):
        m = _create_mixin()
        m._trans_channel = AsyncMock()
        return m

    @pytest.fixture
    def card(self):
        return TransactionCard(
            move="SIGNED · Elite",
            name="X",
            summary="joins **Alpha** · Hex",
            player_id=111,
            colour=discord.Colour.orange(),
            banner=utils.transaction_banner(TransactionType.PICKUP),
            created_at=discord.utils.utcnow(),
            gm_id=222,
        )

    async def test_returns_none_when_no_channel(self, mixin, mock_guild, card):
        mixin._trans_channel.return_value = None
        assert await mixin.announce_transaction(mock_guild, card) is None

    async def test_sends_only_the_card_and_lets_user_pings_through(self, mixin, mock_guild, card):
        mock_msg = MagicMock(spec=discord.Message)
        mock_channel = MagicMock(spec=discord.TextChannel)
        mock_channel.send = AsyncMock(return_value=mock_msg)
        mixin._trans_channel.return_value = mock_channel

        assert await mixin.announce_transaction(mock_guild, card) is mock_msg

        call = mock_channel.send.await_args
        assert call is not None
        kwargs = call.kwargs
        assert isinstance(kwargs["view"], discord.ui.LayoutView)
        assert [f.filename for f in kwargs["files"]] == ["Signed.png"]
        assert "content" not in kwargs and "embed" not in kwargs
        mentions = kwargs["allowed_mentions"]
        assert (mentions.users, mentions.roles, mentions.everyone) == (True, False, False)


# --- announce_to_transaction_committee Tests ---


class TestAnnounceToTransactionCommittee:
    @pytest.fixture
    def mixin(self):
        m = _create_mixin()
        m._trans_log_channel = AsyncMock()
        m._trans_role = AsyncMock()
        return m

    async def test_returns_none_when_no_channel(self, mixin, mock_guild):
        mixin._trans_log_channel.return_value = None
        result = await mixin.announce_to_transaction_committee(guild=mock_guild, embed=discord.Embed())
        assert result is None

    async def test_returns_none_when_no_role(self, mixin, mock_guild):
        mock_channel = MagicMock(spec=discord.TextChannel)
        mock_channel.send = AsyncMock()
        mixin._trans_log_channel.return_value = mock_channel
        mixin._trans_role.return_value = None
        result = await mixin.announce_to_transaction_committee(guild=mock_guild, embed=discord.Embed())
        assert result is None

    async def test_sends_message_successfully(self, mixin, mock_guild):
        mock_channel = MagicMock(spec=discord.TextChannel)
        mock_msg = MagicMock(spec=discord.Message)
        mock_channel.send = AsyncMock(return_value=mock_msg)
        mixin._trans_log_channel.return_value = mock_channel

        mock_role = MagicMock(spec=discord.Role)
        mock_role.mention = "@TransCommittee"
        mixin._trans_role.return_value = mock_role

        result = await mixin.announce_to_transaction_committee(guild=mock_guild, embed=discord.Embed())
        assert result is mock_msg


# --- announce_to_franchise_transactions Tests ---


class TestAnnounceToFranchiseTransactions:
    @pytest.fixture
    def mixin(self):
        m = _create_mixin()
        m._trans_log_channel = AsyncMock(return_value=None)
        return m

    async def test_returns_none_when_no_channel(self, mixin, mock_guild):
        result = await mixin.announce_to_franchise_transactions(mock_guild, franchise="Test Franchise", gm=999, embed=discord.Embed())
        assert result is None

    async def test_sends_to_matching_channel(self, mixin, mock_guild):
        mock_channel = MagicMock(spec=discord.TextChannel)
        mock_channel.name = "test-franchise-transactions"
        mock_msg = MagicMock(spec=discord.Message)
        mock_channel.send = AsyncMock(return_value=mock_msg)
        mock_guild.text_channels = [mock_channel]

        result = await mixin.announce_to_franchise_transactions(mock_guild, franchise="Test Franchise", gm=999, embed=discord.Embed())
        assert result is mock_msg

    async def test_formats_gm_mention_from_member(self, mixin, mock_guild, mock_member):
        mock_channel = MagicMock(spec=discord.TextChannel)
        mock_channel.name = "test-franchise-transactions"
        mock_msg = MagicMock(spec=discord.Message)
        mock_channel.send = AsyncMock(return_value=mock_msg)
        mock_guild.text_channels = [mock_channel]

        result = await mixin.announce_to_franchise_transactions(
            mock_guild, franchise="Test Franchise", gm=mock_member, embed=discord.Embed()
        )
        assert result is mock_msg
        call_kwargs = mock_channel.send.call_args
        assert call_kwargs.kwargs["content"] == mock_member.mention


# --- get_franchise_transaction_channel_name Tests ---


class TestGetFranchiseTransactionChannelName:
    @pytest.fixture
    def mixin(self):
        return _create_mixin()

    async def test_basic_name(self, mixin):
        result = await mixin.get_franchise_transaction_channel_name("Test Franchise")
        assert result == "test-franchise-transactions"

    async def test_name_with_special_chars(self, mixin):
        result = await mixin.get_franchise_transaction_channel_name("King's Landing")
        assert result == "kings-landing-transactions"

    async def test_name_with_multiple_spaces(self, mixin):
        result = await mixin.get_franchise_transaction_channel_name("Some  Franchise")
        # Double space results in double hyphens, but regex strips non-alphanumeric
        assert "transactions" in result


# --- parse_trade_text Tests ---


class TestParseTradeText:
    @pytest.fixture
    def mixin(self):
        m = _create_mixin()
        return m

    async def test_raises_on_empty_data(self, mixin, mock_guild):
        with pytest.raises(TradeParserException):
            await mixin.parse_trade_text(guild=mock_guild, data="")


# --- build_trade_embed Tests ---


class TestBuildTradeEmbed:
    @pytest.fixture
    def mixin(self, mock_guild):
        m = _create_mixin()
        return m

    async def test_empty_trade_list(self, mixin, mock_guild):
        gms, embed = await mixin.build_trade_embed(mock_guild, [])
        assert isinstance(gms, list)
        assert isinstance(embed, discord.Embed)

    async def test_player_trade_embed(self, mixin, mock_guild):
        src = TradeFranchise(id=1, name="Source FC", gm=111)
        dest = TradeFranchise(id=2, name="Dest FC", gm=222)
        value = TradeItem(player=TradePlayer(id=333, team="Team A"), pick=None)
        trade = TradeObject(source=src, destination=dest, value=value)

        mock_guild.get_member = MagicMock(return_value=None)
        gms, _embed = await mixin.build_trade_embed(mock_guild, [trade])
        assert 222 in gms
        assert 333 in gms

    async def test_pick_trade_embed(self, mixin, mock_guild):
        src = TradeFranchise(id=1, name="Source FC", gm=111)
        dest = TradeFranchise(id=2, name="Dest FC", gm=222)
        value = TradeItem(player=None, pick=DraftPickTrade(tier="Elite", round=1, number=5, future=False))
        trade = TradeObject(source=src, destination=dest, value=value)

        mock_guild.get_member = MagicMock(return_value=None)
        gms, _embed = await mixin.build_trade_embed(mock_guild, [trade])
        assert 222 in gms

    async def test_future_pick_trade_embed(self, mixin, mock_guild):
        src = TradeFranchise(id=1, name="Source FC", gm=111)
        dest = TradeFranchise(id=2, name="Dest FC", gm=222)
        value = TradeItem(player=None, pick=DraftPickTrade(tier="Elite", round=2, number=0, future=True))
        trade = TradeObject(source=src, destination=dest, value=value)

        mock_guild.get_member = MagicMock(return_value=None)
        gms, _embed = await mixin.build_trade_embed(mock_guild, [trade])
        assert 222 in gms


# --- API Method Tests (mocked) ---


class TestSignApi:
    @pytest.fixture
    def mixin(self, mock_guild):
        m = _create_mixin()
        m._api_conf = {mock_guild.id: MagicMock()}
        m._league = {mock_guild.id: 1}
        return m

    @patch("rsc.transactions.transactions.TransactionsApi")
    @patch("rsc.abc.ApiClient")
    async def test_sign_success(self, mock_client_cls, mock_api_cls, mixin, mock_guild, mock_member, mock_executor):
        mock_api = AsyncMock()
        expected = _make_transaction_response(type=TransactionType.PICKUP)
        mock_api.transactions_sign_create.return_value = expected
        mock_api_cls.return_value = mock_api

        mock_ctx = AsyncMock()
        mock_ctx.__aenter__ = AsyncMock(return_value=mock_api)
        mock_ctx.__aexit__ = AsyncMock(return_value=False)
        mock_client_cls.return_value = mock_ctx

        result = await mixin.sign(mock_guild, mock_member, "Team Alpha", mock_executor)
        assert result is expected

    @patch("rsc.transactions.transactions.TransactionsApi")
    @patch("rsc.abc.ApiClient")
    async def test_sign_api_exception(self, mock_client_cls, mock_api_cls, mixin, mock_guild, mock_member, mock_executor):
        mock_api = AsyncMock()
        exc = ApiException(status=400, reason="Bad Request")
        exc.body = json.dumps({"detail": "Unable to find team name TestTeam"})
        mock_api.transactions_sign_create.side_effect = exc
        mock_api_cls.return_value = mock_api

        mock_ctx = AsyncMock()
        mock_ctx.__aenter__ = AsyncMock(return_value=mock_api)
        mock_ctx.__aexit__ = AsyncMock(return_value=False)
        mock_client_cls.return_value = mock_ctx

        with pytest.raises(RscException):
            await mixin.sign(mock_guild, mock_member, "TestTeam", mock_executor)


class TestCutApi:
    @pytest.fixture
    def mixin(self, mock_guild):
        m = _create_mixin()
        m._api_conf = {mock_guild.id: MagicMock()}
        m._league = {mock_guild.id: 1}
        return m

    @patch("rsc.transactions.transactions.TransactionsApi")
    @patch("rsc.abc.ApiClient")
    async def test_cut_success(self, mock_client_cls, mock_api_cls, mixin, mock_guild, mock_member, mock_executor):
        mock_api = AsyncMock()
        expected = _make_transaction_response(type=TransactionType.CUT)
        mock_api.transactions_cut_create.return_value = expected
        mock_api_cls.return_value = mock_api

        mock_ctx = AsyncMock()
        mock_ctx.__aenter__ = AsyncMock(return_value=mock_api)
        mock_ctx.__aexit__ = AsyncMock(return_value=False)
        mock_client_cls.return_value = mock_ctx

        result = await mixin.cut(mock_guild, mock_member, mock_executor)
        assert result is expected

    @patch("rsc.transactions.transactions.TransactionsApi")
    @patch("rsc.abc.ApiClient")
    async def test_cut_api_exception_translated(self, mock_client_cls, mock_api_cls, mixin, mock_guild, mock_member, mock_executor):
        mock_api = AsyncMock()
        exc = ApiException(status=400, reason="Bad Request")
        exc.body = json.dumps({"detail": "Cannot cut a player past the transactions end date for S25"})
        mock_api.transactions_cut_create.side_effect = exc
        mock_api_cls.return_value = mock_api

        mock_ctx = AsyncMock()
        mock_ctx.__aenter__ = AsyncMock(return_value=mock_api)
        mock_ctx.__aexit__ = AsyncMock(return_value=False)
        mock_client_cls.return_value = mock_ctx

        with pytest.raises(PastTransactionsEndDate):
            await mixin.cut(mock_guild, mock_member, mock_executor)


class TestResignApi:
    @pytest.fixture
    def mixin(self, mock_guild):
        m = _create_mixin()
        m._api_conf = {mock_guild.id: MagicMock()}
        m._league = {mock_guild.id: 1}
        return m

    @patch("rsc.transactions.transactions.TransactionsApi")
    @patch("rsc.abc.ApiClient")
    async def test_resign_success(self, mock_client_cls, mock_api_cls, mixin, mock_guild, mock_member, mock_executor):
        mock_api = AsyncMock()
        expected = _make_transaction_response(type=TransactionType.RESIGN)
        mock_api.transactions_resign_create.return_value = expected
        mock_api_cls.return_value = mock_api

        mock_ctx = AsyncMock()
        mock_ctx.__aenter__ = AsyncMock(return_value=mock_api)
        mock_ctx.__aexit__ = AsyncMock(return_value=False)
        mock_client_cls.return_value = mock_ctx

        result = await mixin.resign(mock_guild, mock_member, "Team Alpha", mock_executor)
        assert result is expected


class TestSubstitutionApi:
    @pytest.fixture
    def mixin(self, mock_guild):
        m = _create_mixin()
        m._api_conf = {mock_guild.id: MagicMock()}
        m._league = {mock_guild.id: 1}
        return m

    @patch("rsc.transactions.transactions.TransactionsApi")
    @patch("rsc.abc.ApiClient")
    async def test_substitution_success(
        self, mock_client_cls, mock_api_cls, mixin, mock_guild, mock_member, mock_player_out, mock_executor
    ):
        mock_api = AsyncMock()
        expected = _make_transaction_response(type=TransactionType.SUBSTITUTION)
        mock_api.transactions_substitution_create.return_value = expected
        mock_api_cls.return_value = mock_api

        mock_ctx = AsyncMock()
        mock_ctx.__aenter__ = AsyncMock(return_value=mock_api)
        mock_ctx.__aexit__ = AsyncMock(return_value=False)
        mock_client_cls.return_value = mock_ctx

        result = await mixin.substitution(mock_guild, mock_member, mock_player_out, mock_executor)
        assert result is expected

    @patch("rsc.transactions.transactions.TransactionsApi")
    @patch("rsc.abc.ApiClient")
    async def test_substitution_api_exception(
        self, mock_client_cls, mock_api_cls, mixin, mock_guild, mock_member, mock_player_out, mock_executor
    ):
        mock_api = AsyncMock()
        exc = ApiException(status=400, reason="Bad Request")
        exc.body = json.dumps({"detail": "Some error"})
        mock_api.transactions_substitution_create.side_effect = exc
        mock_api_cls.return_value = mock_api

        mock_ctx = AsyncMock()
        mock_ctx.__aenter__ = AsyncMock(return_value=mock_api)
        mock_ctx.__aexit__ = AsyncMock(return_value=False)
        mock_client_cls.return_value = mock_ctx

        with pytest.raises(RscException):
            await mixin.substitution(mock_guild, mock_member, mock_player_out, mock_executor)


class TestRetireApi:
    @pytest.fixture
    def mixin(self, mock_guild):
        m = _create_mixin()
        m._api_conf = {mock_guild.id: MagicMock()}
        m._league = {mock_guild.id: 1}
        return m

    @patch("rsc.transactions.transactions.TransactionsApi")
    @patch("rsc.abc.ApiClient")
    async def test_retire_success(self, mock_client_cls, mock_api_cls, mixin, mock_guild, mock_member, mock_executor):
        mock_api = AsyncMock()
        expected = _make_transaction_response(type=TransactionType.RETIRE)
        mock_api.transactions_retire_create.return_value = expected
        mock_api_cls.return_value = mock_api

        mock_ctx = AsyncMock()
        mock_ctx.__aenter__ = AsyncMock(return_value=mock_api)
        mock_ctx.__aexit__ = AsyncMock(return_value=False)
        mock_client_cls.return_value = mock_ctx

        result = await mixin.retire(mock_guild, mock_member, mock_executor)
        assert result is expected


class TestInactiveReserveApi:
    @pytest.fixture
    def mixin(self, mock_guild):
        m = _create_mixin()
        m._api_conf = {mock_guild.id: MagicMock()}
        m._league = {mock_guild.id: 1}
        return m

    @patch("rsc.transactions.transactions.TransactionsApi")
    @patch("rsc.abc.ApiClient")
    async def test_ir_move_success(self, mock_client_cls, mock_api_cls, mixin, mock_guild, mock_member, mock_executor):
        mock_api = AsyncMock()
        expected = _make_transaction_response(type=TransactionType.INACTIVE_RESERVE)
        mock_api.transactions_inactive_reserve_create.return_value = expected
        mock_api_cls.return_value = mock_api

        mock_ctx = AsyncMock()
        mock_ctx.__aenter__ = AsyncMock(return_value=mock_api)
        mock_ctx.__aexit__ = AsyncMock(return_value=False)
        mock_client_cls.return_value = mock_ctx

        result = await mixin.inactive_reserve(mock_guild, mock_member, mock_executor, redshirt=False, remove=False)
        assert result is expected

    @patch("rsc.transactions.transactions.TransactionsApi")
    @patch("rsc.abc.ApiClient")
    async def test_ir_return_success(self, mock_client_cls, mock_api_cls, mixin, mock_guild, mock_member, mock_executor):
        mock_api = AsyncMock()
        expected = _make_transaction_response(type=TransactionType.IR_RETURN)
        mock_api.transactions_inactive_reserve_create.return_value = expected
        mock_api_cls.return_value = mock_api

        mock_ctx = AsyncMock()
        mock_ctx.__aenter__ = AsyncMock(return_value=mock_api)
        mock_ctx.__aexit__ = AsyncMock(return_value=False)
        mock_client_cls.return_value = mock_ctx

        result = await mixin.inactive_reserve(mock_guild, mock_member, mock_executor, redshirt=False, remove=True)
        assert result is expected

    @patch("rsc.transactions.transactions.TransactionsApi")
    @patch("rsc.abc.ApiClient")
    async def test_ir_redshirt_success(self, mock_client_cls, mock_api_cls, mixin, mock_guild, mock_member, mock_executor):
        mock_api = AsyncMock()
        expected = _make_transaction_response(type=TransactionType.INACTIVE_RESERVE)
        mock_api.transactions_inactive_reserve_create.return_value = expected
        mock_api_cls.return_value = mock_api

        mock_ctx = AsyncMock()
        mock_ctx.__aenter__ = AsyncMock(return_value=mock_api)
        mock_ctx.__aexit__ = AsyncMock(return_value=False)
        mock_client_cls.return_value = mock_ctx

        result = await mixin.inactive_reserve(mock_guild, mock_member, mock_executor, redshirt=True, remove=False)
        assert result is expected


class TestExpireSubApi:
    @pytest.fixture
    def mixin(self, mock_guild):
        m = _create_mixin()
        m._api_conf = {mock_guild.id: MagicMock()}
        m._league = {mock_guild.id: 1}
        return m

    @patch("rsc.transactions.transactions.TransactionsApi")
    @patch("rsc.abc.ApiClient")
    async def test_expire_sub_success(self, mock_client_cls, mock_api_cls, mixin, mock_guild, mock_member, mock_executor):
        mock_api = AsyncMock()
        expected = MagicMock(spec=LeaguePlayer)
        mock_api.transactions_expire_create.return_value = expected
        mock_api_cls.return_value = mock_api

        mock_ctx = AsyncMock()
        mock_ctx.__aenter__ = AsyncMock(return_value=mock_api)
        mock_ctx.__aexit__ = AsyncMock(return_value=False)
        mock_client_cls.return_value = mock_ctx

        result = await mixin.expire_sub(mock_guild, mock_member, mock_executor)
        assert result is expected


class TestDraftApi:
    @pytest.fixture
    def mixin(self, mock_guild):
        m = _create_mixin()
        m._api_conf = {mock_guild.id: MagicMock()}
        m._league = {mock_guild.id: 1}
        return m

    @patch("rsc.transactions.transactions.TransactionsApi")
    @patch("rsc.abc.ApiClient")
    async def test_draft_success(self, mock_client_cls, mock_api_cls, mixin, mock_guild, mock_member, mock_executor):
        mock_api = AsyncMock()
        expected = _make_transaction_response(type=TransactionType.DRAFT)
        mock_api.transactions_draft_create.return_value = expected
        mock_api_cls.return_value = mock_api

        mock_ctx = AsyncMock()
        mock_ctx.__aenter__ = AsyncMock(return_value=mock_api)
        mock_ctx.__aexit__ = AsyncMock(return_value=False)
        mock_client_cls.return_value = mock_ctx

        result = await mixin.draft(mock_guild, mock_member, mock_executor, "Team Alpha", round=1, pick=5)
        assert result is expected


class TestTradeApi:
    @pytest.fixture
    def mixin(self, mock_guild):
        m = _create_mixin()
        m._api_conf = {mock_guild.id: MagicMock()}
        m._league = {mock_guild.id: 1}
        return m

    @patch("rsc.transactions.transactions.TransactionsApi")
    @patch("rsc.abc.ApiClient")
    async def test_trade_success(self, mock_client_cls, mock_api_cls, mixin, mock_guild, mock_executor):
        mock_api = AsyncMock()
        expected = _make_transaction_response(type=TransactionType.TRADE)
        mock_api.transactions_trade_create.return_value = expected
        mock_api_cls.return_value = mock_api

        mock_ctx = AsyncMock()
        mock_ctx.__aenter__ = AsyncMock(return_value=mock_api)
        mock_ctx.__aexit__ = AsyncMock(return_value=False)
        mock_client_cls.return_value = mock_ctx

        result = await mixin.trade(mock_guild, trades=[], executor=mock_executor, notes="Test trade")
        assert result is expected


class TestValidateFranchiseFuturesApi:
    @pytest.fixture
    def mixin(self, mock_guild):
        m = _create_mixin()
        m._api_conf = {mock_guild.id: MagicMock()}
        m._league = {mock_guild.id: 1}
        return m

    @patch("rsc.transactions.transactions.TransactionsApi")
    @patch("rsc.abc.ApiClient")
    async def test_validate_futures_success(self, mock_client_cls, mock_api_cls, mixin, mock_guild):
        mock_api = AsyncMock()
        expected = _make_futures_validation_response(is_valid=False)
        mock_api.transactions_trade_validate_futures_create.return_value = expected
        mock_api_cls.return_value = mock_api

        mock_ctx = AsyncMock()
        mock_ctx.__aenter__ = AsyncMock(return_value=mock_api)
        mock_ctx.__aexit__ = AsyncMock(return_value=False)
        mock_client_cls.return_value = mock_ctx

        result = await mixin.validate_franchise_futures(mock_guild, "Test Franchise")

        assert result is expected
        schema = mock_api.transactions_trade_validate_futures_create.call_args.args[0]
        assert isinstance(schema, FranchiseFuturesValidation)
        assert schema.league == 1
        assert schema.franchise_name == "Test Franchise"

    @patch("rsc.transactions.transactions.TransactionsApi")
    @patch("rsc.abc.ApiClient")
    async def test_validate_futures_api_exception(self, mock_client_cls, mock_api_cls, mixin, mock_guild):
        mock_api = AsyncMock()
        exc = ApiException(status=400, reason="Bad Request")
        exc.body = json.dumps({"detail": "Validation failed"})
        mock_api.transactions_trade_validate_futures_create.side_effect = exc
        mock_api_cls.return_value = mock_api

        mock_ctx = AsyncMock()
        mock_ctx.__aenter__ = AsyncMock(return_value=mock_api)
        mock_ctx.__aexit__ = AsyncMock(return_value=False)
        mock_client_cls.return_value = mock_ctx

        with pytest.raises(RscException):
            await mixin.validate_franchise_futures(mock_guild, "Test Franchise")


class TestValidateFuturesCommands:
    @pytest.fixture
    def mixin(self, mock_guild):
        m = _create_mixin()
        m._api_conf = {mock_guild.id: MagicMock()}
        m._league = {mock_guild.id: 1}
        m.validate_franchise_futures = AsyncMock()
        m.franchises = AsyncMock()
        m.announce_to_franchise_transactions = AsyncMock()
        return m

    @pytest.fixture
    def interaction(self, mock_guild):
        interaction = MagicMock(spec=discord.Interaction)
        interaction.guild = mock_guild
        interaction.response = MagicMock()
        interaction.response.defer = AsyncMock()
        interaction.followup = MagicMock()
        interaction.followup.send = AsyncMock()
        return interaction

    async def test_validatefutures_command_sends_ephemeral_embed(self, mixin, interaction, mock_guild):
        response = _make_futures_validation_response(is_valid=True, violations=[])
        mixin.validate_franchise_futures.return_value = response

        await command_callback(TransactionMixIn._transactions_validate_futures_cmd)(mixin, interaction, "Test Franchise")

        interaction.response.defer.assert_awaited_once_with(ephemeral=True)
        mixin.validate_franchise_futures.assert_awaited_once_with(guild=mock_guild, franchise_name="Test Franchise")
        kwargs = interaction.followup.send.await_args.kwargs
        assert kwargs["ephemeral"] is True
        assert isinstance(kwargs["embed"], discord.Embed)
        assert kwargs["embed"].title == "Test Franchise Futures Validation"

    async def test_validatefuturesall_command_pings_invalid_franchises(self, mixin, interaction, mock_guild):
        franchise = MagicMock()
        franchise.name = "Test Franchise"
        franchise.gm = MagicMock()
        franchise.gm.discord_id = 999
        mixin.franchises.return_value = [franchise]
        mixin.validate_franchise_futures.return_value = _make_futures_validation_response(is_valid=False)
        mixin.announce_to_franchise_transactions.return_value = MagicMock(spec=discord.Message)

        await command_callback(TransactionMixIn._transactions_validate_futures_all_cmd)(mixin, interaction, ping=True)

        interaction.response.defer.assert_awaited_once_with(ephemeral=True)
        mixin.announce_to_franchise_transactions.assert_awaited_once()
        announce_kwargs = mixin.announce_to_franchise_transactions.await_args.kwargs
        assert announce_kwargs["franchise"] == "Test Franchise"
        assert announce_kwargs["gm"] == 999
        assert "You must reconcile these issues" in announce_kwargs["embed"].description

        kwargs = interaction.followup.send.await_args.kwargs
        assert kwargs["ephemeral"] is True
        assert isinstance(kwargs["embed"], discord.Embed)


class TestTransactionHistoryApi:
    @pytest.fixture
    def mixin(self, mock_guild):
        m = _create_mixin()
        m._api_conf = {mock_guild.id: MagicMock()}
        m._league = {mock_guild.id: 1}
        return m

    @patch("rsc.transactions.transactions.TransactionsApi")
    @patch("rsc.abc.ApiClient")
    async def test_history_success(self, mock_client_cls, mock_api_cls, mixin, mock_guild):
        mock_api = AsyncMock()
        mock_result = MagicMock()
        mock_result.results = [_make_transaction_response(type=TransactionType.CUT)]
        mock_api.transactions_history_list.return_value = mock_result
        mock_api_cls.return_value = mock_api

        mock_ctx = AsyncMock()
        mock_ctx.__aenter__ = AsyncMock(return_value=mock_api)
        mock_ctx.__aexit__ = AsyncMock(return_value=False)
        mock_client_cls.return_value = mock_ctx

        result = await mixin.transaction_history(mock_guild, limit=10)
        assert len(result) == 1

    @patch("rsc.transactions.transactions.TransactionsApi")
    @patch("rsc.abc.ApiClient")
    async def test_history_with_filters(self, mock_client_cls, mock_api_cls, mixin, mock_guild, mock_member, mock_executor):
        mock_api = AsyncMock()
        mock_result = MagicMock()
        mock_result.results = []
        mock_api.transactions_history_list.return_value = mock_result
        mock_api_cls.return_value = mock_api

        mock_ctx = AsyncMock()
        mock_ctx.__aenter__ = AsyncMock(return_value=mock_api)
        mock_ctx.__aexit__ = AsyncMock(return_value=False)
        mock_client_cls.return_value = mock_ctx

        result = await mixin.transaction_history(
            mock_guild,
            player=mock_member,
            executor=mock_executor,
            season=25,
            trans_type=TransactionType.CUT,
            limit=5,
        )
        assert isinstance(result, list)

    @patch("rsc.transactions.transactions.TransactionsApi")
    @patch("rsc.abc.ApiClient")
    async def test_history_api_exception(self, mock_client_cls, mock_api_cls, mixin, mock_guild):
        mock_api = AsyncMock()
        exc = ApiException(status=500, reason="Internal Server Error")
        exc.body = None
        mock_api.transactions_history_list.side_effect = exc
        mock_api_cls.return_value = mock_api

        mock_ctx = AsyncMock()
        mock_ctx.__aenter__ = AsyncMock(return_value=mock_api)
        mock_ctx.__aexit__ = AsyncMock(return_value=False)
        mock_client_cls.return_value = mock_ctx

        with pytest.raises(RscException):
            await mixin.transaction_history(mock_guild)


class TestTransactionHistoryByIdApi:
    @pytest.fixture
    def mixin(self, mock_guild):
        m = _create_mixin()
        m._api_conf = {mock_guild.id: MagicMock()}
        m._league = {mock_guild.id: 1}
        return m

    @patch("rsc.transactions.transactions.TransactionsApi")
    @patch("rsc.abc.ApiClient")
    async def test_history_by_id_success(self, mock_client_cls, mock_api_cls, mixin, mock_guild):
        mock_api = AsyncMock()
        expected = _make_transaction_response(type=TransactionType.CUT, id=42)
        mock_api.transactions_history_retrieve.return_value = expected
        mock_api_cls.return_value = mock_api

        mock_ctx = AsyncMock()
        mock_ctx.__aenter__ = AsyncMock(return_value=mock_api)
        mock_ctx.__aexit__ = AsyncMock(return_value=False)
        mock_client_cls.return_value = mock_ctx

        result = await mixin.transaction_history_by_id(mock_guild, transaction_id=42)
        assert result is expected


class TestPagedTransactionHistoryApi:
    @pytest.fixture
    def mixin(self, mock_guild):
        m = _create_mixin()
        m._api_conf = {mock_guild.id: MagicMock()}
        m._league = {mock_guild.id: 1}
        return m

    @patch("rsc.transactions.transactions.TransactionsApi")
    @patch("rsc.abc.ApiClient")
    async def test_paged_history_iterates(self, mock_client_cls, mock_api_cls, mixin, mock_guild):
        mock_api = AsyncMock()

        page1 = MagicMock()
        t1 = _make_transaction_response(type=TransactionType.CUT, id=1)
        t2 = _make_transaction_response(type=TransactionType.PICKUP, id=2)
        page1.results = [t1, t2]
        page1.next = None  # Only one page

        mock_api.transactions_history_list.return_value = page1
        mock_api_cls.return_value = mock_api

        mock_ctx = AsyncMock()
        mock_ctx.__aenter__ = AsyncMock(return_value=mock_api)
        mock_ctx.__aexit__ = AsyncMock(return_value=False)
        mock_client_cls.return_value = mock_ctx

        results = [t async for t in mixin.paged_transaction_history(mock_guild, per_page=10)]

        assert len(results) == 2
        assert results[0] is t1
        assert results[1] is t2

    @patch("rsc.transactions.transactions.TransactionsApi")
    @patch("rsc.abc.ApiClient")
    async def test_paged_history_empty(self, mock_client_cls, mock_api_cls, mixin, mock_guild):
        mock_api = AsyncMock()
        page = MagicMock()
        page.results = []
        mock_api.transactions_history_list.return_value = page
        mock_api_cls.return_value = mock_api

        mock_ctx = AsyncMock()
        mock_ctx.__aenter__ = AsyncMock(return_value=mock_api)
        mock_ctx.__aexit__ = AsyncMock(return_value=False)
        mock_client_cls.return_value = mock_ctx

        results = [t async for t in mixin.paged_transaction_history(mock_guild, per_page=10)]

        assert len(results) == 0


# --- Defaults/Constants Tests ---


class TestTransactionDefaults:
    def test_defaults_type(self):
        assert isinstance(defaults, dict)

    def test_defaults_keys(self):
        assert defaults["TransChannel"] is None
        assert defaults["TransDMs"] is False
        assert defaults["TransLogChannel"] is None
        assert defaults["TransNotifications"] is False
        assert defaults["TransGMNotifications"] is False
        assert defaults["TransRole"] is None
        assert defaults["CutMessage"] is None
        assert defaults["Substitutes"] == []


class TestContractExpiredCard:
    async def test_built_from_the_saved_substitute(self, mock_guild):
        mixin = _create_mixin()
        sub = Substitute(
            date="2026-10-28T00:00:00",
            franchise="Hex_Systems",
            gm=999,
            player_in=111,
            player_out=222,
            team="Quantum",
            tier="Elite",
        )
        with patch("rsc.transactions.transactions.utils.tier_color_by_name", AsyncMock(return_value=discord.Colour.orange())):
            card = await mixin.build_contract_expired_card(mock_guild, sub, name="Sub_Name")
        assert (card.move, card.name, card.summary) == ("CONTRACT EXPIRED · Elite", r"Sub\_Name", r"leaves **Quantum** · Hex\_Systems")
        # The sub is the subject and leaves; the starter comes back in
        assert (card.player_id, card.starter_back_id, card.gm_id) == (111, 222, 999)
        assert card.banner == utils.CONTRACT_EXPIRED_BANNER
        assert isinstance(card.logo, Path) and card.logo.name == "EliteFA_64x64.png"
