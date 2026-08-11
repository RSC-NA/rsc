from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from rscapi.exceptions import ApiException
from rscapi.models.member import Member

from rsc.enums import Platform, PlayerType, Referrer, RegionPreference, StaffPositions
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
            mock_api.members_signup_create.side_effect = ApiException(status=400, reason="Bad")
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
            mock_api.members_destroy.side_effect = ApiException(status=404, reason="Not Found")
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
            mock_api.members_name_change_partial_update.side_effect = ApiException(status=400, reason="Bad")
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
                )

        assert result is lp

    async def test_raises_rsc_exception(self, mock_guild, mock_member):
        mixin = _create_mixin(
            _api_conf={mock_guild.id: MagicMock()},
            _league={mock_guild.id: 1},
        )

        with patch("rsc.abc.ApiClient") as mock_client:
            mock_api = AsyncMock()
            mock_api.members_make_player_create.side_effect = ApiException(status=400, reason="Bad")
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
            mock_api.members_member_league_drop_create.side_effect = ApiException(status=400, reason="Bad")
            mock_client.return_value.__aenter__ = AsyncMock(return_value=MagicMock())
            mock_client.return_value.__aexit__ = AsyncMock(return_value=False)
            with patch("rsc.members.members.MembersApi", return_value=mock_api):
                with pytest.raises(RscException):
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
            mock_api.members_elevated_roles_list.side_effect = ApiException(status=500, reason="Error")
            mock_client.return_value.__aenter__ = AsyncMock(return_value=MagicMock())
            mock_client.return_value.__aexit__ = AsyncMock(return_value=False)
            with patch("rsc.members.members.MembersApi", return_value=mock_api):
                with pytest.raises(RscException):
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
                await mixin.create_elevated_role(
                    mock_guild, member=mock_member, executor=mock_executor, position=StaffPositions.NUMBERS
                )

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
                await mixin.create_elevated_role(
                    mock_guild, member=mock_member, executor=mock_executor, position=StaffPositions.NUMBERS
                )

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
            mock_api.members_elevated_roles_create.side_effect = ApiException(status=403, reason="Forbidden")
            mock_client.return_value.__aenter__ = AsyncMock(return_value=MagicMock())
            mock_client.return_value.__aexit__ = AsyncMock(return_value=False)
            with patch("rsc.members.members.MembersApi", return_value=mock_api):
                with pytest.raises(RscException):
                    await mixin.create_elevated_role(
                    mock_guild, member=mock_member, executor=mock_executor, position=StaffPositions.NUMBERS
                )


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
            mock_api.members_elevated_roles_destroy.side_effect = ApiException(status=404, reason="Not Found")
            mock_client.return_value.__aenter__ = AsyncMock(return_value=MagicMock())
            mock_client.return_value.__aexit__ = AsyncMock(return_value=False)
            with patch("rsc.members.members.MembersApi", return_value=mock_api):
                with pytest.raises(RscException):
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
