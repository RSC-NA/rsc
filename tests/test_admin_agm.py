from unittest.mock import AsyncMock, MagicMock, patch

import discord
import pytest
from rscapi.exceptions import ApiException

from rsc.admin.agm import AdminAGMMixIn
from rsc.enums import Status
from rsc.exceptions import RscException

FRANCHISE = "The Ocean"
FRANCHISE_ID = 7
OTHER_FRANCHISE = "The Desert"
OTHER_FRANCHISE_ID = 9


def _create_mixin(**attrs):
    saved = AdminAGMMixIn.__abstractmethods__
    AdminAGMMixIn.__abstractmethods__ = frozenset()
    try:
        m = object.__new__(AdminAGMMixIn)
    finally:
        AdminAGMMixIn.__abstractmethods__ = saved
    for k, v in attrs.items():
        setattr(m, k, v)
    return m


def _mock_interaction(guild):
    interaction = MagicMock(spec=discord.Interaction)
    interaction.guild = guild
    interaction.user = MagicMock(spec=discord.Member)
    interaction.user.id = 222222222
    interaction.response = MagicMock()
    interaction.response.defer = AsyncMock()
    interaction.followup = MagicMock()
    interaction.followup.send = AsyncMock()
    return interaction


def _mock_agm():
    agm = MagicMock(spec=discord.Member)
    agm.id = 138778232802508801
    agm.mention = "<@138778232802508801>"
    agm.display_name = "someagm"
    agm.roles = []
    agm.add_roles = AsyncMock()
    agm.remove_roles = AsyncMock()
    agm.edit = AsyncMock()
    return agm


def _franchise(id=FRANCHISE_ID, name=FRANCHISE):
    """A `FranchiseList` as `franchises_agm_of` returns it.

    `name` cannot go through the MagicMock constructor -- it configures the mock
    rather than setting the attribute.
    """
    f = MagicMock()
    f.id = id
    f.name = name
    return f


def _mock_channel():
    channel = MagicMock(spec=discord.TextChannel)
    channel.mention = "#the-ocean-transactions"
    channel.send = AsyncMock()
    channel.set_permissions = AsyncMock()
    return channel


def _base_mixin(guild, channel, **overrides):
    """A mixin with every collaborator of the AGM commands stubbed out."""
    attrs = {
        "players": AsyncMock(return_value=[]),
        "tiers": AsyncMock(return_value=[]),
        "_get_agm_message": AsyncMock(return_value="Welcome aboard!"),
        "_get_welcome_roles": AsyncMock(return_value=[]),
        "get_franchise_transaction_channel": AsyncMock(return_value=channel),
        "fetch_franchise": AsyncMock(return_value=MagicMock(id=FRANCHISE_ID, prefix="OCE")),
        "franchises_agm_of": AsyncMock(return_value=[]),
        "add_agm": AsyncMock(),
        "remove_agm": AsyncMock(),
    }
    attrs.update(overrides)
    return _create_mixin(**attrs)


@pytest.fixture
def agm_sync():
    """`/admin agm remove` hands the discord cleanup to the role sync helper.

    Patched out so these tests stay about the command's API behaviour; the
    helper itself is covered in `test_transaction_roles.py`.
    """
    with patch("rsc.admin.agm.update_league_player_discord", new=AsyncMock()) as mock:
        yield mock


def _patch_utils():
    """Patch the discord-side helpers so only API behaviour is under test."""
    utils = patch("rsc.admin.agm.utils")
    mock = utils.start()
    mock.get_agm_role = AsyncMock(return_value=MagicMock(spec=discord.Role))
    mock.get_league_role = AsyncMock(return_value=MagicMock(spec=discord.Role))
    mock.franchise_role_from_name = AsyncMock(return_value=MagicMock(spec=discord.Role))
    mock.franchise_role_from_disord_member = AsyncMock(return_value=None)
    mock.format_discord_prefix = AsyncMock(return_value="OCE | someagm")
    return utils


@pytest.fixture
def agm_utils():
    patcher = _patch_utils()
    yield patcher
    patcher.stop()


def _sent_embed(interaction):
    return interaction.followup.send.await_args.kwargs["embed"]


# The decorator turns the method into an app command, so reach through to the callback
CMD_ADD = AdminAGMMixIn._franchise_promote_agm_cmd.callback
CMD_REMOVE = AdminAGMMixIn._franchise_remove_agm_cmd.callback


class TestAgmCommandRegistration:
    def test_registered_under_admin_agm(self):
        cmds = {c.name: c for c in AdminAGMMixIn._agm.commands}
        assert "add" in cmds
        assert "remove" in cmds
        assert [p.name for p in cmds["add"].parameters] == ["franchise", "agm"]
        assert [p.name for p in cmds["remove"].parameters] == ["franchise", "agm"]


class TestAgmAddCommand:
    async def test_adds_agm_to_franchise(self, mock_guild, agm_utils):
        channel = _mock_channel()
        mixin = _base_mixin(mock_guild, channel)
        interaction = _mock_interaction(mock_guild)
        agm = _mock_agm()

        await CMD_ADD(mixin, interaction, FRANCHISE, agm)

        mixin.add_agm.assert_awaited_once_with(mock_guild, FRANCHISE_ID, agm=agm, executor=interaction.user)
        agm.add_roles.assert_awaited_once()
        assert _sent_embed(interaction).title == "AGM Promoted"

    async def test_api_failure_aborts_before_any_discord_change(self, mock_guild, agm_utils):
        """The API call sits after every read-only check and before the first
        role mutation, so a failure leaves the member untouched."""
        channel = _mock_channel()
        mixin = _base_mixin(
            mock_guild,
            channel,
            add_agm=AsyncMock(side_effect=RscException(response=ApiException(status=403, reason="Forbidden"))),
        )
        interaction = _mock_interaction(mock_guild)
        agm = _mock_agm()

        await CMD_ADD(mixin, interaction, FRANCHISE, agm)

        agm.add_roles.assert_not_awaited()
        agm.remove_roles.assert_not_awaited()
        agm.edit.assert_not_awaited()
        channel.set_permissions.assert_not_awaited()
        channel.send.assert_not_awaited()
        assert _sent_embed(interaction).title == "API Error"

    async def test_executor_without_api_admin_surfaces_the_403(self, mock_guild, agm_utils):
        """`executor` must hold Admin in the franchise's league. The command is
        gated on manage_guild alone, so a guild admin lacking the API role now
        gets a 403 and must not have Discord changed underneath them."""
        channel = _mock_channel()
        mixin = _base_mixin(
            mock_guild,
            channel,
            add_agm=AsyncMock(
                side_effect=RscException(response=ApiException(status=403, reason="Executor cannot modify staff roles for this league."))
            ),
        )
        interaction = _mock_interaction(mock_guild)
        agm = _mock_agm()

        await CMD_ADD(mixin, interaction, FRANCHISE, agm)

        agm.add_roles.assert_not_awaited()
        assert _sent_embed(interaction).title == "API Error"

    async def test_lookup_failure_aborts_before_any_discord_change(self, mock_guild, agm_utils):
        channel = _mock_channel()
        mixin = _base_mixin(
            mock_guild,
            channel,
            franchises_agm_of=AsyncMock(side_effect=RscException(response=ApiException(status=500, reason="Error"))),
        )
        interaction = _mock_interaction(mock_guild)
        agm = _mock_agm()

        await CMD_ADD(mixin, interaction, FRANCHISE, agm)

        mixin.add_agm.assert_not_awaited()
        agm.add_roles.assert_not_awaited()
        assert _sent_embed(interaction).title == "API Error"

    async def test_re_add_is_idempotent_when_record_already_exists(self, mock_guild, agm_utils):
        """Rerunning after a partial Discord failure must repair Discord without
        disturbing the existing record. `add_agm` is a no-op server side, so it
        is still called rather than branched around."""
        channel = _mock_channel()
        mixin = _base_mixin(
            mock_guild,
            channel,
            franchises_agm_of=AsyncMock(return_value=[_franchise()]),
        )
        interaction = _mock_interaction(mock_guild)
        agm = _mock_agm()

        await CMD_ADD(mixin, interaction, FRANCHISE, agm)

        mixin.add_agm.assert_awaited_once()
        mixin.remove_agm.assert_not_awaited()
        agm.add_roles.assert_awaited_once()
        embed = _sent_embed(interaction)
        assert any(f.name == "API Record" for f in embed.fields)

    async def test_moves_agm_by_dropping_other_franchise_record(self, mock_guild, agm_utils):
        """The API has no reverse lookup, so the other franchise is found by
        scanning the franchise list for one that lists this member as an AGM."""
        channel = _mock_channel()
        mixin = _base_mixin(
            mock_guild,
            channel,
            franchises_agm_of=AsyncMock(return_value=[_franchise(OTHER_FRANCHISE_ID, OTHER_FRANCHISE)]),
        )
        interaction = _mock_interaction(mock_guild)
        agm = _mock_agm()

        await CMD_ADD(mixin, interaction, FRANCHISE, agm)

        mixin.remove_agm.assert_awaited_once_with(mock_guild, OTHER_FRANCHISE_ID, agm=agm, executor=interaction.user)
        mixin.add_agm.assert_awaited_once_with(mock_guild, FRANCHISE_ID, agm=agm, executor=interaction.user)
        embed = _sent_embed(interaction)
        stale = next(f for f in embed.fields if f.name == "Removed Stale API Records")
        assert OTHER_FRANCHISE in stale.value

    async def test_stale_removal_failure_aborts_before_any_discord_change(self, mock_guild, agm_utils):
        channel = _mock_channel()
        mixin = _base_mixin(
            mock_guild,
            channel,
            franchises_agm_of=AsyncMock(return_value=[_franchise(OTHER_FRANCHISE_ID, OTHER_FRANCHISE)]),
            remove_agm=AsyncMock(side_effect=RscException(response=ApiException(status=403, reason="Forbidden"))),
        )
        interaction = _mock_interaction(mock_guild)
        agm = _mock_agm()

        await CMD_ADD(mixin, interaction, FRANCHISE, agm)

        mixin.add_agm.assert_not_awaited()
        agm.add_roles.assert_not_awaited()
        assert _sent_embed(interaction).title == "API Error"

    async def test_missing_franchise_id_returns_error(self, mock_guild, agm_utils):
        channel = _mock_channel()
        mixin = _base_mixin(
            mock_guild,
            channel,
            fetch_franchise=AsyncMock(return_value=MagicMock(id=None, prefix="OCE")),
        )
        interaction = _mock_interaction(mock_guild)
        agm = _mock_agm()

        await CMD_ADD(mixin, interaction, FRANCHISE, agm)

        mixin.add_agm.assert_not_awaited()
        agm.add_roles.assert_not_awaited()
        assert "did not return an ID" in _sent_embed(interaction).description

    async def test_rostered_on_another_franchise_short_circuits(self, mock_guild, agm_utils):
        lp = MagicMock()
        lp.status = Status.ROSTERED
        lp.team = MagicMock()
        lp.team.franchise = MagicMock()
        lp.team.franchise.name = "Some Other Franchise"
        channel = _mock_channel()
        mixin = _base_mixin(mock_guild, channel, players=AsyncMock(return_value=[lp]))
        interaction = _mock_interaction(mock_guild)
        agm = _mock_agm()

        await CMD_ADD(mixin, interaction, FRANCHISE, agm)

        mixin.franchises_agm_of.assert_not_awaited()
        mixin.add_agm.assert_not_awaited()
        agm.add_roles.assert_not_awaited()


class TestAgmRemoveCommand:
    async def test_removes_agm_from_franchise(self, mock_guild, agm_utils, agm_sync):
        channel = _mock_channel()
        mixin = _base_mixin(
            mock_guild,
            channel,
            franchises_agm_of=AsyncMock(return_value=[_franchise()]),
        )
        interaction = _mock_interaction(mock_guild)
        agm = _mock_agm()

        await CMD_REMOVE(mixin, interaction, FRANCHISE, agm)

        mixin.remove_agm.assert_awaited_once_with(mock_guild, FRANCHISE_ID, agm=agm, executor=interaction.user)
        assert agm_sync.await_args.kwargs["agm_franchise"] is None
        channel.set_permissions.assert_awaited_once()
        embed = _sent_embed(interaction)
        assert embed.title == "AGM Removed"
        assert ("API Records Removed", "1") in [(f.name, f.value) for f in embed.fields]

    async def test_no_record_still_cleans_up_discord(self, mock_guild, agm_utils, agm_sync):
        """Legacy AGMs predate the API record. Hard failing would strand them
        with the role forever."""
        channel = _mock_channel()
        mixin = _base_mixin(mock_guild, channel)
        interaction = _mock_interaction(mock_guild)
        agm = _mock_agm()

        await CMD_REMOVE(mixin, interaction, FRANCHISE, agm)

        mixin.remove_agm.assert_not_awaited()
        assert agm_sync.await_args.kwargs["agm_franchise"] is None
        embed = _sent_embed(interaction)
        assert embed.title == "AGM Removed"
        assert "No API AGM record was found" in embed.footer.text

    async def test_mismatched_franchise_aborts_without_removing(self, mock_guild, agm_utils, agm_sync):
        """A mis-typed franchise argument must not destroy another franchise's
        record, so refuse and leave Discord alone too.

        Scanning first is what lets the bot name the other franchise. Calling
        remove_agm blind would only produce the API's bare 404.
        """
        channel = _mock_channel()
        mixin = _base_mixin(
            mock_guild,
            channel,
            franchises_agm_of=AsyncMock(return_value=[_franchise(OTHER_FRANCHISE_ID, OTHER_FRANCHISE)]),
        )
        interaction = _mock_interaction(mock_guild)
        agm = _mock_agm()

        await CMD_REMOVE(mixin, interaction, FRANCHISE, agm)

        mixin.remove_agm.assert_not_awaited()
        agm_sync.assert_not_awaited()
        channel.set_permissions.assert_not_awaited()
        assert OTHER_FRANCHISE in _sent_embed(interaction).description

    async def test_mixed_records_remove_only_the_named_franchise(self, mock_guild, agm_utils, agm_sync):
        channel = _mock_channel()
        mixin = _base_mixin(
            mock_guild,
            channel,
            franchises_agm_of=AsyncMock(return_value=[_franchise(OTHER_FRANCHISE_ID, OTHER_FRANCHISE), _franchise()]),
        )
        interaction = _mock_interaction(mock_guild)
        agm = _mock_agm()

        await CMD_REMOVE(mixin, interaction, FRANCHISE, agm)

        mixin.remove_agm.assert_awaited_once_with(mock_guild, FRANCHISE_ID, agm=agm, executor=interaction.user)
        assert agm_sync.await_args.kwargs["agm_franchise"] is None

    async def test_remove_404_is_treated_as_already_removed(self, mock_guild, agm_utils, agm_sync):
        channel = _mock_channel()
        mixin = _base_mixin(
            mock_guild,
            channel,
            franchises_agm_of=AsyncMock(return_value=[_franchise()]),
            remove_agm=AsyncMock(side_effect=RscException(response=ApiException(status=404, reason="Not Found"))),
        )
        interaction = _mock_interaction(mock_guild)
        agm = _mock_agm()

        await CMD_REMOVE(mixin, interaction, FRANCHISE, agm)

        assert agm_sync.await_args.kwargs["agm_franchise"] is None
        embed = _sent_embed(interaction)
        assert embed.title == "AGM Removed"
        assert ("API Records Removed", "0") in [(f.name, f.value) for f in embed.fields]

    async def test_api_failure_aborts_before_role_changes(self, mock_guild, agm_utils):
        channel = _mock_channel()
        mixin = _base_mixin(
            mock_guild,
            channel,
            franchises_agm_of=AsyncMock(return_value=[_franchise()]),
            remove_agm=AsyncMock(side_effect=RscException(response=ApiException(status=403, reason="Forbidden"))),
        )
        interaction = _mock_interaction(mock_guild)
        agm = _mock_agm()

        await CMD_REMOVE(mixin, interaction, FRANCHISE, agm)

        agm.remove_roles.assert_not_awaited()
        channel.set_permissions.assert_not_awaited()
        assert _sent_embed(interaction).title == "API Error"

    async def test_lookup_failure_aborts_before_role_changes(self, mock_guild, agm_utils, agm_sync):
        channel = _mock_channel()
        mixin = _base_mixin(
            mock_guild,
            channel,
            franchises_agm_of=AsyncMock(side_effect=RscException(response=ApiException(status=500, reason="Error"))),
        )
        interaction = _mock_interaction(mock_guild)
        agm = _mock_agm()

        await CMD_REMOVE(mixin, interaction, FRANCHISE, agm)

        mixin.remove_agm.assert_not_awaited()
        agm_sync.assert_not_awaited()
        assert _sent_embed(interaction).title == "API Error"
