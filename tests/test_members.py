import asyncio
import io
from unittest.mock import AsyncMock, MagicMock, patch

import discord
import pytest
from rscapi.models.franchise_gm import FranchiseGM
from rscapi.models.franchise_list import FranchiseList
from rscapi.models.member import Member

from rsc import const
from rsc.enums import Platform, PlayerType, Referrer, RegionPreference, StaffPositions, Status
from rsc.exceptions import RscException
from rsc.members.members import MemberMixIn
from rsc.members.tracker_links import TrackerLine
from rsc.members.views.intent import IntentState, IntentToPlayView
from rsc.members.views.signup import (
    SignupFlowView,
    AlreadySignedUp,
    AlreadySignedUpView,
    SignupAnswers,
    SignupContext,
    SignupKind,
    SignupOutcome,
    SignupPrefill,
    SignupSuccessView,
)

from .sync_fakes import MEMBER_ID, OCEAN_ROLE, TIERS, league_player, role_names, sync_guild, sync_member
from .utils import api_error, api_exception, command_callback

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

        with patch("rsc.abc.ApiClient") as mock_client:
            mock_api = AsyncMock()
            mock_api.members_list.return_value = resp
            mock_client.return_value.__aenter__ = AsyncMock(return_value=MagicMock())
            mock_client.return_value.__aexit__ = AsyncMock(return_value=False)
            with patch("rsc.members.members.MembersApi", return_value=mock_api):
                result = await mixin.members(mock_guild)

        assert len(result) == 1

    async def test_raises_rsc_exception(self, mock_guild):
        mixin = _create_mixin(_api_conf={mock_guild.id: MagicMock()})

        with patch("rsc.abc.ApiClient") as mock_client:
            mock_api = AsyncMock()
            mock_api.members_list.side_effect = api_exception(500, "Error")
            mock_client.return_value.__aenter__ = AsyncMock(return_value=MagicMock())
            mock_client.return_value.__aexit__ = AsyncMock(return_value=False)
            with patch("rsc.members.members.MembersApi", return_value=mock_api), pytest.raises(RscException):
                await mixin.members(mock_guild)


# --- signup API ---


class TestSignupApi:
    async def test_signup_returns_league_player(self, mock_guild, mock_member):
        lp = MagicMock()
        mixin = _create_mixin(
            _api_conf={mock_guild.id: MagicMock()},
            _league={mock_guild.id: 1},
        )

        with patch("rsc.abc.ApiClient") as mock_client:
            mock_api = AsyncMock()
            mock_api.members_signup_create.return_value = lp
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

        with patch("rsc.abc.ApiClient") as mock_client:
            mock_api = AsyncMock()
            mock_api.members_signup_create.side_effect = api_exception(400, "Bad")
            mock_client.return_value.__aenter__ = AsyncMock(return_value=MagicMock())
            mock_client.return_value.__aexit__ = AsyncMock(return_value=False)
            with patch("rsc.members.members.MembersApi", return_value=mock_api), pytest.raises(RscException):
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

        with patch("rsc.abc.ApiClient") as mock_client:
            mock_api = AsyncMock()
            mock_api.members_create.return_value = created
            mock_client.return_value.__aenter__ = AsyncMock(return_value=MagicMock())
            mock_client.return_value.__aexit__ = AsyncMock(return_value=False)
            with patch("rsc.members.members.MembersApi", return_value=mock_api):
                result = await mixin.create_member(mock_guild, member=mock_member)

        assert result is created

    async def test_raises_rsc_exception(self, mock_guild, mock_member):
        mixin = _create_mixin(_api_conf={mock_guild.id: MagicMock()})

        with patch("rsc.abc.ApiClient") as mock_client:
            mock_api = AsyncMock()
            mock_api.members_create.side_effect = api_exception(400, "Bad")
            mock_client.return_value.__aenter__ = AsyncMock(return_value=MagicMock())
            mock_client.return_value.__aexit__ = AsyncMock(return_value=False)
            with patch("rsc.members.members.MembersApi", return_value=mock_api), pytest.raises(RscException):
                await mixin.create_member(mock_guild, member=mock_member)


# --- delete_member API ---


class TestDeleteMemberApi:
    async def test_deletes_member(self, mock_guild, mock_member):
        mixin = _create_mixin(_api_conf={mock_guild.id: MagicMock()})

        with patch("rsc.abc.ApiClient") as mock_client:
            mock_api = AsyncMock()
            mock_api.members_destroy.return_value = None
            mock_client.return_value.__aenter__ = AsyncMock(return_value=MagicMock())
            mock_client.return_value.__aexit__ = AsyncMock(return_value=False)
            with patch("rsc.members.members.MembersApi", return_value=mock_api):
                await mixin.delete_member(mock_guild, member=mock_member)

        mock_api.members_destroy.assert_awaited_once_with(mock_member.id)

    async def test_raises_rsc_exception(self, mock_guild, mock_member):
        mixin = _create_mixin(_api_conf={mock_guild.id: MagicMock()})

        with patch("rsc.abc.ApiClient") as mock_client:
            mock_api = AsyncMock()
            mock_api.members_destroy.side_effect = api_exception(404, "Not Found")
            mock_client.return_value.__aenter__ = AsyncMock(return_value=MagicMock())
            mock_client.return_value.__aexit__ = AsyncMock(return_value=False)
            with patch("rsc.members.members.MembersApi", return_value=mock_api), pytest.raises(RscException):
                await mixin.delete_member(mock_guild, member=mock_member)


# --- change_member_name API ---


class TestChangeMemberNameApi:
    async def test_changes_name(self, mock_guild):
        updated = MagicMock()
        mixin = _create_mixin(_api_conf={mock_guild.id: MagicMock()})

        with patch("rsc.abc.ApiClient") as mock_client:
            mock_api = AsyncMock()
            mock_api.members_name_change_partial_update.return_value = updated
            mock_client.return_value.__aenter__ = AsyncMock(return_value=MagicMock())
            mock_client.return_value.__aexit__ = AsyncMock(return_value=False)
            with patch("rsc.members.members.MembersApi", return_value=mock_api):
                result = await mixin.change_member_name(mock_guild, id=111, name="NewName")

        assert result is updated

    async def test_raises_rsc_exception(self, mock_guild):
        mixin = _create_mixin(_api_conf={mock_guild.id: MagicMock()})

        with patch("rsc.abc.ApiClient") as mock_client:
            mock_api = AsyncMock()
            mock_api.members_name_change_partial_update.side_effect = api_exception(400, "Bad")
            mock_client.return_value.__aenter__ = AsyncMock(return_value=MagicMock())
            mock_client.return_value.__aexit__ = AsyncMock(return_value=False)
            with patch("rsc.members.members.MembersApi", return_value=mock_api), pytest.raises(RscException):
                await mixin.change_member_name(mock_guild, id=111, name="Bad")

    async def test_sends_executor_when_provided(self, mock_guild):
        """The admin who ran the command is attributed, not the bot's API key."""
        mixin = _create_mixin(_api_conf={mock_guild.id: MagicMock()})

        with patch("rsc.abc.ApiClient") as mock_client:
            mock_api = AsyncMock()
            mock_client.return_value.__aenter__ = AsyncMock(return_value=MagicMock())
            mock_client.return_value.__aexit__ = AsyncMock(return_value=False)
            with patch("rsc.members.members.MembersApi", return_value=mock_api):
                await mixin.change_member_name(mock_guild, id=111, name="NewName", executor=999)

        data = mock_api.members_name_change_partial_update.call_args.args[1]
        # The field is StrictInt -- a stringified id is rejected outright.
        assert isinstance(data.executor, int)
        assert data.executor == 999
        assert data.to_dict()["executor"] == 999

    async def test_omits_executor_when_absent(self, mock_guild):
        """An explicit null would override the API-side default of the caller."""
        mixin = _create_mixin(_api_conf={mock_guild.id: MagicMock()})

        with patch("rsc.abc.ApiClient") as mock_client:
            mock_api = AsyncMock()
            mock_client.return_value.__aenter__ = AsyncMock(return_value=MagicMock())
            mock_client.return_value.__aexit__ = AsyncMock(return_value=False)
            with patch("rsc.members.members.MembersApi", return_value=mock_api):
                await mixin.change_member_name(mock_guild, id=111, name="NewName")

        data = mock_api.members_name_change_partial_update.call_args.args[1]
        # None, never the string "None" -- StrictInt would reject the latter.
        assert data.executor is None
        assert "executor" not in data.to_dict()


# --- player_stats API ---


class TestPlayerStatsApi:
    async def test_returns_stats(self, mock_guild, mock_member):
        stats = MagicMock()
        mixin = _create_mixin(
            _api_conf={mock_guild.id: MagicMock()},
            _league={mock_guild.id: 1},
        )

        with patch("rsc.abc.ApiClient") as mock_client:
            mock_api = AsyncMock()
            mock_api.members_stats_retrieve.return_value = stats
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

        with patch("rsc.abc.ApiClient") as mock_client:
            mock_api = AsyncMock()
            mock_api.members_stats_retrieve.return_value = stats
            mock_client.return_value.__aenter__ = AsyncMock(return_value=MagicMock())
            mock_client.return_value.__aexit__ = AsyncMock(return_value=False)
            with patch("rsc.members.members.MembersApi", return_value=mock_api):
                result = await mixin.player_stats(mock_guild, player=mock_member, postseason=True)

        assert result is stats
        # The dedicated postseason endpoint is deprecated; postseason is now a
        # discriminator on the regular one.
        mock_api.members_postseason_stats_retrieve.assert_not_awaited()
        assert mock_api.members_stats_retrieve.await_args.kwargs["stats_type"] == "PST"


# --- declare_intent API ---


class TestDeclareIntentApi:
    async def test_declares_intent(self, mock_guild, mock_member):
        deleted = MagicMock()
        mixin = _create_mixin(
            _api_conf={mock_guild.id: MagicMock()},
            _league={mock_guild.id: 1},
        )

        with patch("rsc.abc.ApiClient") as mock_client:
            mock_api = AsyncMock()
            mock_api.members_intent_to_play_create.return_value = deleted
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

        with patch("rsc.abc.ApiClient") as mock_client:
            mock_api = AsyncMock()
            mock_api.members_intent_to_play_create.return_value = deleted
            mock_client.return_value.__aenter__ = AsyncMock(return_value=MagicMock())
            mock_client.return_value.__aexit__ = AsyncMock(return_value=False)
            with patch("rsc.members.members.MembersApi", return_value=mock_api):
                result = await mixin.declare_intent(mock_guild, member=12345, returning=False)

        assert result is deleted
        mock_api.members_intent_to_play_create.assert_awaited_once()
        call_args = mock_api.members_intent_to_play_create.call_args
        assert call_args[0][0] == 12345


# --- activity_check API ---


class TestActivityCheckApi:
    async def test_activity_check(self, mock_guild, mock_member, mock_executor):
        check = MagicMock()
        mixin = _create_mixin(
            _api_conf={mock_guild.id: MagicMock()},
            _league={mock_guild.id: 1},
        )

        with patch("rsc.abc.ApiClient") as mock_client:
            mock_api = AsyncMock()
            mock_api.members_activity_check_create.return_value = check
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

        with patch("rsc.abc.ApiClient") as mock_client:
            mock_api = AsyncMock()
            mock_api.members_transfer_account_create.return_value = transferred
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

        with patch("rsc.abc.ApiClient") as mock_client:
            mock_api = AsyncMock()
            resp = MagicMock()
            resp.results = history
            mock_api.members_name_changes_list.return_value = resp
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

        with patch("rsc.abc.ApiClient") as mock_client:
            mock_api = AsyncMock()
            mock_api.members_make_player_create.return_value = lp
            mock_client.return_value.__aenter__ = AsyncMock(return_value=MagicMock())
            mock_client.return_value.__aexit__ = AsyncMock(return_value=False)
            with patch("rsc.members.members.MembersApi", return_value=mock_api):
                result = await mixin.make_league_player(
                    mock_guild,
                    member=mock_member,
                    base_mmr=1000,
                    current_mmr=1050,
                    tier=1,
                    status=Status.DRAFT_ELIGIBLE,
                )

        assert result is lp

    async def test_raises_rsc_exception(self, mock_guild, mock_member):
        mixin = _create_mixin(
            _api_conf={mock_guild.id: MagicMock()},
            _league={mock_guild.id: 1},
        )

        with patch("rsc.abc.ApiClient") as mock_client:
            mock_api = AsyncMock()
            mock_api.members_make_player_create.side_effect = api_exception(400, "Bad")
            mock_client.return_value.__aenter__ = AsyncMock(return_value=MagicMock())
            mock_client.return_value.__aexit__ = AsyncMock(return_value=False)
            with patch("rsc.members.members.MembersApi", return_value=mock_api), pytest.raises(RscException):
                await mixin.make_league_player(
                    mock_guild,
                    member=mock_member,
                    base_mmr=1000,
                    current_mmr=1050,
                    tier=1,
                    status=Status.DRAFT_ELIGIBLE,
                )


# --- drop_player_from_league API ---


class TestDropPlayerFromLeagueApi:
    async def test_drops_player(self, mock_guild, mock_member):
        dropped = MagicMock()
        mixin = _create_mixin(
            _api_conf={mock_guild.id: MagicMock()},
            _league={mock_guild.id: 1},
        )

        with patch("rsc.abc.ApiClient") as mock_client:
            mock_api = AsyncMock()
            mock_api.members_member_league_drop_create.return_value = dropped
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

        with patch("rsc.abc.ApiClient") as mock_client:
            mock_api = AsyncMock()
            mock_api.members_member_league_drop_create.side_effect = api_exception(400, "Bad")
            mock_client.return_value.__aenter__ = AsyncMock(return_value=MagicMock())
            mock_client.return_value.__aexit__ = AsyncMock(return_value=False)
            with patch("rsc.members.members.MembersApi", return_value=mock_api), pytest.raises(RscException):
                await mixin.drop_player_from_league(mock_guild, member=mock_member)


# --- elevated role helpers ---


def _elevated_role(*, id=1, position=None, franchise_id=None):
    r = MagicMock()
    r.id = id
    r.position = position
    r.franchise_id = franchise_id
    return r


class TestMemberElevatedRolesApi:
    async def test_passes_member_id_and_filters(self, mock_guild):
        """2.0.0 renamed the path param `id` -> `member_id`. Passing the old
        name raises a pydantic ValidationError, not an ApiException, so it
        escapes the wrapper's error handling entirely."""
        roles = [_elevated_role(position="NUMS")]
        mixin = _create_mixin(_api_conf={mock_guild.id: MagicMock()}, _league={mock_guild.id: 42})

        with patch("rsc.abc.ApiClient") as mock_client:
            mock_api = AsyncMock()
            mock_api.members_elevated_roles_list.return_value = roles
            mock_client.return_value.__aenter__ = AsyncMock(return_value=MagicMock())
            mock_client.return_value.__aexit__ = AsyncMock(return_value=False)
            with patch("rsc.members.members.MembersApi", return_value=mock_api):
                result = await mixin.member_elevated_roles(mock_guild, 1234, position="NUMS")

        assert result is roles
        mock_api.members_elevated_roles_list.assert_awaited_once_with(member_id=1234, league=42, position="NUMS")

    async def test_rejects_removed_agm_filter(self, mock_guild):
        """`agm`/`gm` moved to FranchiseStaff and the query params are gone. The
        server ignores unknown params and answers 200 with the *unfiltered*
        list, so a leftover caller would silently get every staff row back.
        Keeping the kwarg off the signature turns that into a TypeError here."""
        mixin = _create_mixin(_api_conf={mock_guild.id: MagicMock()}, _league={mock_guild.id: 42})

        with pytest.raises(TypeError):
            await mixin.member_elevated_roles(mock_guild, 1234, agm=True)

    async def test_raises_rsc_exception_on_api_error(self, mock_guild):
        mixin = _create_mixin(_api_conf={mock_guild.id: MagicMock()}, _league={mock_guild.id: 42})

        with patch("rsc.abc.ApiClient") as mock_client:
            mock_api = AsyncMock()
            mock_api.members_elevated_roles_list.side_effect = api_exception(500, "Error")
            mock_client.return_value.__aenter__ = AsyncMock(return_value=MagicMock())
            mock_client.return_value.__aexit__ = AsyncMock(return_value=False)
            with patch("rsc.members.members.MembersApi", return_value=mock_api), pytest.raises(RscException):
                await mixin.member_elevated_roles(mock_guild, 1234)


class TestCreateElevatedRoleApi:
    async def test_creates_staff_position(self, mock_guild, mock_member, mock_executor):
        """`position` is required now: the API dropped the position-less grant
        that GM/AGM rows used to be."""
        created = MagicMock(spec=Member)
        mixin = _create_mixin(
            _api_conf={mock_guild.id: MagicMock()},
            _league={mock_guild.id: 1},
            _elevated_role_cache={},
        )

        with patch("rsc.abc.ApiClient") as mock_client:
            mock_api = AsyncMock()
            mock_api.members_elevated_roles_create.return_value = created
            mock_client.return_value.__aenter__ = AsyncMock(return_value=MagicMock())
            mock_client.return_value.__aexit__ = AsyncMock(return_value=False)
            with patch("rsc.members.members.MembersApi", return_value=mock_api):
                result = await mixin.create_elevated_role(
                    mock_guild, member=mock_member, executor=mock_executor, position=StaffPositions.NUMBERS
                )

        assert result is created
        kwargs = mock_api.members_elevated_roles_create.await_args.kwargs
        assert kwargs["member_id"] == mock_member.id
        assert kwargs["elevated_role_input"].to_dict() == {
            "league": 1,
            "position": "NUMS",
            "executor": mock_executor.id,
        }

    async def test_rejects_removed_agm_arguments(self, mock_guild, mock_member, mock_executor):
        """Pydantic silently discards unknown kwargs on the input model, so an
        `agm=True` left behind would post a bare staff grant instead of failing."""
        mixin = _create_mixin(_league={mock_guild.id: 1})

        with pytest.raises(TypeError):
            await mixin.create_elevated_role(
                mock_guild, member=mock_member, executor=mock_executor, position=StaffPositions.NUMBERS, agm=True
            )

    async def test_sends_position_code_when_provided(self, mock_guild, mock_member, mock_executor):
        mixin = _create_mixin(
            _api_conf={mock_guild.id: MagicMock()},
            _league={mock_guild.id: 1},
            _elevated_role_cache={},
        )

        with patch("rsc.abc.ApiClient") as mock_client:
            mock_api = AsyncMock()
            mock_client.return_value.__aenter__ = AsyncMock(return_value=MagicMock())
            mock_client.return_value.__aexit__ = AsyncMock(return_value=False)
            with patch("rsc.members.members.MembersApi", return_value=mock_api):
                await mixin.create_elevated_role(mock_guild, member=mock_member, executor=mock_executor, position=StaffPositions.NUMBERS)

        body = mock_api.members_elevated_roles_create.await_args.kwargs["elevated_role_input"].to_dict()
        assert body["position"] == "NUMS"

    async def test_accepts_raw_discord_ids(self, mock_guild):
        mixin = _create_mixin(
            _api_conf={mock_guild.id: MagicMock()},
            _league={mock_guild.id: 1},
            _elevated_role_cache={},
        )

        with patch("rsc.abc.ApiClient") as mock_client:
            mock_api = AsyncMock()
            mock_client.return_value.__aenter__ = AsyncMock(return_value=MagicMock())
            mock_client.return_value.__aexit__ = AsyncMock(return_value=False)
            with patch("rsc.members.members.MembersApi", return_value=mock_api):
                await mixin.create_elevated_role(mock_guild, member=111, executor=222, position=StaffPositions.NUMBERS)

        kwargs = mock_api.members_elevated_roles_create.await_args.kwargs
        assert kwargs["member_id"] == 111
        assert kwargs["elevated_role_input"].executor == 222

    async def test_invalidates_elevated_role_cache(self, mock_guild, mock_member, mock_executor):
        cache = {mock_guild.id: {mock_member.id: (9e9, frozenset({"NUMS"})), 999: (9e9, frozenset())}}
        mixin = _create_mixin(
            _api_conf={mock_guild.id: MagicMock()},
            _league={mock_guild.id: 1},
            _elevated_role_cache=cache,
        )

        with patch("rsc.abc.ApiClient") as mock_client:
            mock_api = AsyncMock()
            mock_client.return_value.__aenter__ = AsyncMock(return_value=MagicMock())
            mock_client.return_value.__aexit__ = AsyncMock(return_value=False)
            with patch("rsc.members.members.MembersApi", return_value=mock_api):
                await mixin.create_elevated_role(mock_guild, member=mock_member, executor=mock_executor, position=StaffPositions.NUMBERS)

        assert mock_member.id not in cache[mock_guild.id]
        assert 999 in cache[mock_guild.id]

    async def test_raises_rsc_exception_on_api_error(self, mock_guild, mock_member, mock_executor):
        mixin = _create_mixin(
            _api_conf={mock_guild.id: MagicMock()},
            _league={mock_guild.id: 1},
            _elevated_role_cache={},
        )

        with patch("rsc.abc.ApiClient") as mock_client:
            mock_api = AsyncMock()
            mock_api.members_elevated_roles_create.side_effect = api_exception(403, "Forbidden")
            mock_client.return_value.__aenter__ = AsyncMock(return_value=MagicMock())
            mock_client.return_value.__aexit__ = AsyncMock(return_value=False)
            with patch("rsc.members.members.MembersApi", return_value=mock_api), pytest.raises(RscException):
                await mixin.create_elevated_role(mock_guild, member=mock_member, executor=mock_executor, position=StaffPositions.NUMBERS)


class TestDeleteElevatedRoleApi:
    async def test_passes_member_and_role_ids_separately(self, mock_guild):
        """The generated parameter order is (id, member_id), which reads
        backwards. Transposing them hits /members/<role_id>/elevated_roles/<discord_id>/,
        which the server answers with a 404 or a 500 rather than an error the
        bot can explain."""
        mixin = _create_mixin(_api_conf={mock_guild.id: MagicMock()}, _elevated_role_cache={})

        with patch("rsc.abc.ApiClient") as mock_client:
            mock_api = AsyncMock()
            mock_client.return_value.__aenter__ = AsyncMock(return_value=MagicMock())
            mock_client.return_value.__aexit__ = AsyncMock(return_value=False)
            with patch("rsc.members.members.MembersApi", return_value=mock_api):
                await mixin.delete_elevated_role(mock_guild, discord_id=138778232802508801, role_id=9)

        mock_api.members_elevated_roles_destroy.assert_awaited_once_with(member_id=138778232802508801, id=9)

    async def test_invalidates_elevated_role_cache(self, mock_guild):
        cache = {mock_guild.id: {555: (9e9, frozenset({"NUMS"}))}}
        mixin = _create_mixin(_api_conf={mock_guild.id: MagicMock()}, _elevated_role_cache=cache)

        with patch("rsc.abc.ApiClient") as mock_client:
            mock_api = AsyncMock()
            mock_client.return_value.__aenter__ = AsyncMock(return_value=MagicMock())
            mock_client.return_value.__aexit__ = AsyncMock(return_value=False)
            with patch("rsc.members.members.MembersApi", return_value=mock_api):
                await mixin.delete_elevated_role(mock_guild, discord_id=555, role_id=9)

        assert 555 not in cache[mock_guild.id]

    async def test_raises_rsc_exception_on_api_error(self, mock_guild):
        mixin = _create_mixin(_api_conf={mock_guild.id: MagicMock()}, _elevated_role_cache={})

        with patch("rsc.abc.ApiClient") as mock_client:
            mock_api = AsyncMock()
            mock_api.members_elevated_roles_destroy.side_effect = api_exception(404, "Not Found")
            mock_client.return_value.__aenter__ = AsyncMock(return_value=MagicMock())
            mock_client.return_value.__aexit__ = AsyncMock(return_value=False)
            with patch("rsc.members.members.MembersApi", return_value=mock_api), pytest.raises(RscException):
                await mixin.delete_elevated_role(mock_guild, discord_id=555, role_id=9)


class TestInvalidateElevatedRoleCache:
    def test_no_op_when_cache_absent(self, mock_guild):
        """Mixins built by tests and MockBot never ran __init__."""
        mixin = _create_mixin()
        mixin.invalidate_elevated_role_cache(mock_guild, 1234)

    def test_clears_whole_guild_when_no_member_given(self, mock_guild):
        cache = {mock_guild.id: {1: (9e9, frozenset())}, 999: {2: (9e9, frozenset())}}
        mixin = _create_mixin(_elevated_role_cache=cache)

        mixin.invalidate_elevated_role_cache(mock_guild)

        assert mock_guild.id not in cache
        assert 999 in cache


# --- _intent_to_play_flow ---


class TestIntentToPlayFlowTimeout:
    """A timed out view has already shown "Time Out". The flow must not replace it."""

    async def test_timeout_keeps_time_out_message(self, mock_guild):
        mixin = _create_mixin(declare_intent=AsyncMock())
        interaction = MagicMock()
        interaction.edit_original_response = AsyncMock()

        with patch("rsc.members.members.IntentToPlayView") as view_cls:
            view = view_cls.return_value
            view.prompt = AsyncMock()
            view.wait = AsyncMock(return_value=True)
            await mixin._intent_to_play_flow(interaction, mock_guild, MagicMock())

        interaction.edit_original_response.assert_not_awaited()
        mixin.declare_intent.assert_not_awaited()


def _intent_mixin(row, **attrs):
    defaults = {
        "declare_intent": AsyncMock(return_value=MagicMock()),
        "effective_player": AsyncMock(return_value=row),
        "tiers": AsyncMock(return_value=TIERS),
        "agm_franchise_of": AsyncMock(return_value=None),
        "franchises": AsyncMock(return_value=[]),
        "_get_welcome_roles": AsyncMock(return_value=[]),
    }
    defaults.update(attrs)
    return _create_mixin(**defaults)


async def _declare(mixin, member, returning: bool, on_reply=None) -> MagicMock:
    interaction = MagicMock()
    interaction.edit_original_response = AsyncMock(side_effect=on_reply)
    with patch("rsc.members.members.IntentToPlayView") as view_cls:
        view = view_cls.return_value
        view.prompt = AsyncMock()
        view.wait = AsyncMock(return_value=False)
        view.state = IntentState.FINISHED
        view.result = returning
        await mixin._intent_to_play_flow(interaction, member.guild, member)
    return interaction


def _reply_title(interaction) -> str:
    view = interaction.edit_original_response.await_args.kwargs["view"]
    return next(item.content for item in view.walk_children() if isinstance(item, discord.ui.TextDisplay))


ROSTERED_ROLES = [const.LEAGUE_ROLE, "Premier", OCEAN_ROLE]


class TestIntentToPlayFlowSync:
    async def test_returning_player_gets_the_new_rows_roles_before_the_reply(self):
        member = sync_member(sync_guild(), held=ROSTERED_ROLES, nick="OCE | nickm")
        mixin = _intent_mixin(league_player(Status.DRAFT_ELIGIBLE))
        held_at_reply: list[set[str]] = []

        interaction = await _declare(mixin, member, returning=True, on_reply=lambda **_: held_at_reply.append(role_names(member)))

        assert held_at_reply == [{const.LEAGUE_ROLE, "Premier", const.DRAFT_ELIGIBLE}]
        assert member.display_name == "DE | nickm"
        assert _reply_title(interaction) == "## Intent to Play Declared"

    async def test_not_returning_player_becomes_non_playing(self):
        member = sync_member(sync_guild(), held=ROSTERED_ROLES, nick="OCE | nickm")

        interaction = await _declare(_intent_mixin(None), member, returning=False)

        assert role_names(member) == {const.FORMER_PLAYER_ROLE}
        assert member.display_name == "nickm"
        assert _reply_title(interaction) == "## Intent to Play Declared"

    async def test_not_returning_player_keeps_a_roster_spot_that_still_holds(self):
        member = sync_member(sync_guild(), held=ROSTERED_ROLES, nick="OCE | nickm")

        interaction = await _declare(_intent_mixin(league_player(Status.ROSTERED)), member, returning=False)

        assert role_names(member) == set(ROSTERED_ROLES)
        assert member.display_name == "OCE | nickm"
        assert _reply_title(interaction) == "## Intent to Play Declared"

    async def test_nickname_that_does_not_fit_still_gets_the_roles_and_the_success_reply(self):
        name = "a" * 30
        member = sync_member(sync_guild(), held=ROSTERED_ROLES, nick=name)

        interaction = await _declare(_intent_mixin(league_player(Status.DRAFT_ELIGIBLE, name=name)), member, returning=True)

        assert const.DRAFT_ELIGIBLE in role_names(member)
        assert member.display_name == name
        assert _reply_title(interaction) == "## Intent to Play Declared"

    @pytest.mark.parametrize("row", [None, league_player(Status.UNSIGNED_GM, name="someone")], ids=["no row", "unsigned GM row"])
    async def test_gm_is_synced_as_the_gm_of_their_franchise(self, row):
        member = sync_member(sync_guild(), held=[const.GM_ROLE], nick="someone")
        ocean = FranchiseList(name="The Ocean", prefix="OCE", gm=FranchiseGM(rsc_name="someone", discord_id=MEMBER_ID))

        await _declare(_intent_mixin(row, franchises=AsyncMock(return_value=[ocean])), member, returning=row is not None)

        assert {const.GM_ROLE, OCEAN_ROLE} <= role_names(member)
        assert member.display_name == "OCE | someone"

    async def test_failed_sync_still_reports_the_declaration(self):
        member = sync_member(sync_guild(), held=ROSTERED_ROLES, nick="OCE | nickm")
        mixin = _intent_mixin(None, effective_player=AsyncMock(side_effect=api_error(500)))

        interaction = await _declare(mixin, member, returning=False)

        assert role_names(member) == set(ROSTERED_ROLES)
        assert _reply_title(interaction) == "## Intent to Play Declared"

    async def test_refused_declaration_changes_no_roles(self):
        member = sync_member(sync_guild(), held=ROSTERED_ROLES, nick="OCE | nickm")
        mixin = _intent_mixin(None, declare_intent=AsyncMock(side_effect=api_error(400, "Sign-ups are closed.")))

        interaction = await _declare(mixin, member, returning=False)

        assert role_names(member) == set(ROSTERED_ROLES)
        assert _reply_title(interaction) == "## API Error"


# --- /signup and /permfa ---

EPIC_TRACKER = "https://rocketleague.tracker.network/rocket-league/profile/epic/Xentrick/overview"


def _signup_mixin(**attrs):
    defaults = {
        "_league": {GUILD_ID: 1},
        "members": AsyncMock(return_value=[]),
        "create_member": AsyncMock(),
        "trackers": AsyncMock(return_value=[]),
        "signup": AsyncMock(return_value=MagicMock()),
        "permfa_signup": AsyncMock(return_value=MagicMock()),
        "should_get_devleague_role": AsyncMock(return_value=False),
    }
    defaults.update(attrs)
    return _create_mixin(**defaults)


def _flow_mock(kind: SignupKind | None, outcome: SignupOutcome = SignupOutcome.SUBMITTED) -> MagicMock:
    flow = MagicMock()
    flow.start = AsyncMock()
    flow.wait_for_outcome = AsyncMock(return_value=outcome)
    flow.submit_interaction = MagicMock()
    flow.submit_interaction.edit_original_response = AsyncMock()
    flow.answers = SignupAnswers(
        nights_confirmed=True,
        rules_accepted=True,
        kind=kind,
        player_type=PlayerType.NEW,
        region=RegionPreference.EAST,
        rsc_name="Xentrick",
        platform=Platform.EPIC,
        referrer=Referrer.FRIEND,
        trackers=[TrackerLine(raw=EPIC_TRACKER, url=EPIC_TRACKER, platform="epic", player_id="Xentrick")],
    )
    return flow


async def _run_flow(mixin, mock_guild, mock_member, flow, banner=None, banner_error=None):
    banner_file = AsyncMock(return_value=banner, side_effect=banner_error)
    with (
        patch("rsc.members.members.SignupFlowView", return_value=flow),
        patch("rsc.members.members.update_league_player_discord", AsyncMock()),
        patch("rsc.members.members.signup_banner_file", banner_file),
    ):
        await mixin._signup_flow(MagicMock(), mock_guild, mock_member, SignupContext(season_number=24))
    return banner_file


class TestSignupFlow:
    async def test_signup_sends_parsed_trackers_and_banner(self, mock_guild, mock_member):
        mixin = _signup_mixin()
        flow = _flow_mock(SignupKind.FREE_AGENT)
        banner = discord.File(io.BytesIO(b"webp"), filename="signup.webp")
        banner_file = await _run_flow(mixin, mock_guild, mock_member, flow, banner=banner)

        mixin.signup.assert_awaited_once()
        assert mixin.signup.await_args.kwargs["trackers"] == [EPIC_TRACKER]
        assert mixin.signup.await_args.kwargs["accepted_rules"] is True
        assert mixin.signup.await_args.kwargs["accepted_match_nights"] is True
        mixin.permfa_signup.assert_not_awaited()
        assert banner_file.await_args.kwargs["kicker"] == "RSC · SEASON 24"
        kwargs = flow.submit_interaction.edit_original_response.await_args.kwargs
        assert isinstance(kwargs["view"], SignupSuccessView)
        assert kwargs["attachments"] == [banner]

    async def test_permfa_choice_uses_permfa_endpoint(self, mock_guild, mock_member):
        mixin = _signup_mixin()
        await _run_flow(mixin, mock_guild, mock_member, _flow_mock(SignupKind.PERMFA), banner=MagicMock())
        mixin.permfa_signup.assert_awaited_once()
        mixin.signup.assert_not_awaited()

    async def test_banner_failure_still_reports_success(self, mock_guild, mock_member):
        mixin = _signup_mixin()
        flow = _flow_mock(SignupKind.FREE_AGENT)
        await _run_flow(mixin, mock_guild, mock_member, flow, banner_error=OSError("font"))
        kwargs = flow.submit_interaction.edit_original_response.await_args.kwargs
        assert isinstance(kwargs["view"], SignupSuccessView)
        assert kwargs["attachments"] == []

    async def test_duplicate_shows_already_signed_up(self, mock_guild, mock_member):
        mixin = _signup_mixin(signup=AsyncMock(side_effect=api_error(409, "Conflict")))
        flow = _flow_mock(SignupKind.FREE_AGENT)
        await _run_flow(mixin, mock_guild, mock_member, flow)
        view = flow.submit_interaction.edit_original_response.await_args.kwargs["view"]
        assert isinstance(view, AlreadySignedUpView)
        assert view.state is AlreadySignedUp.SIGNUP

    async def test_unconfirmed_answers_are_not_sent(self, mock_guild, mock_member):
        mixin = _signup_mixin()
        flow = _flow_mock(SignupKind.FREE_AGENT)
        flow.answers.rules_accepted = False
        await _run_flow(mixin, mock_guild, mock_member, flow)
        mixin.signup.assert_not_awaited()
        view = flow.submit_interaction.edit_original_response.await_args.kwargs["view"]
        assert "Signup Failed" in view.children[0].children[0].content

    async def test_prefill_starts_once_the_message_is_up(self, mock_guild, mock_member):
        mixin = _signup_mixin()
        flow = _flow_mock(SignupKind.FREE_AGENT, outcome=SignupOutcome.CANCELLED)
        flow.prefill = None
        await _run_flow(mixin, mock_guild, mock_member, flow)
        flow.start.assert_awaited_once()
        assert isinstance(flow.prefill, asyncio.Task)
        await flow.prefill

    async def test_cancelled_sends_nothing(self, mock_guild, mock_member):
        mixin = _signup_mixin()
        flow = _flow_mock(SignupKind.FREE_AGENT, outcome=SignupOutcome.CANCELLED)
        await _run_flow(mixin, mock_guild, mock_member, flow)
        mixin.signup.assert_not_awaited()
        flow.submit_interaction.edit_original_response.assert_not_awaited()


class TestSignupPrefill:
    async def test_existing_member_prefills_name_and_trackers(self, mock_guild, mock_member):
        member = MagicMock(spec=Member)
        member.rsc_name = "Xentrick"
        tracker = MagicMock()
        tracker.link = EPIC_TRACKER
        mixin = _signup_mixin(members=AsyncMock(return_value=[member]), trackers=AsyncMock(return_value=[tracker]))

        prefill = await mixin._signup_prefill(mock_guild, mock_member, None, looked_up=False)

        assert prefill == SignupPrefill(rsc_name="Xentrick", trackers=(EPIC_TRACKER,))
        mixin.create_member.assert_not_awaited()

    async def test_new_member_is_created_without_a_name(self, mock_guild, mock_member):
        mixin = _signup_mixin()
        prefill = await mixin._signup_prefill(mock_guild, mock_member, None, looked_up=False)
        assert prefill == SignupPrefill()
        mixin.create_member.assert_awaited_once()

    async def test_lookup_errors_leave_the_form_empty(self, mock_guild, mock_member):
        error = api_error(500, "Down")
        mixin = _signup_mixin(trackers=AsyncMock(side_effect=error))
        prefill = await mixin._signup_prefill(mock_guild, mock_member, None, looked_up=True)
        assert prefill.trackers == ()


class TestPermFAPrecheck:
    async def _run(self, mock_guild, mock_member, status):
        league_player = MagicMock()
        league_player.league.id = 1
        league_player.status = status
        member = MagicMock(spec=Member)
        member.player_leagues = [league_player]
        mixin = _signup_mixin(members=AsyncMock(return_value=[member]))
        state, found = await mixin._permfa_precheck(mock_guild, mock_member)
        assert found is member
        return state

    async def test_permfa_sees_e3(self, mock_guild, mock_member):
        assert await self._run(mock_guild, mock_member, Status.PERM_FA) is AlreadySignedUp.PERMFA

    async def test_waiting_permfa_sees_e3w(self, mock_guild, mock_member):
        assert await self._run(mock_guild, mock_member, Status.PERMFA_W) is AlreadySignedUp.PERMFA_WAITING

    async def test_anyone_else_gets_the_form(self, mock_guild, mock_member):
        assert await self._run(mock_guild, mock_member, Status.DROPPED) is None

    async def test_lookup_error_falls_through_to_the_form(self, mock_guild, mock_member):
        mixin = _signup_mixin(members=AsyncMock(side_effect=api_error(500, "Down")))
        assert await mixin._permfa_precheck(mock_guild, mock_member) == (None, None)


class TestPermFACommand:
    """`/permfa`: the status check, then the same flow with PermFA preselected"""

    def _interaction(self, mock_guild, mock_member) -> MagicMock:
        interaction = MagicMock(spec=discord.Interaction)
        interaction.guild = mock_guild
        interaction.user = mock_member
        interaction.response = MagicMock()
        interaction.response.defer = AsyncMock()
        interaction.followup = MagicMock()
        interaction.followup.send = AsyncMock()
        return interaction

    async def test_existing_permfa_sees_e3_before_step_one(self, mock_guild, mock_member):
        mixin = _signup_mixin(_permfa_precheck=AsyncMock(return_value=(AlreadySignedUp.PERMFA, None)), _signup_flow=AsyncMock())
        interaction = self._interaction(mock_guild, mock_member)
        await command_callback(MemberMixIn._member_permfa_signup)(mixin, interaction)

        mixin._signup_flow.assert_not_awaited()
        interaction.response.defer.assert_awaited_once_with(ephemeral=True)
        view = interaction.followup.send.await_args.kwargs["view"]
        assert isinstance(view, AlreadySignedUpView)
        assert view.state is AlreadySignedUp.PERMFA

    async def test_waiting_permfa_sees_e3w(self, mock_guild, mock_member):
        mixin = _signup_mixin(_permfa_precheck=AsyncMock(return_value=(AlreadySignedUp.PERMFA_WAITING, None)), _signup_flow=AsyncMock())
        interaction = self._interaction(mock_guild, mock_member)
        await command_callback(MemberMixIn._member_permfa_signup)(mixin, interaction)
        assert interaction.followup.send.await_args.kwargs["view"].state is AlreadySignedUp.PERMFA_WAITING

    async def test_anyone_else_starts_with_permfa_picked(self, mock_guild, mock_member):
        member = MagicMock(spec=Member)
        mixin = _signup_mixin(_permfa_precheck=AsyncMock(return_value=(None, member)), _signup_flow=AsyncMock())
        interaction = self._interaction(mock_guild, mock_member)
        await command_callback(MemberMixIn._member_permfa_signup)(mixin, interaction)

        interaction.followup.send.assert_not_awaited()
        args = mixin._signup_flow.await_args
        context = args.args[3]
        assert (context.command, context.kind) == ("permfa", SignupKind.PERMFA)
        assert args.kwargs == {"member": member, "looked_up": True}

        flow = SignupFlowView(interaction, context)
        assert flow.answers.kind is SignupKind.PERMFA


# --- /signup and /permfa answer inside Discord's 3 second window ---

ACK_DEADLINE = 3.0


class _Clock:
    """Time as the member's Discord client sees it, moved forward by each RSC API call"""

    def __init__(self, now: float = 0.0):
        self.now = now

    def api_call(self, seconds: float, result=None, error: Exception | None = None) -> AsyncMock:
        async def call(*args, **kwargs):
            self.now += seconds
            if error:
                raise error
            return result

        return AsyncMock(side_effect=call)


def _discord_interaction(mock_guild, mock_member, clock: _Clock) -> MagicMock:
    """An interaction that, like Discord, answers 10062 to a first response sent after the 3 second window"""
    interaction = MagicMock(spec=discord.Interaction)
    interaction.guild = mock_guild
    interaction.user = mock_member
    acknowledged = False

    async def acknowledge(*args, **kwargs):
        nonlocal acknowledged
        if clock.now > ACK_DEADLINE:
            raise discord.NotFound(MagicMock(status=404, reason="Not Found"), {"code": 10062, "message": "Unknown interaction"})
        acknowledged = True

    interaction.response = MagicMock()
    interaction.response.is_done.side_effect = lambda: acknowledged
    interaction.response.defer = AsyncMock(side_effect=acknowledge)
    interaction.response.send_message = AsyncMock(side_effect=acknowledge)
    interaction.followup = MagicMock()
    interaction.followup.send = AsyncMock()
    interaction.edit_original_response = AsyncMock()
    return interaction


def _shown(interaction: MagicMock) -> list:
    """Every view or embed the member was sent, by whichever route"""
    calls = [
        *interaction.response.send_message.await_args_list,
        *interaction.followup.send.await_args_list,
        *interaction.edit_original_response.await_args_list,
    ]
    return [call.kwargs.get("view") or call.kwargs.get("embed") for call in calls]


class TestSignupAnswersInTime:
    """However long the RSC API takes, the member gets an answer instead of "The application did not respond\""""

    SEASON = MagicMock(id=12, number=28)

    async def test_new_player_gets_step_one(self, mock_guild, mock_member):
        clock = _Clock()
        mixin = _signup_mixin(next_signup_season=clock.api_call(1.2, self.SEASON), players=clock.api_call(1.2, []))
        interaction = _discord_interaction(mock_guild, mock_member, clock)

        with patch.object(SignupFlowView, "wait_for_outcome", AsyncMock(return_value=SignupOutcome.CANCELLED)):
            await command_callback(MemberMixIn._member_signup)(mixin, interaction)

        assert clock.now > ACK_DEADLINE, "the lookups must outlast the window for this to prove anything"
        [view] = _shown(interaction)
        assert isinstance(view, SignupFlowView)

    async def test_current_player_gets_the_intent_prompt(self, mock_guild, mock_member):
        clock = _Clock()
        mixin = _signup_mixin(next_signup_season=clock.api_call(1.6, self.SEASON), players=clock.api_call(1.6, [MagicMock()]))
        interaction = _discord_interaction(mock_guild, mock_member, clock)

        with patch.object(IntentToPlayView, "wait", AsyncMock(return_value=True)):
            await command_callback(MemberMixIn._member_signup)(mixin, interaction)

        [view] = _shown(interaction)
        assert isinstance(view, IntentToPlayView)

    async def test_api_error_is_reported(self, mock_guild, mock_member):
        clock = _Clock()
        mixin = _signup_mixin(next_signup_season=clock.api_call(3.5, error=api_error(500, "Down")))
        interaction = _discord_interaction(mock_guild, mock_member, clock)

        await command_callback(MemberMixIn._member_signup)(mixin, interaction)

        [embed] = _shown(interaction)
        assert isinstance(embed, discord.Embed)

    async def test_existing_permfa_is_told(self, mock_guild, mock_member):
        clock = _Clock()
        mixin = _signup_mixin(_permfa_precheck=clock.api_call(3.5, (AlreadySignedUp.PERMFA, None)), _signup_flow=AsyncMock())
        interaction = _discord_interaction(mock_guild, mock_member, clock)

        await command_callback(MemberMixIn._member_permfa_signup)(mixin, interaction)

        [view] = _shown(interaction)
        assert isinstance(view, AlreadySignedUpView)
        assert view.state is AlreadySignedUp.PERMFA

    async def test_new_permfa_gets_step_one(self, mock_guild, mock_member):
        clock = _Clock()
        mixin = _signup_mixin(_permfa_precheck=clock.api_call(3.5, (None, None)))
        interaction = _discord_interaction(mock_guild, mock_member, clock)

        with patch.object(SignupFlowView, "wait_for_outcome", AsyncMock(return_value=SignupOutcome.CANCELLED)):
            await command_callback(MemberMixIn._member_permfa_signup)(mixin, interaction)

        [view] = _shown(interaction)
        assert isinstance(view, SignupFlowView)
        assert view.answers.kind is SignupKind.PERMFA

    async def test_an_interaction_discord_already_dropped_runs_no_lookups(self, mock_guild, mock_member):
        clock = _Clock(now=ACK_DEADLINE + 1)
        mixin = _signup_mixin(next_signup_season=clock.api_call(0.4, self.SEASON), players=clock.api_call(0.4, []))
        interaction = _discord_interaction(mock_guild, mock_member, clock)

        await command_callback(MemberMixIn._member_signup)(mixin, interaction)

        mixin.next_signup_season.assert_not_awaited()
        assert _shown(interaction) == []
