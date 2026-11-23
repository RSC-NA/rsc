from unittest.mock import AsyncMock, MagicMock, patch

import discord
import pytest

from rsc.admin.sync import AdminSyncMixIn
from rsc.enums import Status
from rsc.exceptions import DiscordNameTooLong

from .utils import api_error, command_callback


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


def _league_player(discord_id: int, status: Status, name: str = "someone"):
    p = MagicMock()
    p.id = discord_id
    p.status = status
    p.player = MagicMock()
    p.player.discord_id = discord_id
    p.player.name = name
    return p


async def _rows(*rows):
    for row in rows:
        yield row


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
        mixin.paged_members = MagicMock(return_value=_rows())
        mixin.effective_players = MagicMock(return_value=_rows())
        return mixin

    @pytest.fixture
    def agm_franchise_map(self):
        return {}

    async def _run(self, mixin, interaction, agm_role, dryrun=False):
        with (
            patch("rsc.admin.sync.ConfirmSyncView") as view_cls,
            patch("rsc.admin.sync.utils.get_agm_role", AsyncMock(return_value=agm_role)),
        ):
            view = MagicMock()
            view.prompt = AsyncMock()
            view.wait = AsyncMock()
            view.result = True
            view_cls.return_value = view

            await command_callback(AdminSyncMixIn._sync_nonplaying_cmd)(mixin, interaction, dryrun)
        return interaction.edit_original_response.await_args.kwargs["embed"]

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

        mixin.paged_members = MagicMock(return_value=_rows(api_member))
        interaction.guild.get_member = MagicMock(return_value=stale)

        with patch("rsc.admin.sync.update_nonplaying_discord", AsyncMock()) as sync:
            embed = await self._run(mixin, interaction, agm_role)

        sync.assert_awaited_once()
        assert sync.await_args is not None
        assert sync.await_args.kwargs["agm_franchise"] is None
        stale.remove_roles.assert_not_awaited()
        assert not [f for f in embed.fields if f.name.startswith("Stale AGM Roles")]


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
        rows = _rows(
            _league_player(111, Status.ROSTERED, "cosmo6430 - INACTIVE USER - TRANSFER"),
            _league_player(222, Status.ROSTERED),
        )
        mixin = _create_mixin()
        mixin.tiers = AsyncMock(return_value=[])
        mixin.agm_franchise_map = AsyncMock(return_value={})
        mixin.effective_players = MagicMock(return_value=rows)
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


class TestNonPlayingSyncAcrossSeasons:
    @pytest.fixture
    def interaction(self, mock_guild):
        interaction = MagicMock(spec=discord.Interaction)
        interaction.guild = mock_guild
        interaction.edit_original_response = AsyncMock()
        interaction.followup = MagicMock()
        interaction.followup.send = AsyncMock()
        return interaction

    async def _run(self, interaction, effective_players):
        member = MagicMock(spec=discord.Member)
        member.id = 111
        member.display_name = "someone"
        interaction.guild.get_member = MagicMock(return_value=member)

        api_member = MagicMock()
        api_member.discord_id = 111

        mixin = _create_mixin()
        mixin.tiers = AsyncMock(return_value=[])
        mixin._get_welcome_roles = AsyncMock(return_value=[])
        mixin.agm_franchise_map = AsyncMock(return_value={})
        mixin.paged_members = MagicMock(return_value=_rows(api_member))
        mixin.effective_players = MagicMock(return_value=effective_players)

        with (
            patch("rsc.admin.sync.ConfirmSyncView") as view_cls,
            patch("rsc.admin.sync.utils.get_agm_role", AsyncMock(side_effect=ValueError("no role"))),
            patch("rsc.admin.sync.update_nonplaying_discord", AsyncMock()) as strip,
        ):
            view = MagicMock()
            view.prompt = AsyncMock()
            view.wait = AsyncMock()
            view.result = True
            view_cls.return_value = view

            await command_callback(AdminSyncMixIn._sync_nonplaying_cmd)(mixin, interaction, False)
        return strip

    async def test_leaves_a_member_whose_only_row_is_in_the_older_season(self, interaction):
        strip = await self._run(interaction, _rows(_league_player(111, Status.ROSTERED)))

        strip.assert_not_awaited()

    async def test_strips_a_member_with_no_row(self, interaction):
        strip = await self._run(interaction, _rows())

        strip.assert_awaited_once()

    @pytest.mark.parametrize("status", [Status.DROPPED, Status.FORMER, Status.BANNED])
    async def test_strips_a_member_whose_row_says_they_left(self, interaction, status):
        strip = await self._run(interaction, _rows(_league_player(111, status)))

        strip.assert_awaited_once()

    async def test_reports_an_api_failure_without_touching_anyone(self, interaction):
        async def failing():
            raise api_error(500, "Down")
            yield

        strip = await self._run(interaction, failing())

        strip.assert_not_awaited()
        assert "Down" in interaction.edit_original_response.await_args.kwargs["embed"].description


class TestMemberSyncAcrossSeasons:
    @pytest.fixture
    def interaction(self, mock_guild):
        interaction = MagicMock(spec=discord.Interaction)
        interaction.guild = mock_guild
        interaction.response = MagicMock()
        interaction.response.defer = AsyncMock()
        interaction.followup = MagicMock()
        interaction.followup.send = AsyncMock()
        return interaction

    async def _run(self, interaction, mock_member, effective_row):
        mixin = _create_mixin()
        mixin.tiers = AsyncMock(return_value=[])
        mixin._get_welcome_roles = AsyncMock(return_value=[])
        mixin.franchises = AsyncMock(return_value=[])
        mixin.effective_player = AsyncMock(return_value=effective_row)

        with (
            patch("rsc.admin.sync.update_league_player_discord", AsyncMock()) as sync,
            patch("rsc.admin.sync.update_nonplaying_discord", AsyncMock()) as strip,
        ):
            await command_callback(AdminSyncMixIn._sync_member_cmd)(mixin, interaction, mock_member)
        return sync, strip

    async def test_syncs_from_the_older_season_row_when_the_default_season_has_none(self, interaction, mock_member):
        row = _league_player(mock_member.id, Status.ROSTERED)

        sync, strip = await self._run(interaction, mock_member, row)

        sync.assert_awaited_once()
        assert sync.await_args is not None
        assert sync.await_args.kwargs["league_player"] is row
        strip.assert_not_awaited()

    async def test_a_member_with_no_row_becomes_non_playing(self, interaction, mock_member):
        sync, strip = await self._run(interaction, mock_member, None)

        sync.assert_not_awaited()
        strip.assert_awaited_once()


class TestNightlySyncIsolatesMembers:
    async def test_a_refused_role_write_does_not_end_the_run(self, mock_guild, caplog):
        refused = MagicMock(spec=discord.Member)
        refused.id = 111
        refused.display_name = "above the bot"
        other = MagicMock(spec=discord.Member)
        other.id = 222
        other.display_name = "someone"
        mock_guild.get_member = MagicMock(side_effect={111: refused, 222: other}.get)

        rows = [_league_player(111, Status.ROSTERED), _league_player(222, Status.ROSTERED)]
        mixin = _create_mixin()
        mixin.bot = MagicMock()
        mixin.bot.guilds = [mock_guild]
        mixin.tiers = AsyncMock(return_value=[])
        mixin.agm_franchise_map = AsyncMock(return_value={})
        mixin.should_get_devleague_role = AsyncMock(return_value=False)
        mixin.effective_players = MagicMock(return_value=_rows(*rows))

        forbidden = discord.Forbidden(MagicMock(status=403, reason="Forbidden"), "Missing Permissions")
        sync = AsyncMock(side_effect=[forbidden, None])

        with patch("rsc.admin.sync.update_league_player_discord", sync), caplog.at_level("INFO", logger="red.rsc.admin.sync"):
            await AdminSyncMixIn.sync_discord_roles.coro(mixin)

        assert sync.await_count == 2
        assert sync.await_args_list[1].kwargs["player"] is other

        warnings = [r.getMessage() for r in caplog.records if r.levelname == "WARNING"]
        assert len(warnings) == 1
        assert "above the bot" in warnings[0]
        assert "111" in warnings[0]
        assert any("Finished syncing league players" in r.getMessage() for r in caplog.records)
