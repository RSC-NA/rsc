from unittest.mock import AsyncMock, MagicMock

import discord
import pytest
from rscapi.exceptions import ApiException

from rsc.admin.members import AdminMembersMixIn
from rsc.enums import StaffPositions
from rsc.exceptions import RscException


def _create_mixin(**attrs):
    saved = AdminMembersMixIn.__abstractmethods__
    AdminMembersMixIn.__abstractmethods__ = frozenset()
    try:
        m = object.__new__(AdminMembersMixIn)
    finally:
        AdminMembersMixIn.__abstractmethods__ = saved
    for k, v in attrs.items():
        setattr(m, k, v)
    return m


def _mock_interaction(guild):
    interaction = MagicMock(spec=discord.Interaction)
    interaction.guild = guild
    interaction.response = MagicMock()
    interaction.response.defer = AsyncMock()
    interaction.followup = MagicMock()
    interaction.followup.send = AsyncMock()
    return interaction


def _role(position, *, id=1, arbiter=False, project_role=""):
    r = MagicMock()
    r.id = id
    r.position = position
    r.arbiter = arbiter
    r.project_role = project_role
    r.league = MagicMock()
    r.league.name = "RSC 3v3"
    return r


def _sent_embed(interaction):
    return interaction.followup.send.await_args.kwargs["embed"]


# The decorator turns the method into an app command, so reach through to the callback
CMD = AdminMembersMixIn._member_elevated_roles_cmd.callback


class TestAdminElevatedRolesCommand:
    async def test_registered_under_admin_members(self):
        cmds = {c.name: c for c in AdminMembersMixIn._members.commands}
        assert "elevatedroles" in cmds
        assert [p.name for p in cmds["elevatedroles"].parameters] == ["member"]

    async def test_displays_each_role_as_a_field(self, mock_guild, mock_member):
        roles = [
            _role("NUMS", id=7, project_role="Numbers Cruncher"),
            _role("ADM", id=9, arbiter=True),
        ]
        mixin = _create_mixin(member_elevated_roles=AsyncMock(return_value=roles))
        interaction = _mock_interaction(mock_guild)

        await CMD(mixin, interaction, mock_member)

        embed = _sent_embed(interaction)
        assert embed.title == "Elevated Roles"
        assert "RSC 3v3" in embed.description
        assert [f.name for f in embed.fields] == ["Numbers", "Admin"]

        numbers, admin = embed.fields
        assert "**Role ID:** 7" in numbers.value
        assert "**Project Role:** Numbers Cruncher" in numbers.value
        assert "**Arbiter:** No" in numbers.value
        assert "**Arbiter:** Yes" in admin.value
        # GM/AGM are FranchiseStaff now and must not be reported here
        assert "GM" not in numbers.value

    async def test_no_roles_reports_empty(self, mock_guild, mock_member):
        mixin = _create_mixin(member_elevated_roles=AsyncMock(return_value=[]))
        interaction = _mock_interaction(mock_guild)

        await CMD(mixin, interaction, mock_member)

        embed = _sent_embed(interaction)
        assert "no elevated roles" in embed.description
        assert embed.fields == []

    async def test_unknown_position_falls_back_to_raw_value(self, mock_guild, mock_member):
        """A position the local enum has not caught up with must not crash the command."""
        mixin = _create_mixin(member_elevated_roles=AsyncMock(return_value=[_role("BOGUS")]))
        interaction = _mock_interaction(mock_guild)

        await CMD(mixin, interaction, mock_member)

        embed = _sent_embed(interaction)
        assert embed.fields[0].name == "BOGUS (unrecognized)"

    async def test_null_position_is_handled(self, mock_guild, mock_member):
        mixin = _create_mixin(member_elevated_roles=AsyncMock(return_value=[_role(None)]))
        interaction = _mock_interaction(mock_guild)

        await CMD(mixin, interaction, mock_member)

        assert _sent_embed(interaction).fields[0].name == "Unknown"

    async def test_api_error_returns_error_embed(self, mock_guild, mock_member):
        exc = RscException(response=ApiException(status=500, reason="Error"))
        mixin = _create_mixin(member_elevated_roles=AsyncMock(side_effect=exc))
        interaction = _mock_interaction(mock_guild)

        await CMD(mixin, interaction, mock_member)

        assert _sent_embed(interaction).title == "API Error"

    async def test_bypasses_permission_cache(self, mock_guild, mock_member):
        """Must hit the API directly so admins always see current truth."""
        mixin = _create_mixin(member_elevated_roles=AsyncMock(return_value=[]))
        mixin.elevated_positions = AsyncMock()
        interaction = _mock_interaction(mock_guild)

        await CMD(mixin, interaction, mock_member)

        mixin.member_elevated_roles.assert_awaited_once_with(mock_guild, mock_member.id)
        mixin.elevated_positions.assert_not_awaited()

    async def test_no_guild_is_noop(self, mock_member):
        mixin = _create_mixin(member_elevated_roles=AsyncMock())
        interaction = _mock_interaction(None)

        assert await CMD(mixin, interaction, mock_member) is None
        mixin.member_elevated_roles.assert_not_awaited()


class TestStaffPositionsFullName:
    @pytest.mark.parametrize(
        ("value", "expected"),
        [
            ("TM", "Transactions"),
            ("TMH", "Transactions Head"),
            ("FRAN", "Franchise Manager"),
            ("NH", "Numbers Head"),
            ("NUMS", "Numbers"),
            ("MMR", "MMR Puller"),
            ("ADM", "Admin"),
        ],
    )
    def test_full_name_matches_api_description(self, value, expected):
        assert StaffPositions(value).full_name == expected

    def test_every_position_has_a_readable_name(self):
        """No position may render as a bare enum member name (e.g. 'NUMBERS_HEAD')."""
        for p in StaffPositions:
            assert p.full_name, f"{p.name} has no full_name"
            assert "_" not in p.full_name, f"{p.name} renders unformatted: {p.full_name}"
