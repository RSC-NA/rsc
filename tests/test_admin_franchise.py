from unittest.mock import AsyncMock, MagicMock

import discord
import pytest

from rsc.admin.franchise import AdminFranchiseMixIn


def _create_mixin(**attrs):
    saved = AdminFranchiseMixIn.__abstractmethods__
    AdminFranchiseMixIn.__abstractmethods__ = frozenset()
    try:
        m = object.__new__(AdminFranchiseMixIn)
    finally:
        AdminFranchiseMixIn.__abstractmethods__ = saved
    for k, v in attrs.items():
        setattr(m, k, v)
    return m


def _agm_entry(discord_id, rsc_name="SomeAGM"):
    """A `FranchiseGM` as `FranchiseList.agms` carries one."""
    a = MagicMock()
    a.discord_id = discord_id
    a.rsc_name = rsc_name
    return a


def _guild_member(discord_id):
    m = MagicMock(spec=discord.Member)
    m.id = discord_id
    m.mention = f"<@{discord_id}>"
    m.remove_roles = AsyncMock()
    return m


def _mock_guild_with(members):
    guild = MagicMock(spec=discord.Guild)
    guild.id = 395806681994493964
    guild.get_member = MagicMock(side_effect=lambda i: members.get(i))
    return guild


def _mock_channel():
    channel = MagicMock(spec=discord.TextChannel)
    channel.set_permissions = AsyncMock()
    return channel


@pytest.fixture
def agm_role():
    return MagicMock(spec=discord.Role)


class TestClearFormerAgms:
    async def test_strips_role_and_channel_access_for_each_agm(self, agm_role):
        """`transfer_franchise` drops the AGM rows server side and the API has no
        discord side effects, so the bot owns this half of the cleanup."""
        first, second = _guild_member(111), _guild_member(222)
        guild = _mock_guild_with({111: first, 222: second})
        channel = _mock_channel()
        mixin = _create_mixin()

        cleared, unresolved = await mixin._clear_former_agms(
            guild,
            [_agm_entry(111), _agm_entry(222)],
            agm_role=agm_role,
            tchannel=channel,
            exclude=set(),
        )

        assert cleared == [first, second]
        assert unresolved == []
        first.remove_roles.assert_awaited_once_with(agm_role, reason="Franchise was transferred to a new GM")
        second.remove_roles.assert_awaited_once_with(agm_role, reason="Franchise was transferred to a new GM")
        assert channel.set_permissions.await_count == 2
        assert [c.args[0] for c in channel.set_permissions.await_args_list] == [first, second]
        assert all(c.kwargs["overwrite"] is None for c in channel.set_permissions.await_args_list)

    async def test_leaves_roster_state_alone(self, agm_role):
        """A transfer does not change roster membership, so an AGM who is also
        rostered keeps their franchise role and prefix."""
        member = _guild_member(111)
        guild = _mock_guild_with({111: member})
        mixin = _create_mixin()

        await mixin._clear_former_agms(
            guild, [_agm_entry(111)], agm_role=agm_role, tchannel=_mock_channel(), exclude=set()
        )

        # Exactly one call, carrying only the AGM role
        member.remove_roles.assert_awaited_once_with(agm_role, reason="Franchise was transferred to a new GM")
        member.edit.assert_not_called()

    async def test_excludes_the_incoming_gm(self, agm_role):
        """The new GM may have been an AGM of this same franchise. The transfer
        already strips their AGM role and grants them the GM overwrite, so
        clearing them here would undo that."""
        new_gm, other = _guild_member(111), _guild_member(222)
        guild = _mock_guild_with({111: new_gm, 222: other})
        channel = _mock_channel()
        mixin = _create_mixin()

        cleared, _ = await mixin._clear_former_agms(
            guild,
            [_agm_entry(111), _agm_entry(222)],
            agm_role=agm_role,
            tchannel=channel,
            exclude={111},
        )

        assert cleared == [other]
        new_gm.remove_roles.assert_not_awaited()
        assert [c.args[0] for c in channel.set_permissions.await_args_list] == [other]

    async def test_reports_agms_who_left_the_server(self, agm_role):
        """Their API record is gone either way. Reporting them lets the operator
        confirm rather than silently assuming the cleanup was complete."""
        present = _guild_member(111)
        guild = _mock_guild_with({111: present})
        mixin = _create_mixin()
        gone = _agm_entry(999, rsc_name="Departed")

        cleared, unresolved = await mixin._clear_former_agms(
            guild,
            [_agm_entry(111), gone],
            agm_role=agm_role,
            tchannel=_mock_channel(),
            exclude=set(),
        )

        assert cleared == [present]
        assert unresolved == [gone]

    async def test_removes_roles_even_without_a_transaction_channel(self, agm_role):
        """A missing channel must not strand them holding the AGM role."""
        member = _guild_member(111)
        guild = _mock_guild_with({111: member})
        mixin = _create_mixin()

        cleared, _ = await mixin._clear_former_agms(
            guild, [_agm_entry(111)], agm_role=agm_role, tchannel=None, exclude=set()
        )

        assert cleared == [member]
        member.remove_roles.assert_awaited_once()

    async def test_no_agms_is_a_no_op(self, agm_role):
        guild = _mock_guild_with({})
        channel = _mock_channel()
        mixin = _create_mixin()

        assert await mixin._clear_former_agms(guild, [], agm_role=agm_role, tchannel=channel, exclude=set()) == ([], [])
        channel.set_permissions.assert_not_awaited()
