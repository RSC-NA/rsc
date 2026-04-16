import json
import sys
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock, patch

import discord
import pytest
from rscapi.exceptions import ApiException
from rscapi.models.player import Player
from rscapi.models.player_transaction_updates import PlayerTransactionUpdates
from rscapi.models.transaction_response import TransactionResponse
from rscapi.models.franchise_identifier import FranchiseIdentifier
from rscapi.models.trade_item import TradeItem
from rscapi.models.trade_value import TradeValue
from rscapi.models.draft_pick import DraftPick
from rscapi.models.player1 import Player1
from rscapi.models.league_player import LeaguePlayer
from rscapi.models.tier import Tier

from rsc.enums import TransactionType
from rsc.exceptions import (
    MalformedTransactionResponse,
    RscException,
    TradeParserException,
)
from rsc.transactions.transactions import (
    FUTURE_TRADE_REGEX,
    GM_TRADE_REGEX,
    PICK_TRADE_REGEX,
    PLAYER_TRADE_REGEX,
    TransactionMixIn,
    defaults,
)
from rsc.types import Substitute, TransactionSettings


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


def _make_ptu(discord_id, name="TestPlayer", old_team=None, new_team=None, tier=None, franchise=None):
    ptu = MagicMock(spec=PlayerTransactionUpdates)
    ptu.player = MagicMock(spec=LeaguePlayer)
    ptu.player.player = _make_player(discord_id, name)
    ptu.player.tier = tier
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


# --- build_transaction_embed Tests ---


class TestBuildTransactionEmbed:
    """Test the build_transaction_embed method."""

    @pytest.fixture
    def mixin(self, mock_guild):
        m = _create_mixin()
        m.league_player_from_transaction = AsyncMock()
        m.franchise_logo = AsyncMock(return_value=None)
        return m

    async def test_raises_on_missing_type(self, mixin, mock_guild, mock_member):
        response = _make_transaction_response(type=None)
        with pytest.raises(MalformedTransactionResponse, match="type not returned"):
            await mixin.build_transaction_embed(mock_guild, response, mock_member)

    @patch("rsc.transactions.transactions.utils.transaction_image_from_type", new_callable=AsyncMock)
    @patch("rsc.transactions.transactions.utils.fa_img_from_tier", new_callable=AsyncMock)
    @patch("rsc.transactions.transactions.utils.tier_color_by_name", new_callable=AsyncMock)
    async def test_cut_embed(self, mock_tier_color, mock_fa_img, mock_trans_img, mixin, mock_guild, mock_member):
        # Setup
        mock_img = MagicMock(spec=discord.File)
        mock_img.filename = "Cut.png"
        mock_trans_img.return_value = mock_img
        mock_fa_img.return_value = None
        mock_tier_color.return_value = discord.Color.blue()

        old_team = MagicMock()
        old_team.tier = "Elite"
        old_team.name = "Team Alpha"

        franchise = _make_franchise_identifier("TestFranchise", 999)

        ptu = _make_ptu(mock_member.id, "TestPlayer", old_team=old_team)
        mixin.league_player_from_transaction.return_value = ptu

        response = _make_transaction_response(
            type=TransactionType.CUT,
            player_updates=[ptu],
            first_franchise=franchise,
        )

        embed, files = await mixin.build_transaction_embed(mock_guild, response, mock_member)
        assert isinstance(embed, discord.Embed)
        assert len(files) >= 1

    @patch("rsc.transactions.transactions.utils.transaction_image_from_type", new_callable=AsyncMock)
    @patch("rsc.transactions.transactions.utils.tier_color_by_name", new_callable=AsyncMock)
    async def test_pickup_embed(self, mock_tier_color, mock_trans_img, mixin, mock_guild, mock_member):
        mock_img = MagicMock(spec=discord.File)
        mock_img.filename = "Signed.png"
        mock_trans_img.return_value = mock_img
        mock_tier_color.return_value = discord.Color.green()

        new_team = MagicMock()
        new_team.tier = "Elite"
        new_team.name = "Team Alpha"

        franchise = _make_franchise_identifier("TestFranchise", 999)

        ptu = _make_ptu(mock_member.id, "TestPlayer", new_team=new_team)
        mixin.league_player_from_transaction.return_value = ptu

        response = _make_transaction_response(
            type=TransactionType.PICKUP,
            player_updates=[ptu],
            second_franchise=franchise,
        )

        embed, files = await mixin.build_transaction_embed(mock_guild, response, mock_member)
        assert isinstance(embed, discord.Embed)

    @patch("rsc.transactions.transactions.utils.transaction_image_from_type", new_callable=AsyncMock)
    @patch("rsc.transactions.transactions.utils.tier_color_by_name", new_callable=AsyncMock)
    async def test_resign_embed(self, mock_tier_color, mock_trans_img, mixin, mock_guild, mock_member):
        mock_img = MagicMock(spec=discord.File)
        mock_img.filename = "ReSigned.png"
        mock_trans_img.return_value = mock_img
        mock_tier_color.return_value = discord.Color.green()

        new_team = MagicMock()
        new_team.tier = "Elite"
        new_team.name = "Team Alpha"

        franchise = _make_franchise_identifier("TestFranchise", 999)

        ptu = _make_ptu(mock_member.id, "TestPlayer", new_team=new_team)
        mixin.league_player_from_transaction.return_value = ptu

        response = _make_transaction_response(
            type=TransactionType.RESIGN,
            player_updates=[ptu],
            second_franchise=franchise,
        )

        embed, files = await mixin.build_transaction_embed(mock_guild, response, mock_member)
        assert isinstance(embed, discord.Embed)

    @patch("rsc.transactions.transactions.utils.transaction_image_from_type", new_callable=AsyncMock)
    @patch("rsc.transactions.transactions.utils.tier_color_by_name", new_callable=AsyncMock)
    async def test_retire_embed(self, mock_tier_color, mock_trans_img, mixin, mock_guild, mock_member):
        mock_img = MagicMock(spec=discord.File)
        mock_img.filename = "Retired.png"
        mock_trans_img.return_value = mock_img
        mock_tier_color.return_value = discord.Color.blue()

        ptu = _make_ptu(mock_member.id, "TestPlayer")
        mixin.league_player_from_transaction.return_value = ptu

        franchise = _make_franchise_identifier("TestFranchise", 999)

        response = _make_transaction_response(
            type=TransactionType.RETIRE,
            player_updates=[ptu],
            first_franchise=franchise,
        )

        embed, files = await mixin.build_transaction_embed(mock_guild, response, mock_member)
        assert isinstance(embed, discord.Embed)

    @patch("rsc.transactions.transactions.utils.transaction_image_from_type", new_callable=AsyncMock)
    @patch("rsc.transactions.transactions.utils.tier_color_by_name", new_callable=AsyncMock)
    async def test_temp_fa_embed(self, mock_tier_color, mock_trans_img, mixin, mock_guild, mock_member):
        mock_img = MagicMock(spec=discord.File)
        mock_img.filename = "TempFA.png"
        mock_trans_img.return_value = mock_img
        mock_tier_color.return_value = discord.Color.blue()

        new_team = MagicMock()
        new_team.tier = "Elite"
        new_team.name = "Team Alpha"

        franchise = _make_franchise_identifier("TestFranchise", 999)

        ptu = _make_ptu(mock_member.id, "TestPlayer", new_team=new_team)
        mixin.league_player_from_transaction.return_value = ptu

        response = _make_transaction_response(
            type=TransactionType.TEMP_FA,
            player_updates=[ptu],
            second_franchise=franchise,
        )

        embed, files = await mixin.build_transaction_embed(mock_guild, response, mock_member)
        assert isinstance(embed, discord.Embed)

    @patch("rsc.transactions.transactions.utils.transaction_image_from_type", new_callable=AsyncMock)
    async def test_cut_embed_malformed_no_old_team(self, mock_trans_img, mixin, mock_guild, mock_member):
        mock_img = MagicMock(spec=discord.File)
        mock_img.filename = "Cut.png"
        mock_trans_img.return_value = mock_img

        ptu = _make_ptu(mock_member.id, "TestPlayer", old_team=None)
        mixin.league_player_from_transaction.return_value = ptu

        response = _make_transaction_response(
            type=TransactionType.CUT,
            player_updates=[ptu],
            first_franchise=None,
        )

        with pytest.raises(MalformedTransactionResponse):
            await mixin.build_transaction_embed(mock_guild, response, mock_member)

    @patch("rsc.transactions.transactions.utils.transaction_image_from_type", new_callable=AsyncMock)
    async def test_pickup_embed_malformed_no_new_team(self, mock_trans_img, mixin, mock_guild, mock_member):
        mock_img = MagicMock(spec=discord.File)
        mock_img.filename = "Signed.png"
        mock_trans_img.return_value = mock_img

        ptu = _make_ptu(mock_member.id, "TestPlayer", new_team=None)
        mixin.league_player_from_transaction.return_value = ptu

        response = _make_transaction_response(
            type=TransactionType.PICKUP,
            player_updates=[ptu],
            second_franchise=None,
        )

        with pytest.raises(MalformedTransactionResponse):
            await mixin.build_transaction_embed(mock_guild, response, mock_member)

    @patch("rsc.transactions.transactions.utils.transaction_image_from_type", new_callable=AsyncMock)
    async def test_build_embed_with_player_out(self, mock_trans_img, mixin, mock_guild, mock_member, mock_player_out):
        mock_img = MagicMock(spec=discord.File)
        mock_img.filename = "TempFA.png"
        mock_trans_img.return_value = mock_img

        new_team = MagicMock()
        new_team.tier = "Elite"
        new_team.name = "Team Alpha"

        franchise = _make_franchise_identifier("TestFranchise", 999)

        ptu = _make_ptu(mock_member.id, "TestPlayer", new_team=new_team)
        mixin.league_player_from_transaction.return_value = ptu

        response = _make_transaction_response(
            type=TransactionType.SUBSTITUTION,
            player_updates=[ptu],
            second_franchise=franchise,
        )

        embed, files = await mixin.build_transaction_embed(
            mock_guild, response, mock_member, player_out=mock_player_out
        )
        assert isinstance(embed, discord.Embed)
        # When player_out is provided, embed should have "Player In" and "Player Out" fields
        field_names = [f.name for f in embed.fields]
        assert "Player In" in field_names
        assert "Player Out" in field_names


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

    async def test_returns_none_when_no_channel(self, mixin, mock_guild):
        mixin._trans_channel.return_value = None
        embed = discord.Embed()
        result = await mixin.announce_transaction(mock_guild, embed=embed)
        assert result is None

    async def test_sends_and_edits_message(self, mixin, mock_guild, mock_member):
        mock_msg = MagicMock(spec=discord.Message)
        mock_msg.edit = AsyncMock()
        mock_channel = MagicMock(spec=discord.TextChannel)
        mock_channel.send = AsyncMock(return_value=mock_msg)
        mixin._trans_channel.return_value = mock_channel

        embed = discord.Embed()
        result = await mixin.announce_transaction(
            mock_guild, embed=embed, player=mock_member, gm=999
        )
        assert result is mock_msg
        mock_channel.send.assert_called_once()
        mock_msg.edit.assert_called_once()

    async def test_announce_with_int_player_and_gm(self, mixin, mock_guild):
        mock_msg = MagicMock(spec=discord.Message)
        mock_msg.edit = AsyncMock()
        mock_channel = MagicMock(spec=discord.TextChannel)
        mock_channel.send = AsyncMock(return_value=mock_msg)
        mixin._trans_channel.return_value = mock_channel

        embed = discord.Embed()
        result = await mixin.announce_transaction(
            mock_guild, embed=embed, player=111, gm=222
        )
        assert result is mock_msg
        call_kwargs = mock_channel.send.call_args
        assert "<@!111>" in call_kwargs.kwargs["content"]
        assert "<@!222>" in call_kwargs.kwargs["content"]


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
        result = await mixin.announce_to_transaction_committee(
            guild=mock_guild, embed=discord.Embed()
        )
        assert result is None

    async def test_returns_none_when_no_role(self, mixin, mock_guild):
        mock_channel = MagicMock(spec=discord.TextChannel)
        mock_channel.send = AsyncMock()
        mixin._trans_log_channel.return_value = mock_channel
        mixin._trans_role.return_value = None
        result = await mixin.announce_to_transaction_committee(
            guild=mock_guild, embed=discord.Embed()
        )
        assert result is None

    async def test_sends_message_successfully(self, mixin, mock_guild):
        mock_channel = MagicMock(spec=discord.TextChannel)
        mock_msg = MagicMock(spec=discord.Message)
        mock_channel.send = AsyncMock(return_value=mock_msg)
        mixin._trans_log_channel.return_value = mock_channel

        mock_role = MagicMock(spec=discord.Role)
        mock_role.mention = "@TransCommittee"
        mixin._trans_role.return_value = mock_role

        result = await mixin.announce_to_transaction_committee(
            guild=mock_guild, embed=discord.Embed()
        )
        assert result is mock_msg


# --- announce_to_franchise_transactions Tests ---


class TestAnnounceToFranchiseTransactions:
    @pytest.fixture
    def mixin(self):
        m = _create_mixin()
        m._trans_log_channel = AsyncMock(return_value=None)
        return m

    async def test_returns_none_when_no_channel(self, mixin, mock_guild):
        result = await mixin.announce_to_franchise_transactions(
            mock_guild, franchise="Test Franchise", gm=999, embed=discord.Embed()
        )
        assert result is None

    async def test_sends_to_matching_channel(self, mixin, mock_guild):
        mock_channel = MagicMock(spec=discord.TextChannel)
        mock_channel.name = "test-franchise-transactions"
        mock_msg = MagicMock(spec=discord.Message)
        mock_channel.send = AsyncMock(return_value=mock_msg)
        mock_guild.text_channels = [mock_channel]

        result = await mixin.announce_to_franchise_transactions(
            mock_guild, franchise="Test Franchise", gm=999, embed=discord.Embed()
        )
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
        src = FranchiseIdentifier(id=1, name="Source FC", gm=111)
        dest = FranchiseIdentifier(id=2, name="Dest FC", gm=222)
        value = TradeValue(player=Player1(id=333, team="Team A"), pick=None)
        trade = TradeItem(source=src, destination=dest, value=value)

        mock_guild.get_member = MagicMock(return_value=None)
        gms, embed = await mixin.build_trade_embed(mock_guild, [trade])
        assert 222 in gms
        assert 333 in gms

    async def test_pick_trade_embed(self, mixin, mock_guild):
        src = FranchiseIdentifier(id=1, name="Source FC", gm=111)
        dest = FranchiseIdentifier(id=2, name="Dest FC", gm=222)
        value = TradeValue(player=None, pick=DraftPick(tier="Elite", round=1, number=5, future=False))
        trade = TradeItem(source=src, destination=dest, value=value)

        mock_guild.get_member = MagicMock(return_value=None)
        gms, embed = await mixin.build_trade_embed(mock_guild, [trade])
        assert 222 in gms

    async def test_future_pick_trade_embed(self, mixin, mock_guild):
        src = FranchiseIdentifier(id=1, name="Source FC", gm=111)
        dest = FranchiseIdentifier(id=2, name="Dest FC", gm=222)
        value = TradeValue(player=None, pick=DraftPick(tier="Elite", round=2, number=0, future=True))
        trade = TradeItem(source=src, destination=dest, value=value)

        mock_guild.get_member = MagicMock(return_value=None)
        gms, embed = await mixin.build_trade_embed(mock_guild, [trade])
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
    @patch("rsc.transactions.transactions.ApiClient")
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
    @patch("rsc.transactions.transactions.ApiClient")
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
    @patch("rsc.transactions.transactions.ApiClient")
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
    @patch("rsc.transactions.transactions.ApiClient")
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

        from rsc.exceptions import PastTransactionsEndDate

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
    @patch("rsc.transactions.transactions.ApiClient")
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
    @patch("rsc.transactions.transactions.ApiClient")
    async def test_substitution_success(self, mock_client_cls, mock_api_cls, mixin, mock_guild, mock_member, mock_player_out, mock_executor):
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
    @patch("rsc.transactions.transactions.ApiClient")
    async def test_substitution_api_exception(self, mock_client_cls, mock_api_cls, mixin, mock_guild, mock_member, mock_player_out, mock_executor):
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
    @patch("rsc.transactions.transactions.ApiClient")
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
    @patch("rsc.transactions.transactions.ApiClient")
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
    @patch("rsc.transactions.transactions.ApiClient")
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
    @patch("rsc.transactions.transactions.ApiClient")
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
    @patch("rsc.transactions.transactions.ApiClient")
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
    @patch("rsc.transactions.transactions.ApiClient")
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
    @patch("rsc.transactions.transactions.ApiClient")
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


class TestTransactionHistoryApi:
    @pytest.fixture
    def mixin(self, mock_guild):
        m = _create_mixin()
        m._api_conf = {mock_guild.id: MagicMock()}
        m._league = {mock_guild.id: 1}
        return m

    @patch("rsc.transactions.transactions.TransactionsApi")
    @patch("rsc.transactions.transactions.ApiClient")
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
    @patch("rsc.transactions.transactions.ApiClient")
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
    @patch("rsc.transactions.transactions.ApiClient")
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
    @patch("rsc.transactions.transactions.ApiClient")
    async def test_history_by_id_success(self, mock_client_cls, mock_api_cls, mixin, mock_guild):
        mock_api = AsyncMock()
        expected = _make_transaction_response(type=TransactionType.CUT, id=42)
        mock_api.transactions_history_read.return_value = expected
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
    @patch("rsc.transactions.transactions.ApiClient")
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

        results = []
        async for t in mixin.paged_transaction_history(mock_guild, per_page=10):
            results.append(t)

        assert len(results) == 2
        assert results[0] is t1
        assert results[1] is t2

    @patch("rsc.transactions.transactions.TransactionsApi")
    @patch("rsc.transactions.transactions.ApiClient")
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

        results = []
        async for t in mixin.paged_transaction_history(mock_guild, per_page=10):
            results.append(t)

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
