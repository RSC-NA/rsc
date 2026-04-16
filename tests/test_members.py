from unittest.mock import AsyncMock, MagicMock, patch

import discord
import pytest
from rscapi.exceptions import ApiException
from rscapi.models.member import Member

from rsc.enums import Platform, PlayerType, Referrer, RegionPreference, Status
from rsc.exceptions import RscException
from rsc.members.members import MemberMixIn

GUILD_ID = 395806681994493964


def _create_mixin(**attrs):
    saved = MemberMixIn.__abstractmethods__
    MemberMixIn.__abstractmethods__ = frozenset()
    try:
        m = object.__new__(MemberMixIn)
    finally:
        MemberMixIn.__abstractmethods__ = saved
    for k, v in attrs.items():
        setattr(m, k, v)
    return m


# --- league_player_from_member ---


class TestLeaguePlayerFromMember:
    async def test_returns_matching_league_player(self, mock_guild):
        lp = MagicMock()
        lp.league = MagicMock()
        lp.league.id = 1
        member = MagicMock(spec=Member)
        member.player_leagues = [lp]
        mixin = _create_mixin(_league={mock_guild.id: 1})

        result = await mixin.league_player_from_member(mock_guild, member)
        assert result is lp

    async def test_returns_none_when_no_match(self, mock_guild):
        lp = MagicMock()
        lp.league = MagicMock()
        lp.league.id = 99
        member = MagicMock(spec=Member)
        member.player_leagues = [lp]
        mixin = _create_mixin(_league={mock_guild.id: 1})

        result = await mixin.league_player_from_member(mock_guild, member)
        assert result is None

    async def test_returns_none_when_no_player_leagues(self, mock_guild):
        member = MagicMock(spec=Member)
        member.player_leagues = None
        mixin = _create_mixin(_league={mock_guild.id: 1})

        result = await mixin.league_player_from_member(mock_guild, member)
        assert result is None

    async def test_returns_none_when_empty_leagues(self, mock_guild):
        member = MagicMock(spec=Member)
        member.player_leagues = []
        mixin = _create_mixin(_league={mock_guild.id: 1})

        result = await mixin.league_player_from_member(mock_guild, member)
        assert result is None


# --- members API ---


class TestMembersApi:
    async def test_returns_members(self, mock_guild):
        resp = MagicMock()
        resp.results = [MagicMock()]
        mixin = _create_mixin(_api_conf={mock_guild.id: MagicMock()})

        with patch("rsc.members.members.ApiClient") as mock_client:
            mock_api = AsyncMock()
            mock_api.members_list.return_value = resp
            mock_client.return_value.__aenter__ = AsyncMock(return_value=MagicMock())
            mock_client.return_value.__aexit__ = AsyncMock(return_value=False)
            with patch("rsc.members.members.MembersApi", return_value=mock_api):
                result = await mixin.members(mock_guild)

        assert len(result) == 1

    async def test_raises_rsc_exception(self, mock_guild):
        mixin = _create_mixin(_api_conf={mock_guild.id: MagicMock()})

        with patch("rsc.members.members.ApiClient") as mock_client:
            mock_api = AsyncMock()
            mock_api.members_list.side_effect = ApiException(status=500, reason="Error")
            mock_client.return_value.__aenter__ = AsyncMock(return_value=MagicMock())
            mock_client.return_value.__aexit__ = AsyncMock(return_value=False)
            with patch("rsc.members.members.MembersApi", return_value=mock_api):
                with pytest.raises(RscException):
                    await mixin.members(mock_guild)


# --- signup API ---


class TestSignupApi:
    async def test_signup_returns_league_player(self, mock_guild, mock_member):
        lp = MagicMock()
        mixin = _create_mixin(
            _api_conf={mock_guild.id: MagicMock()},
            _league={mock_guild.id: 1},
        )

        with patch("rsc.members.members.ApiClient") as mock_client:
            mock_api = AsyncMock()
            mock_api.members_signup.return_value = lp
            mock_client.return_value.__aenter__ = AsyncMock(return_value=MagicMock())
            mock_client.return_value.__aexit__ = AsyncMock(return_value=False)
            with patch("rsc.members.members.MembersApi", return_value=mock_api):
                result = await mixin.signup(
                    mock_guild,
                    member=mock_member,
                    rsc_name="TestPlayer",
                    trackers=["https://tracker.gg/1"],
                    platform=Platform.STEAM,
                    player_type=PlayerType.NEW,
                    referrer=Referrer.REDDIT,
                    region_preference=RegionPreference.EAST,
                )

        assert result is lp

    async def test_signup_raises_rsc_exception(self, mock_guild, mock_member):
        mixin = _create_mixin(
            _api_conf={mock_guild.id: MagicMock()},
            _league={mock_guild.id: 1},
        )

        with patch("rsc.members.members.ApiClient") as mock_client:
            mock_api = AsyncMock()
            mock_api.members_signup.side_effect = ApiException(status=400, reason="Bad")
            mock_client.return_value.__aenter__ = AsyncMock(return_value=MagicMock())
            mock_client.return_value.__aexit__ = AsyncMock(return_value=False)
            with patch("rsc.members.members.MembersApi", return_value=mock_api):
                with pytest.raises(RscException):
                    await mixin.signup(
                        mock_guild,
                        member=mock_member,
                        rsc_name="TestPlayer",
                        trackers=["https://tracker.gg/1"],
                        platform=Platform.STEAM,
                        player_type=PlayerType.NEW,
                        referrer=Referrer.REDDIT,
                        region_preference=RegionPreference.EAST,
                    )


# --- create_member API ---


class TestCreateMemberApi:
    async def test_creates_member(self, mock_guild, mock_member):
        created = MagicMock()
        mixin = _create_mixin(_api_conf={mock_guild.id: MagicMock()})

        with patch("rsc.members.members.ApiClient") as mock_client:
            mock_api = AsyncMock()
            mock_api.members_create.return_value = created
            mock_client.return_value.__aenter__ = AsyncMock(return_value=MagicMock())
            mock_client.return_value.__aexit__ = AsyncMock(return_value=False)
            with patch("rsc.members.members.MembersApi", return_value=mock_api):
                result = await mixin.create_member(mock_guild, member=mock_member)

        assert result is created

    async def test_raises_rsc_exception(self, mock_guild, mock_member):
        mixin = _create_mixin(_api_conf={mock_guild.id: MagicMock()})

        with patch("rsc.members.members.ApiClient") as mock_client:
            mock_api = AsyncMock()
            mock_api.members_create.side_effect = ApiException(status=400, reason="Bad")
            mock_client.return_value.__aenter__ = AsyncMock(return_value=MagicMock())
            mock_client.return_value.__aexit__ = AsyncMock(return_value=False)
            with patch("rsc.members.members.MembersApi", return_value=mock_api):
                with pytest.raises(RscException):
                    await mixin.create_member(mock_guild, member=mock_member)


# --- delete_member API ---


class TestDeleteMemberApi:
    async def test_deletes_member(self, mock_guild, mock_member):
        mixin = _create_mixin(_api_conf={mock_guild.id: MagicMock()})

        with patch("rsc.members.members.ApiClient") as mock_client:
            mock_api = AsyncMock()
            mock_api.members_delete.return_value = None
            mock_client.return_value.__aenter__ = AsyncMock(return_value=MagicMock())
            mock_client.return_value.__aexit__ = AsyncMock(return_value=False)
            with patch("rsc.members.members.MembersApi", return_value=mock_api):
                await mixin.delete_member(mock_guild, member=mock_member)

        mock_api.members_delete.assert_awaited_once_with(mock_member.id)

    async def test_raises_rsc_exception(self, mock_guild, mock_member):
        mixin = _create_mixin(_api_conf={mock_guild.id: MagicMock()})

        with patch("rsc.members.members.ApiClient") as mock_client:
            mock_api = AsyncMock()
            mock_api.members_delete.side_effect = ApiException(status=404, reason="Not Found")
            mock_client.return_value.__aenter__ = AsyncMock(return_value=MagicMock())
            mock_client.return_value.__aexit__ = AsyncMock(return_value=False)
            with patch("rsc.members.members.MembersApi", return_value=mock_api):
                with pytest.raises(RscException):
                    await mixin.delete_member(mock_guild, member=mock_member)


# --- change_member_name API ---


class TestChangeMemberNameApi:
    async def test_changes_name(self, mock_guild):
        updated = MagicMock()
        mixin = _create_mixin(_api_conf={mock_guild.id: MagicMock()})

        with patch("rsc.members.members.ApiClient") as mock_client:
            mock_api = AsyncMock()
            mock_api.members_name_change.return_value = updated
            mock_client.return_value.__aenter__ = AsyncMock(return_value=MagicMock())
            mock_client.return_value.__aexit__ = AsyncMock(return_value=False)
            with patch("rsc.members.members.MembersApi", return_value=mock_api):
                result = await mixin.change_member_name(mock_guild, id=111, name="NewName")

        assert result is updated

    async def test_raises_rsc_exception(self, mock_guild):
        mixin = _create_mixin(_api_conf={mock_guild.id: MagicMock()})

        with patch("rsc.members.members.ApiClient") as mock_client:
            mock_api = AsyncMock()
            mock_api.members_name_change.side_effect = ApiException(status=400, reason="Bad")
            mock_client.return_value.__aenter__ = AsyncMock(return_value=MagicMock())
            mock_client.return_value.__aexit__ = AsyncMock(return_value=False)
            with patch("rsc.members.members.MembersApi", return_value=mock_api):
                with pytest.raises(RscException):
                    await mixin.change_member_name(mock_guild, id=111, name="Bad")


# --- player_stats API ---


class TestPlayerStatsApi:
    async def test_returns_stats(self, mock_guild, mock_member):
        stats = MagicMock()
        mixin = _create_mixin(
            _api_conf={mock_guild.id: MagicMock()},
            _league={mock_guild.id: 1},
        )

        with patch("rsc.members.members.ApiClient") as mock_client:
            mock_api = AsyncMock()
            mock_api.members_stats.return_value = stats
            mock_client.return_value.__aenter__ = AsyncMock(return_value=MagicMock())
            mock_client.return_value.__aexit__ = AsyncMock(return_value=False)
            with patch("rsc.members.members.MembersApi", return_value=mock_api):
                result = await mixin.player_stats(mock_guild, player=mock_member)

        assert result is stats

    async def test_postseason_stats(self, mock_guild, mock_member):
        stats = MagicMock()
        mixin = _create_mixin(
            _api_conf={mock_guild.id: MagicMock()},
            _league={mock_guild.id: 1},
        )

        with patch("rsc.members.members.ApiClient") as mock_client:
            mock_api = AsyncMock()
            mock_api.members_postseason_stats.return_value = stats
            mock_client.return_value.__aenter__ = AsyncMock(return_value=MagicMock())
            mock_client.return_value.__aexit__ = AsyncMock(return_value=False)
            with patch("rsc.members.members.MembersApi", return_value=mock_api):
                result = await mixin.player_stats(mock_guild, player=mock_member, postseason=True)

        assert result is stats


# --- declare_intent API ---


class TestDeclareIntentApi:
    async def test_declares_intent(self, mock_guild, mock_member):
        deleted = MagicMock()
        mixin = _create_mixin(
            _api_conf={mock_guild.id: MagicMock()},
            _league={mock_guild.id: 1},
        )

        with patch("rsc.members.members.ApiClient") as mock_client:
            mock_api = AsyncMock()
            mock_api.members_intent_to_play.return_value = deleted
            mock_client.return_value.__aenter__ = AsyncMock(return_value=MagicMock())
            mock_client.return_value.__aexit__ = AsyncMock(return_value=False)
            with patch("rsc.members.members.MembersApi", return_value=mock_api):
                result = await mixin.declare_intent(mock_guild, member=mock_member, returning=True)

        assert result is deleted

    async def test_declares_intent_with_int_member(self, mock_guild):
        deleted = MagicMock()
        mixin = _create_mixin(
            _api_conf={mock_guild.id: MagicMock()},
            _league={mock_guild.id: 1},
        )

        with patch("rsc.members.members.ApiClient") as mock_client:
            mock_api = AsyncMock()
            mock_api.members_intent_to_play.return_value = deleted
            mock_client.return_value.__aenter__ = AsyncMock(return_value=MagicMock())
            mock_client.return_value.__aexit__ = AsyncMock(return_value=False)
            with patch("rsc.members.members.MembersApi", return_value=mock_api):
                result = await mixin.declare_intent(mock_guild, member=12345, returning=False)

        assert result is deleted
        mock_api.members_intent_to_play.assert_awaited_once()
        call_args = mock_api.members_intent_to_play.call_args
        assert call_args[0][0] == 12345


# --- activity_check API ---


class TestActivityCheckApi:
    async def test_activity_check(self, mock_guild, mock_member, mock_executor):
        check = MagicMock()
        mixin = _create_mixin(
            _api_conf={mock_guild.id: MagicMock()},
            _league={mock_guild.id: 1},
        )

        with patch("rsc.members.members.ApiClient") as mock_client:
            mock_api = AsyncMock()
            mock_api.members_activity_check.return_value = check
            mock_client.return_value.__aenter__ = AsyncMock(return_value=MagicMock())
            mock_client.return_value.__aexit__ = AsyncMock(return_value=False)
            with patch("rsc.members.members.MembersApi", return_value=mock_api):
                result = await mixin.activity_check(
                    mock_guild,
                    player=mock_member,
                    returning_status=True,
                    executor=mock_executor,
                )

        assert result is check


# --- transfer_membership API ---


class TestTransferMembershipApi:
    async def test_transfers(self, mock_guild, mock_member):
        transferred = MagicMock()
        mixin = _create_mixin(_api_conf={mock_guild.id: MagicMock()})

        with patch("rsc.members.members.ApiClient") as mock_client:
            mock_api = AsyncMock()
            mock_api.members_transfer_account.return_value = transferred
            mock_client.return_value.__aenter__ = AsyncMock(return_value=MagicMock())
            mock_client.return_value.__aexit__ = AsyncMock(return_value=False)
            with patch("rsc.members.members.MembersApi", return_value=mock_api):
                result = await mixin.transfer_membership(mock_guild, old=111, new=mock_member)

        assert result is transferred


# --- name_history API ---


class TestNameHistoryApi:
    async def test_returns_history(self, mock_guild, mock_member):
        history = [MagicMock(), MagicMock()]
        mixin = _create_mixin(_api_conf={mock_guild.id: MagicMock()})

        with patch("rsc.members.members.ApiClient") as mock_client:
            mock_api = AsyncMock()
            mock_api.members_name_changes.return_value = history
            mock_client.return_value.__aenter__ = AsyncMock(return_value=MagicMock())
            mock_client.return_value.__aexit__ = AsyncMock(return_value=False)
            with patch("rsc.members.members.MembersApi", return_value=mock_api):
                result = await mixin.name_history(mock_guild, member=mock_member)

        assert len(result) == 2


# --- make_league_player API ---


class TestMakeLeaguePlayerApi:
    async def test_makes_player(self, mock_guild, mock_member):
        lp = MagicMock()
        mixin = _create_mixin(
            _api_conf={mock_guild.id: MagicMock()},
            _league={mock_guild.id: 1},
        )

        with patch("rsc.members.members.ApiClient") as mock_client:
            mock_api = AsyncMock()
            mock_api.members_make_player.return_value = lp
            mock_client.return_value.__aenter__ = AsyncMock(return_value=MagicMock())
            mock_client.return_value.__aexit__ = AsyncMock(return_value=False)
            with patch("rsc.members.members.MembersApi", return_value=mock_api):
                result = await mixin.make_league_player(
                    mock_guild,
                    member=mock_member,
                    base_mmr=1000,
                    current_mmr=1050,
                    tier=1,
                )

        assert result is lp

    async def test_raises_rsc_exception(self, mock_guild, mock_member):
        mixin = _create_mixin(
            _api_conf={mock_guild.id: MagicMock()},
            _league={mock_guild.id: 1},
        )

        with patch("rsc.members.members.ApiClient") as mock_client:
            mock_api = AsyncMock()
            mock_api.members_make_player.side_effect = ApiException(status=400, reason="Bad")
            mock_client.return_value.__aenter__ = AsyncMock(return_value=MagicMock())
            mock_client.return_value.__aexit__ = AsyncMock(return_value=False)
            with patch("rsc.members.members.MembersApi", return_value=mock_api):
                with pytest.raises(RscException):
                    await mixin.make_league_player(
                        mock_guild,
                        member=mock_member,
                        base_mmr=1000,
                        current_mmr=1050,
                        tier=1,
                    )


# --- drop_player_from_league API ---


class TestDropPlayerFromLeagueApi:
    async def test_drops_player(self, mock_guild, mock_member):
        dropped = MagicMock()
        mixin = _create_mixin(
            _api_conf={mock_guild.id: MagicMock()},
            _league={mock_guild.id: 1},
        )

        with patch("rsc.members.members.ApiClient") as mock_client:
            mock_api = AsyncMock()
            mock_api.members_member_league_drop.return_value = dropped
            mock_client.return_value.__aenter__ = AsyncMock(return_value=MagicMock())
            mock_client.return_value.__aexit__ = AsyncMock(return_value=False)
            with patch("rsc.members.members.MembersApi", return_value=mock_api):
                result = await mixin.drop_player_from_league(mock_guild, member=mock_member)

        assert result is dropped

    async def test_raises_rsc_exception(self, mock_guild, mock_member):
        mixin = _create_mixin(
            _api_conf={mock_guild.id: MagicMock()},
            _league={mock_guild.id: 1},
        )

        with patch("rsc.members.members.ApiClient") as mock_client:
            mock_api = AsyncMock()
            mock_api.members_member_league_drop.side_effect = ApiException(status=400, reason="Bad")
            mock_client.return_value.__aenter__ = AsyncMock(return_value=MagicMock())
            mock_client.return_value.__aexit__ = AsyncMock(return_value=False)
            with patch("rsc.members.members.MembersApi", return_value=mock_api):
                with pytest.raises(RscException):
                    await mixin.drop_player_from_league(mock_guild, member=mock_member)
