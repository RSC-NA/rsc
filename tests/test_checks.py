from unittest.mock import AsyncMock, MagicMock, patch

import discord
import pytest
from rscapi.exceptions import ApiException

from rsc.checks import elevated_role_required
from rsc.enums import StaffPositions
from rsc.exceptions import RscException
from rsc.members.members import ELEVATED_ROLE_TTL, MemberMixIn

TRACKER_POSITIONS = (
    StaffPositions.ADMIN,
    StaffPositions.NUMBERS,
    StaffPositions.NUMBERS_HEAD,
)


def _create_mixin(**attrs):
    saved = MemberMixIn.__abstractmethods__
    MemberMixIn.__abstractmethods__ = frozenset()
    try:
        m = object.__new__(MemberMixIn)
    finally:
        MemberMixIn.__abstractmethods__ = saved
    m._elevated_role_cache = {}
    for k, v in attrs.items():
        setattr(m, k, v)
    return m


def _mock_interaction(guild, *, manage_guild: bool, user_id: int = 1234):
    user = MagicMock(spec=discord.Member)
    user.id = user_id
    user.guild_permissions = MagicMock()
    user.guild_permissions.manage_guild = manage_guild

    interaction = MagicMock(spec=discord.Interaction)
    interaction.guild = guild
    interaction.user = user
    interaction.response = MagicMock()
    interaction.response.send_message = AsyncMock()
    return interaction


def _guarded():
    """A command body wrapped by the check, plus a flag recording invocation."""
    called = {"hit": False}

    @elevated_role_required(*TRACKER_POSITIONS)
    async def cmd(cls, interaction):
        called["hit"] = True
        return "ran"

    return cmd, called


class TestElevatedRoleRequired:
    async def test_manage_guild_bypasses_api(self, mock_guild):
        cmd, called = _guarded()
        mixin = _create_mixin()
        mixin.elevated_positions = AsyncMock()
        interaction = _mock_interaction(mock_guild, manage_guild=True)

        result = await cmd(mixin, interaction)

        assert result == "ran"
        assert called["hit"]
        # Guild managers must never trigger an elevated role lookup
        mixin.elevated_positions.assert_not_awaited()

    @pytest.mark.parametrize("api_label", ["Numbers", "Numbers Head", "Admin"])
    async def test_committee_member_passes_end_to_end(self, mock_guild, api_label, monkeypatch):
        """Wire the real API response shape all the way through the gate.

        This is the regression guard for the label-vs-code mismatch: the API
        returns "Numbers", the allowlist holds "NUMS". Mocking `elevated_positions`
        hides that, so this test drives the real normalization path.
        """
        cmd, called = _guarded()
        role = MagicMock()
        role.position = api_label
        mixin = _create_mixin(_api_conf={mock_guild.id: MagicMock()}, _league={mock_guild.id: 1})

        mock_api = AsyncMock()
        mock_api.members_elevated_roles_list.return_value = [role]
        interaction = _mock_interaction(mock_guild, manage_guild=False)

        with patch("rsc.abc.ApiClient") as mock_client:
            mock_client.return_value.__aenter__ = AsyncMock(return_value=MagicMock())
            mock_client.return_value.__aexit__ = AsyncMock(return_value=False)
            with patch("rsc.members.members.MembersApi", return_value=mock_api):
                result = await cmd(mixin, interaction)

        assert result == "ran", f"Committee member with API position {api_label!r} was denied"
        assert called["hit"]
        interaction.response.send_message.assert_not_awaited()

    @pytest.mark.parametrize("position", ["NUMS", "NH", "ADM"])
    async def test_allowed_positions_pass(self, mock_guild, position):
        cmd, called = _guarded()
        mixin = _create_mixin()
        mixin.elevated_positions = AsyncMock(return_value=frozenset({position}))
        interaction = _mock_interaction(mock_guild, manage_guild=False)

        result = await cmd(mixin, interaction)

        assert result == "ran"
        assert called["hit"]
        interaction.response.send_message.assert_not_awaited()

    async def test_no_elevated_roles_denied(self, mock_guild):
        cmd, called = _guarded()
        mixin = _create_mixin()
        mixin.elevated_positions = AsyncMock(return_value=frozenset())
        interaction = _mock_interaction(mock_guild, manage_guild=False)

        await cmd(mixin, interaction)

        assert not called["hit"]
        interaction.response.send_message.assert_awaited_once()
        assert interaction.response.send_message.await_args.kwargs["ephemeral"] is True

    async def test_unrelated_elevated_role_denied(self, mock_guild):
        cmd, called = _guarded()
        mixin = _create_mixin()
        mixin.elevated_positions = AsyncMock(return_value=frozenset({"MEDIA", "STATS"}))
        interaction = _mock_interaction(mock_guild, manage_guild=False)

        await cmd(mixin, interaction)

        assert not called["hit"]
        interaction.response.send_message.assert_awaited_once()

    async def test_api_failure_fails_closed(self, mock_guild):
        cmd, called = _guarded()
        mixin = _create_mixin()
        mixin.elevated_positions = AsyncMock(side_effect=RscException(response=ApiException(status=500, reason="Error")))
        interaction = _mock_interaction(mock_guild, manage_guild=False)

        await cmd(mixin, interaction)

        assert not called["hit"]
        interaction.response.send_message.assert_awaited_once()

    async def test_api_failure_still_allows_guild_manager(self, mock_guild):
        cmd, called = _guarded()
        mixin = _create_mixin()
        mixin.elevated_positions = AsyncMock(side_effect=RscException(response=ApiException(status=500, reason="Error")))
        interaction = _mock_interaction(mock_guild, manage_guild=True)

        result = await cmd(mixin, interaction)

        assert result == "ran"
        assert called["hit"]

    async def test_no_guild_is_noop(self):
        cmd, called = _guarded()
        mixin = _create_mixin()
        interaction = _mock_interaction(None, manage_guild=False)

        assert await cmd(mixin, interaction) is None
        assert not called["hit"]


class TestElevatedPositionsCache:
    def _patched_api(self, roles):
        """Patch ApiClient/MembersApi so members_elevated_roles_list returns `roles`."""
        mock_api = AsyncMock()
        mock_api.members_elevated_roles_list.return_value = roles
        client = patch("rsc.abc.ApiClient")
        return client, mock_api

    async def test_caches_within_ttl(self, mock_guild):
        mixin = _create_mixin(_api_conf={mock_guild.id: MagicMock()}, _league={mock_guild.id: 1})
        role = MagicMock()
        role.position = "Numbers"  # API returns display labels, not codes
        client, mock_api = self._patched_api([role])

        with client as mock_client:
            mock_client.return_value.__aenter__ = AsyncMock(return_value=MagicMock())
            mock_client.return_value.__aexit__ = AsyncMock(return_value=False)
            with patch("rsc.members.members.MembersApi", return_value=mock_api):
                first = await mixin.elevated_positions(mock_guild, 1234)
                second = await mixin.elevated_positions(mock_guild, 1234)

        assert first == frozenset({"NUMS"})
        assert second == frozenset({"NUMS"})
        # Second call must be served from cache
        assert mock_api.members_elevated_roles_list.await_count == 1

    async def test_refetches_after_ttl_expiry(self, mock_guild):
        mixin = _create_mixin(_api_conf={mock_guild.id: MagicMock()}, _league={mock_guild.id: 1})
        role = MagicMock()
        role.position = "Numbers"
        client, mock_api = self._patched_api([role])

        with client as mock_client:
            mock_client.return_value.__aenter__ = AsyncMock(return_value=MagicMock())
            mock_client.return_value.__aexit__ = AsyncMock(return_value=False)
            with patch("rsc.members.members.MembersApi", return_value=mock_api):
                await mixin.elevated_positions(mock_guild, 1234)
                # Force the entry to look stale
                expiry, positions = mixin._elevated_role_cache[mock_guild.id][1234]
                mixin._elevated_role_cache[mock_guild.id][1234] = (expiry - ELEVATED_ROLE_TTL - 1, positions)
                await mixin.elevated_positions(mock_guild, 1234)

        assert mock_api.members_elevated_roles_list.await_count == 2

    async def test_drops_null_positions(self, mock_guild):
        """GM/AGM rows carry position=None and must not blow up normalization."""
        mixin = _create_mixin(_api_conf={mock_guild.id: MagicMock()}, _league={mock_guild.id: 1})
        good, bad = MagicMock(), MagicMock()
        good.position = "Numbers Head"
        bad.position = None
        client, mock_api = self._patched_api([good, bad])

        with client as mock_client:
            mock_client.return_value.__aenter__ = AsyncMock(return_value=MagicMock())
            mock_client.return_value.__aexit__ = AsyncMock(return_value=False)
            with patch("rsc.members.members.MembersApi", return_value=mock_api):
                result = await mixin.elevated_positions(mock_guild, 1234)

        assert result == frozenset({"NH"})

    @pytest.mark.parametrize(
        ("api_value", "expected"),
        [
            # The API returns labels in responses but accepts codes as input.
            # Both must normalize to the code, or the permission gate matches nothing.
            ("Numbers", "NUMS"),
            ("NUMS", "NUMS"),
            ("Admin", "ADM"),
            ("ADM", "ADM"),
            ("Numbers Head", "NH"),
            ("Transactions Head", "TMH"),
            ("MMR Puller", "MMR"),
            ("Franchise Manager", "FRAN"),
            ("numbers", "NUMS"),  # case-insensitive
        ],
    )
    async def test_normalizes_api_position_to_code(self, mock_guild, api_value, expected):
        mixin = _create_mixin(_api_conf={mock_guild.id: MagicMock()}, _league={mock_guild.id: 1})
        role = MagicMock()
        role.position = api_value
        client, mock_api = self._patched_api([role])

        with client as mock_client:
            mock_client.return_value.__aenter__ = AsyncMock(return_value=MagicMock())
            mock_client.return_value.__aexit__ = AsyncMock(return_value=False)
            with patch("rsc.members.members.MembersApi", return_value=mock_api):
                result = await mixin.elevated_positions(mock_guild, 1234)

        assert result == frozenset({expected})

    async def test_unknown_position_dropped(self, mock_guild):
        mixin = _create_mixin(_api_conf={mock_guild.id: MagicMock()}, _league={mock_guild.id: 1})
        role = MagicMock()
        role.position = "Chief Vibes Officer"
        client, mock_api = self._patched_api([role])

        with client as mock_client:
            mock_client.return_value.__aenter__ = AsyncMock(return_value=MagicMock())
            mock_client.return_value.__aexit__ = AsyncMock(return_value=False)
            with patch("rsc.members.members.MembersApi", return_value=mock_api):
                result = await mixin.elevated_positions(mock_guild, 1234)

        assert result == frozenset()

    async def test_cache_is_per_member(self, mock_guild):
        mixin = _create_mixin(_api_conf={mock_guild.id: MagicMock()}, _league={mock_guild.id: 1})
        role = MagicMock()
        role.position = "Numbers"
        client, mock_api = self._patched_api([role])

        with client as mock_client:
            mock_client.return_value.__aenter__ = AsyncMock(return_value=MagicMock())
            mock_client.return_value.__aexit__ = AsyncMock(return_value=False)
            with patch("rsc.members.members.MembersApi", return_value=mock_api):
                await mixin.elevated_positions(mock_guild, 1234)
                await mixin.elevated_positions(mock_guild, 5678)

        assert mock_api.members_elevated_roles_list.await_count == 2

    async def test_scopes_query_to_guild_league(self, mock_guild):
        mixin = _create_mixin(_api_conf={mock_guild.id: MagicMock()}, _league={mock_guild.id: 42})
        client, mock_api = self._patched_api([])

        with client as mock_client:
            mock_client.return_value.__aenter__ = AsyncMock(return_value=MagicMock())
            mock_client.return_value.__aexit__ = AsyncMock(return_value=False)
            with patch("rsc.members.members.MembersApi", return_value=mock_api):
                await mixin.elevated_positions(mock_guild, 1234)

        mock_api.members_elevated_roles_list.assert_awaited_once_with(id=1234, league=42, position=None)

    async def test_api_exception_becomes_rsc_exception(self, mock_guild):
        mixin = _create_mixin(_api_conf={mock_guild.id: MagicMock()}, _league={mock_guild.id: 1})
        mock_api = AsyncMock()
        mock_api.members_elevated_roles_list.side_effect = ApiException(status=500, reason="Error")

        with patch("rsc.abc.ApiClient") as mock_client:
            mock_client.return_value.__aenter__ = AsyncMock(return_value=MagicMock())
            mock_client.return_value.__aexit__ = AsyncMock(return_value=False)
            with patch("rsc.members.members.MembersApi", return_value=mock_api):
                with pytest.raises(RscException):
                    await mixin.elevated_positions(mock_guild, 1234)


class TestTrackerCommandsGated:
    async def test_every_subcommand_is_gated(self):
        """All /trackers subcommands must go through the elevated role check."""
        from rsc.trackers.trackers import TrackerMixIn

        cmds = TrackerMixIn._trackers.commands
        assert len(cmds) == 10

        ungated = [c.name for c in cmds if not hasattr(c.callback, "__rsc_elevated_positions__")]
        assert not ungated, f"Ungated /trackers subcommands: {sorted(ungated)}"

        # Every one of them must accept exactly the numbers committee + admin roles
        expected = frozenset({"ADM", "NUMS", "NH"})
        for c in cmds:
            assert c.callback.__rsc_elevated_positions__ == expected, f"/trackers {c.name} gated on unexpected positions"

    async def test_signatures_survive_the_decorator(self):
        """`@wraps` must preserve parameters so discord.py builds the command correctly."""
        from rsc.trackers.trackers import TrackerMixIn

        by_name = {c.name: c for c in TrackerMixIn._trackers.commands}

        assert [p.name for p in by_name["add"].parameters] == ["player", "tracker"]
        assert [p.name for p in by_name["link"].parameters] == ["tracker_id", "player"]
        assert [p.name for p in by_name["merge"].parameters] == ["source", "dest"]
        assert by_name["stats"].parameters == []

        # Optionality must be preserved too
        old = {p.name: p.required for p in by_name["old"].parameters}
        assert old == {"status": False, "days": False}
