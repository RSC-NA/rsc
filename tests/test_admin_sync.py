from unittest.mock import AsyncMock, MagicMock, patch

import discord
import pytest

from rsc.admin.sync import AdminSyncMixIn
from rsc.admin.views import ConfirmSyncView
from rsc.enums import Status
from rsc.exceptions import DiscordNameTooLong, RscException

from .utils import command_callback


def _create_mixin(**attrs):
    saved = AdminSyncMixIn.__abstractmethods__
    AdminSyncMixIn.__abstractmethods__ = frozenset()
    try:
        m = object.__new__(AdminSyncMixIn)
    finally:
        AdminSyncMixIn.__abstractmethods__ = saved
    for k, v in attrs.items():
        setattr(m, k, v)
    return m


def _make_franchise(name: str, gm_discord_id: int | None = None):
    franchise = MagicMock()
    franchise.id = 1
    franchise.name = name
    franchise.gm = MagicMock()
    franchise.gm.discord_id = gm_discord_id
    return franchise


class TestTransactionChannelSync:
    @pytest.fixture
    def interaction(self, mock_guild):
        interaction = MagicMock(spec=discord.Interaction)
        interaction.guild = mock_guild
        interaction.edit_original_response = AsyncMock()
        return interaction

    @pytest.fixture
    def category(self):
        category = MagicMock(spec=discord.CategoryChannel)
        category.text_channels = []
        return category

    @pytest.fixture
    def mixin(self, mock_guild):
        mixin = _create_mixin()
        mixin.franchises = AsyncMock(return_value=[_make_franchise("Active One"), _make_franchise("Active Two")])
        mixin.get_franchise_transaction_channel_name = AsyncMock(side_effect=lambda name: f"{name.lower().replace(' ', '-')}-transactions")
        mixin.get_franchise_transaction_channel = AsyncMock()
        mixin._trans_role = AsyncMock(return_value=None)

        mock_guild.default_role = MagicMock(spec=discord.Role)
        mock_guild.get_member = MagicMock(return_value=None)
        return mixin

    @patch("rsc.admin.sync.ConfirmSyncView")
    async def test_transaction_channel_sync_keeps_create_only_as_default(
        self,
        mock_confirm_view_cls,
        mixin,
        interaction,
        category,
        mock_guild,
    ):
        confirm_view = MagicMock()
        confirm_view.prompt = AsyncMock()
        confirm_view.wait = AsyncMock()
        confirm_view.result = True
        mock_confirm_view_cls.return_value = confirm_view

        existing_channel = MagicMock(spec=discord.TextChannel)
        existing_channel.name = "active-one-transactions"
        existing_channel.mention = "#active-one-transactions"

        stale_channel = MagicMock(spec=discord.TextChannel)
        stale_channel.name = "old-transactions"
        stale_channel.delete = AsyncMock()

        created_channel = MagicMock(spec=discord.TextChannel)
        created_channel.name = "active-two-transactions"
        created_channel.mention = "#active-two-transactions"
        created_channel.send = AsyncMock()

        category.text_channels = [existing_channel, stale_channel]
        mixin.get_franchise_transaction_channel.side_effect = [existing_channel, None]
        mock_guild.create_text_channel = AsyncMock(return_value=created_channel)

        await command_callback(AdminSyncMixIn._validate_transaction_channels)(mixin, interaction, category)

        stale_channel.delete.assert_not_awaited()
        mock_guild.create_text_channel.assert_awaited_once()
        embed = interaction.edit_original_response.await_args.kwargs["embed"]
        assert "Deleted" not in [field.name for field in embed.fields]

    @patch("rsc.admin.sync.ConfirmSyncView")
    async def test_transaction_channel_sync_deletes_stale_when_requested(
        self,
        mock_confirm_view_cls,
        mixin,
        interaction,
        category,
    ):
        confirm_view = MagicMock()
        confirm_view.prompt = AsyncMock()
        confirm_view.wait = AsyncMock()
        confirm_view.result = True
        mock_confirm_view_cls.return_value = confirm_view

        active_channel = MagicMock(spec=discord.TextChannel)
        active_channel.name = "active-one-transactions"
        active_channel.mention = "#active-one-transactions"

        stale_channel = MagicMock(spec=discord.TextChannel)
        stale_channel.name = "old-transactions"
        stale_channel.delete = AsyncMock()

        category.text_channels = [active_channel, stale_channel]
        mixin.franchises = AsyncMock(return_value=[_make_franchise("Active One")])
        mixin.get_franchise_transaction_channel.side_effect = [active_channel]

        await command_callback(AdminSyncMixIn._validate_transaction_channels)(mixin, interaction, category, delete_stale=True)

        stale_channel.delete.assert_awaited_once()
        embed = interaction.edit_original_response.await_args.kwargs["embed"]
        deleted_field = next(field for field in embed.fields if field.name == "Deleted")
        assert deleted_field.value == "old-transactions"


class TestNonPlayingSyncAgmSweep:
    """`/admin sync nonplaying` reconciles AGM state against the API.

    The per-member loop can only reach members the API returns. The reverse
    sweep is what catches someone still holding the Assistant GM role who has no
    member record at all -- the role is the one piece of AGM state that nothing
    else would ever take back.
    """

    @pytest.fixture
    def interaction(self, mock_guild):
        interaction = MagicMock(spec=discord.Interaction)
        interaction.guild = mock_guild
        interaction.response = MagicMock()
        interaction.response.defer = AsyncMock()
        interaction.edit_original_response = AsyncMock()
        interaction.followup = MagicMock()
        interaction.followup.send = AsyncMock()
        return interaction

    @staticmethod
    def _member(discord_id, name="someone"):
        m = MagicMock(spec=discord.Member)
        m.id = discord_id
        m.display_name = name
        m.mention = f"<@{discord_id}>"
        m.roles = []
        m.remove_roles = AsyncMock()
        return m

    @staticmethod
    async def _no_members():
        """`paged_members` yields nothing: this suite is about the sweep."""
        return
        yield  # pragma: no cover - makes this an async generator

    @pytest.fixture
    def agm_role(self):
        role = MagicMock(spec=discord.Role)
        role.name = "Assistant GM"
        role.members = []
        return role

    @pytest.fixture
    def mixin(self, agm_franchise_map):
        mixin = _create_mixin()
        mixin.tiers = AsyncMock(return_value=[])
        mixin._get_welcome_roles = AsyncMock(return_value=[])
        mixin.agm_franchise_map = AsyncMock(return_value=agm_franchise_map)
        mixin.paged_members = MagicMock(return_value=self._no_members())
        mixin.league_player_from_member = AsyncMock(return_value=None)
        return mixin

    @pytest.fixture
    def agm_franchise_map(self):
        return {}

    async def _run(self, mixin, interaction, agm_role, dryrun=False, confirmed=True):
        with (
            patch("rsc.admin.sync.ConfirmSyncView") as view_cls,
            patch("rsc.admin.sync.utils.get_agm_role", AsyncMock(return_value=agm_role)),
        ):
            view = MagicMock()
            view.prompt = AsyncMock()
            view.wait = AsyncMock()
            view.result = confirmed
            view_cls.return_value = view
            self.view_cls = view_cls
            self.view = view

            await command_callback(AdminSyncMixIn._sync_nonplaying_cmd)(mixin, interaction, dryrun)
        if not interaction.edit_original_response.await_args:
            return None
        return interaction.edit_original_response.await_args.kwargs["embed"]

    def _api_members(self, mixin, interaction, members):
        """`paged_members` yields one API member per discord member, none of them playing."""

        async def _yield():
            for m in members:
                api_member = MagicMock()
                api_member.discord_id = m.id
                yield api_member

        by_id = {m.id: m for m in members}
        mixin.paged_members = MagicMock(return_value=_yield())
        interaction.guild.get_member = MagicMock(side_effect=by_id.get)

    async def test_preview_lists_who_would_lose_a_prefix(self, mixin, interaction, agm_role):
        """After a season rolls over, everyone yet to declare intent has no league
        player. Staff must see how many prefixes a run strips before confirming."""
        player = self._member(1, "ABC | alice")
        unprefixed = self._member(2, "bob")
        agm = self._member(3, "XYZ | carol")
        self._api_members(mixin, interaction, [player, unprefixed, agm])
        mixin.agm_franchise_map = AsyncMock(return_value={3: MagicMock()})

        with patch("rsc.admin.sync.update_nonplaying_discord", AsyncMock()):
            await self._run(mixin, interaction, agm_role)

        preview = self.view.prompt.await_args.kwargs["embed"]
        field = next(f for f in preview.fields if f.name.startswith("Losing a Prefix"))
        assert field.name == "Losing a Prefix (1)"
        assert player.mention in field.value
        assert agm.mention not in field.value
        assert "**3** of 3" in preview.description

    async def test_dryrun_changes_nobody_and_skips_the_prompt(self, mixin, interaction, agm_role):
        player = self._member(1, "ABC | alice")
        self._api_members(mixin, interaction, [player])

        with patch("rsc.admin.sync.update_nonplaying_discord", AsyncMock()) as sync:
            embed = await self._run(mixin, interaction, agm_role, dryrun=True)

        sync.assert_not_awaited()
        self.view_cls.assert_not_called()
        assert embed.footer.text == "Dry run. Nothing was changed."
        assert "Losing a Prefix (1)" in [f.name for f in embed.fields]

    async def test_declining_changes_nobody(self, mixin, interaction, agm_role):
        player = self._member(1, "ABC | alice")
        stale = self._member(111)
        agm_role.members = [stale]
        self._api_members(mixin, interaction, [player])

        with patch("rsc.admin.sync.update_nonplaying_discord", AsyncMock()) as sync:
            await self._run(mixin, interaction, agm_role, confirmed=False)

        sync.assert_not_awaited()
        stale.remove_roles.assert_not_awaited()

    async def test_api_failure_while_planning_is_reported(self, mixin, interaction, agm_role):
        """The command has deferred, so an unhandled error would leave it thinking forever."""
        mixin.paged_members = MagicMock(side_effect=RscException("API down"))

        with patch("rsc.admin.sync.update_nonplaying_discord", AsyncMock()) as sync:
            await self._run(mixin, interaction, agm_role)

        sync.assert_not_awaited()
        self.view_cls.assert_not_called()
        interaction.edit_original_response.assert_awaited_once()

    async def test_strips_the_role_from_a_member_the_api_does_not_list(self, mixin, interaction, agm_role):
        stale = self._member(111)
        agm_role.members = [stale]

        embed = await self._run(mixin, interaction, agm_role)

        stale.remove_roles.assert_awaited_once_with(agm_role, reason="API has no AGM record for this member")
        assert "Stale AGM Roles (1)" in [f.name for f in embed.fields]

    async def test_leaves_a_real_agm_alone(self, mixin, interaction, agm_role):
        real = self._member(111)
        agm_role.members = [real]
        mixin.agm_franchise_map = AsyncMock(return_value={111: MagicMock()})

        embed = await self._run(mixin, interaction, agm_role)

        real.remove_roles.assert_not_awaited()
        assert not [f for f in embed.fields if f.name.startswith("Stale AGM Roles")]

    async def test_dryrun_reports_without_removing(self, mixin, interaction, agm_role):
        """This is the first sync that can remove the role at scale, so the
        rehearsal has to show exactly what a live run would do."""
        stale = self._member(111)
        agm_role.members = [stale]

        embed = await self._run(mixin, interaction, agm_role, dryrun=True)

        stale.remove_roles.assert_not_awaited()
        field = next(f for f in embed.fields if f.name.startswith("Stale AGM Roles"))
        assert "Would remove" in field.value
        assert stale.mention in field.value

    async def test_long_sweep_is_truncated_for_the_embed_field(self, mixin, interaction, agm_role):
        """Discord caps a field value at 1024 characters."""
        agm_role.members = [self._member(i) for i in range(1, 26)]

        embed = await self._run(mixin, interaction, agm_role)

        field = next(f for f in embed.fields if f.name.startswith("Stale AGM Roles"))
        assert field.name == "Stale AGM Roles (25)"
        assert "...and 5 more" in field.value
        assert len(field.value) <= 1024

    async def test_missing_agm_role_skips_the_sweep(self, mixin, interaction, agm_role):
        """A guild without the role configured must still finish the sync."""
        with (
            patch("rsc.admin.sync.ConfirmSyncView") as view_cls,
            patch("rsc.admin.sync.utils.get_agm_role", AsyncMock(side_effect=ValueError("no role"))),
        ):
            view = MagicMock()
            view.prompt = AsyncMock()
            view.wait = AsyncMock()
            view.result = True
            view_cls.return_value = view

            await command_callback(AdminSyncMixIn._sync_nonplaying_cmd)(mixin, interaction, False)

        embed = interaction.edit_original_response.await_args.kwargs["embed"]
        assert embed.title == "Non-Playing Sync"

    async def test_empty_franchise_list_aborts_before_touching_anyone(self, mixin, interaction, agm_role):
        """`agm_franchise_map` raises rather than answering {}. Otherwise one bad
        response would strip every AGM in the guild in a single run."""
        stale = self._member(111)
        agm_role.members = [stale]
        mixin.agm_franchise_map = AsyncMock(side_effect=RuntimeError("Refusing to build an AGM map"))

        embed = await self._run(mixin, interaction, agm_role)

        stale.remove_roles.assert_not_awaited()
        assert "Refusing to build an AGM map" in embed.description

    async def test_does_not_double_remove_a_member_the_loop_handled(self, mixin, interaction, agm_role):
        """`update_nonplaying_discord` already strips the role for members the
        API returns. Discord's role cache lags a removal, so without this the
        sweep would spend a second call on the same member."""
        stale = self._member(111)
        agm_role.members = [stale]

        api_member = MagicMock()
        api_member.discord_id = 111

        async def _one_member():
            yield api_member

        mixin.paged_members = MagicMock(return_value=_one_member())
        interaction.guild.get_member = MagicMock(return_value=stale)

        with patch("rsc.admin.sync.update_nonplaying_discord", AsyncMock()) as sync:
            embed = await self._run(mixin, interaction, agm_role)

        sync.assert_awaited_once()
        assert sync.await_args is not None
        assert sync.await_args.kwargs["agm_franchise"] is None
        stale.remove_roles.assert_not_awaited()
        assert not [f for f in embed.fields if f.name.startswith("Stale AGM Roles")]


class TestConfirmSyncViewPrompt:
    """A command that deferred to build a preview can only edit its original response."""

    @staticmethod
    def _interaction(*, deferred):
        interaction = MagicMock(spec=discord.Interaction)
        interaction.response = MagicMock()
        interaction.response.is_done = MagicMock(return_value=deferred)
        interaction.response.send_message = AsyncMock()
        interaction.edit_original_response = AsyncMock()
        return interaction

    async def test_deferred_command_gets_the_preview_above_the_prompt(self):
        interaction = self._interaction(deferred=True)
        preview = discord.Embed(title="Preview")

        await ConfirmSyncView(interaction).prompt(embed=preview)

        interaction.response.send_message.assert_not_awaited()
        embeds = interaction.edit_original_response.await_args.kwargs["embeds"]
        assert [e.title for e in embeds] == ["Preview", "API Sync"]

    async def test_fresh_command_answers_with_the_prompt(self):
        interaction = self._interaction(deferred=False)

        await ConfirmSyncView(interaction).prompt()

        interaction.edit_original_response.assert_not_awaited()
        embeds = interaction.response.send_message.await_args.kwargs["embeds"]
        assert [e.title for e in embeds] == ["API Sync"]


class TestPlayerSyncNicknameTooLong:
    """`/admin sync players` walks the whole league in one command.

    A member whose RSC name plus franchise prefix will not fit in a discord
    nickname is a data problem, not a bug, and it turns up mid-run. Their roles
    are applied before the rename is attempted, so the run has to report the
    member and keep going rather than lose the rest of the league to it.
    """

    @pytest.fixture
    def interaction(self, mock_guild):
        interaction = MagicMock(spec=discord.Interaction)
        interaction.guild = mock_guild
        interaction.edit_original_response = AsyncMock()
        interaction.followup = MagicMock()
        interaction.followup.send = AsyncMock()
        return interaction

    @staticmethod
    def _member(discord_id, name):
        m = MagicMock(spec=discord.Member)
        m.id = discord_id
        m.display_name = name
        m.mention = f"<@{discord_id}>"
        return m

    @staticmethod
    def _api_player(discord_id, name):
        p = MagicMock()
        p.id = discord_id
        p.status = Status.ROSTERED
        p.player = MagicMock()
        p.player.discord_id = discord_id
        p.player.name = name
        return p

    @pytest.fixture
    def members(self, mock_guild):
        by_id = {
            111: self._member(111, "cosmo6430"),
            222: self._member(222, "someone"),
        }
        mock_guild.get_member = MagicMock(side_effect=by_id.get)
        return by_id

    @pytest.fixture
    def mixin(self, members):
        async def _players():
            yield self._api_player(111, "cosmo6430 - INACTIVE USER - TRANSFER")
            yield self._api_player(222, "someone")

        mixin = _create_mixin()
        mixin.tiers = AsyncMock(return_value=[])
        mixin.agm_franchise_map = AsyncMock(return_value={})
        mixin.paged_players = MagicMock(return_value=_players())
        return mixin

    async def _run(self, mixin, interaction, sync_mock):
        with (
            patch("rsc.admin.sync.ConfirmSyncView") as view_cls,
            patch("rsc.admin.sync.update_league_player_discord", sync_mock),
        ):
            view = MagicMock()
            view.prompt = AsyncMock()
            view.wait = AsyncMock()
            view.result = True
            view_cls.return_value = view

            await command_callback(AdminSyncMixIn._sync_players_cmd)(mixin, interaction, False)

    async def test_reports_the_member_and_finishes_the_run(self, mixin, interaction, members):
        too_long = DiscordNameTooLong(member_id=111, nickname="COS | cosmo6430 - INACTIVE USER - TRANSFER")
        sync_mock = AsyncMock(side_effect=[too_long, None])

        await self._run(mixin, interaction, sync_mock)

        # The second player still synced.
        assert sync_mock.await_count == 2
        assert sync_mock.await_args_list[1].kwargs["player"] is members[222]

        embed = interaction.followup.send.await_args.kwargs["embed"]
        assert embed.title == "Nickname Too Long"
        assert members[111].mention in embed.description

        # And the command reported success for the run as a whole.
        assert interaction.edit_original_response.await_args.kwargs["embed"].title == "League Player Sync"
