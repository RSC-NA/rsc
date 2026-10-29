from unittest.mock import AsyncMock, MagicMock

import discord
import pytest

from rscapi.models.franchise_rebrand import FranchiseRebrand
from rscapi.models.team_rebrand import TeamRebrand

from rsc import const
from rsc.admin.franchise import AdminFranchiseMixIn, rebrand_length_errors
from rsc.exceptions import RscException

from .utils import command_callback


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
    guild.get_member = MagicMock(side_effect=members.get)
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

        await mixin._clear_former_agms(guild, [_agm_entry(111)], agm_role=agm_role, tchannel=_mock_channel(), exclude=set())

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

        cleared, _ = await mixin._clear_former_agms(guild, [_agm_entry(111)], agm_role=agm_role, tchannel=None, exclude=set())

        assert cleared == [member]
        member.remove_roles.assert_awaited_once()

    async def test_no_agms_is_a_no_op(self, agm_role):
        guild = _mock_guild_with({})
        channel = _mock_channel()
        mixin = _create_mixin()

        assert await mixin._clear_former_agms(guild, [], agm_role=agm_role, tchannel=channel, exclude=set()) == ([], [])
        channel.set_permissions.assert_not_awaited()


class TestRebrandLengthErrors:
    """`/admin franchise rebrand` must reject over-long fields itself.

    The generated models validate these with pydantic, which raises while the
    request is still being assembled. No handler exists for a ValidationError on
    an app command, and by that point the command has already swapped in its
    loading embed -- so the interaction would simply hang.
    """

    def test_accepts_values_at_the_limit(self):
        prefix = "A" * const.FRANCHISE_PREFIX_MAX_LENGTH
        teams = ["B" * const.TEAM_NAME_MAX_LENGTH, "Short"]
        assert rebrand_length_errors(prefix, teams) == []

    def test_flags_an_over_long_team_name(self):
        errors = rebrand_length_errors("ABC", ["A" * (const.TEAM_NAME_MAX_LENGTH + 1)])
        assert len(errors) == 1
        assert "Team name" in errors[0]

    def test_flags_an_over_long_prefix(self):
        errors = rebrand_length_errors("A" * (const.FRANCHISE_PREFIX_MAX_LENGTH + 1), ["Fine"])
        assert len(errors) == 1
        assert "Prefix" in errors[0]

    def test_reports_every_offender_at_once(self):
        """One round trip through the modal per bad name would be miserable."""
        long_name = "A" * (const.TEAM_NAME_MAX_LENGTH + 1)
        errors = rebrand_length_errors("TOOLONG", [long_name, "Fine", long_name])
        assert len(errors) == 3

    def test_empty_team_list_is_not_an_error(self):
        assert rebrand_length_errors("ABC", []) == []


class TestRebrandLimitsMatchTheApi:
    """The constants are a local mirror of the client models. If rscapi tightens
    or relaxes a limit, the guard above silently stops matching the server."""

    @staticmethod
    def _max_length(model, field):
        return next(m.max_length for m in model.model_fields[field].metadata if hasattr(m, "max_length"))

    def test_team_name_limit_matches_team_rebrand(self):
        assert self._max_length(TeamRebrand, "name") == const.TEAM_NAME_MAX_LENGTH

    def test_prefix_limit_matches_franchise_rebrand(self):
        assert self._max_length(FranchiseRebrand, "prefix") == const.FRANCHISE_PREFIX_MAX_LENGTH


class TestTeamCacheUpdates:
    """`/admin franchise addteam` and `delteam` patch the autocomplete cache in
    place. Deleting a team appended the name instead of removing it, so every
    deletion left a second copy of the team in autocomplete."""

    GUILD_ID = 395806681994493964

    @pytest.fixture
    def guild(self):
        guild = MagicMock(spec=discord.Guild)
        guild.id = self.GUILD_ID
        return guild

    @pytest.fixture
    def interaction(self, guild):
        interaction = MagicMock(spec=discord.Interaction)
        interaction.guild = guild
        interaction.response = MagicMock()
        interaction.response.defer = AsyncMock()
        interaction.followup = MagicMock()
        interaction.followup.send = AsyncMock()
        return interaction

    def _team(self, id=1, name="Dik-diks", tier="Premier", franchise="Dik-Diks"):
        t = MagicMock()
        t.id = id
        t.name = name
        t.tier = MagicMock()
        t.tier.name = tier
        t.franchise = MagicMock()
        t.franchise.name = franchise
        return t

    async def test_delete_removes_the_team_from_the_cache(self, interaction, guild):
        fteam = self._team()
        mixin = _create_mixin(
            _team_cache={guild.id: ["Alpha", "Dik-diks"]},
            teams=AsyncMock(return_value=[fteam]),
            delete_team=AsyncMock(),
        )

        await command_callback(AdminFranchiseMixIn._franchise_rmteam_cmd)(mixin, interaction, "Dik-Diks", "premier", "Dik-diks")

        mixin.delete_team.assert_awaited_once_with(guild, team_id=fteam.id)
        assert mixin._team_cache[guild.id] == ["Alpha"]

    async def test_delete_uses_the_name_the_api_returned(self, interaction, guild):
        """The team argument is free text unless it came from autocomplete."""
        mixin = _create_mixin(
            _team_cache={guild.id: ["Dik-diks"]},
            teams=AsyncMock(return_value=[self._team(name="Dik-diks")]),
            delete_team=AsyncMock(),
        )

        await command_callback(AdminFranchiseMixIn._franchise_rmteam_cmd)(mixin, interaction, "Dik-Diks", "premier", "dik")

        assert mixin._team_cache[guild.id] == []

    async def test_delete_leaves_the_cache_alone_when_the_api_fails(self, interaction, guild):
        mixin = _create_mixin(
            _team_cache={guild.id: ["Dik-diks"]},
            teams=AsyncMock(return_value=[self._team()]),
            delete_team=AsyncMock(side_effect=RscException(message="boom")),
        )

        await command_callback(AdminFranchiseMixIn._franchise_rmteam_cmd)(mixin, interaction, "Dik-Diks", "premier", "Dik-diks")

        assert mixin._team_cache[guild.id] == ["Dik-diks"]

    async def test_add_caches_the_name_the_api_stored(self, interaction, guild):
        """The typed name may differ from the stored one, which would leave two
        entries for the same team."""
        mixin = _create_mixin(
            _team_cache={guild.id: ["Alpha"]},
            create_team=AsyncMock(return_value=self._team(name="Dik-diks")),
        )

        await command_callback(AdminFranchiseMixIn._franchise_addteam_cmd)(mixin, interaction, "Dik-Diks", "premier", "DIK-DIKS")

        assert mixin._team_cache[guild.id] == ["Alpha", "Dik-diks"]

    async def test_add_does_not_repeat_a_cached_team(self, interaction, guild):
        mixin = _create_mixin(
            _team_cache={guild.id: ["Dik-diks"]},
            create_team=AsyncMock(return_value=self._team(name="Dik-diks")),
        )

        await command_callback(AdminFranchiseMixIn._franchise_addteam_cmd)(mixin, interaction, "Dik-Diks", "premier", "Dik-diks")

        assert mixin._team_cache[guild.id] == ["Dik-diks"]


class TestFranchiseDelete:
    async def test_says_the_api_cannot_delete_franchises(self):
        interaction = MagicMock(spec=discord.Interaction)
        interaction.response.send_message = AsyncMock()
        mixin = _create_mixin(franchises=AsyncMock())

        await command_callback(AdminFranchiseMixIn._franchise_delete)(mixin, interaction, franchise="Hex Systems")

        assert interaction.response.send_message.await_args is not None
        kwargs = interaction.response.send_message.await_args.kwargs
        assert kwargs["embed"].title == "Not Implemented"
        assert kwargs["embed"].description == "Deleting a franchise has not been implemented in the RSC API."
        assert kwargs["ephemeral"] is True
        # Nothing is looked up or confirmed for a command that can't do anything
        mixin.franchises.assert_not_awaited()

    async def test_runs_the_kept_flow_once_supported(self, monkeypatch):
        monkeypatch.setattr("rsc.admin.franchise.FRANCHISE_DELETE_SUPPORTED", True)
        interaction = MagicMock(spec=discord.Interaction)
        mixin = _create_mixin(_process_franchise_delete=AsyncMock())

        await command_callback(AdminFranchiseMixIn._franchise_delete)(mixin, interaction, franchise="Hex Systems")

        mixin._process_franchise_delete.assert_awaited_once_with(interaction, "Hex Systems")


class TestFranchiseCreate:
    @pytest.fixture
    def gm(self):
        gm = _guild_member(111)
        gm.add_roles = AsyncMock()
        gm.edit = AsyncMock()
        gm.display_name = "Nick"
        return gm

    @pytest.fixture
    def gm_role(self):
        role = MagicMock(spec=discord.Role)
        role.name = const.GM_ROLE
        return role

    def _guild(self, *roles):
        guild = MagicMock(spec=discord.Guild)
        guild.id = 395806681994493964
        guild.roles = list(roles)
        guild.create_role = AsyncMock()
        return guild

    def _interaction(self, guild):
        interaction = MagicMock(spec=discord.Interaction)
        interaction.guild = guild
        interaction.edit_original_response = AsyncMock()
        return interaction

    async def run(self, guild, gm, monkeypatch):
        view = MagicMock()
        view.prompt = AsyncMock()
        view.wait = AsyncMock()
        view.result = True
        monkeypatch.setattr("rsc.admin.franchise.CreateFranchiseView", MagicMock(return_value=view))
        monkeypatch.setattr("rsc.admin.franchise.utils.remove_prefix", AsyncMock(return_value="Nick"))
        franchise = MagicMock()
        franchise.gm.rsc_name = "Nick"
        mixin = _create_mixin(create_franchise=AsyncMock(return_value=franchise))
        interaction = self._interaction(guild)

        await command_callback(AdminFranchiseMixIn._franchise_create)(mixin, interaction, name="Hex Systems", prefix="HX", gm=gm)
        return interaction

    async def test_reuses_an_existing_franchise_role(self, gm, gm_role, monkeypatch):
        frole = MagicMock(spec=discord.Role)
        frole.name = "Hex Systems (Nick)"
        guild = self._guild(gm_role, frole)

        interaction = await self.run(guild, gm, monkeypatch)

        guild.create_role.assert_not_awaited()
        gm.add_roles.assert_awaited_once_with(frole, gm_role)
        assert interaction.edit_original_response.await_args is not None
        assert interaction.edit_original_response.await_args.kwargs["embed"].description == "Franchise has been created."

    async def test_creates_the_franchise_role_when_missing(self, gm, gm_role, monkeypatch):
        guild = self._guild(gm_role)
        new_role = MagicMock(spec=discord.Role)
        guild.create_role.return_value = new_role

        await self.run(guild, gm, monkeypatch)

        guild.create_role.assert_awaited_once()
        gm.add_roles.assert_awaited_once_with(new_role, gm_role)
