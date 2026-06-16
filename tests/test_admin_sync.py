from unittest.mock import AsyncMock, MagicMock, patch

import discord
import pytest

from rsc.admin.sync import AdminSyncMixIn


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
        mixin.get_franchise_transaction_channel_name = AsyncMock(
            side_effect=lambda name: f"{name.lower().replace(' ', '-')}-transactions"
        )
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

        await AdminSyncMixIn._validate_transaction_channels.callback(mixin, interaction, category)

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

        await AdminSyncMixIn._validate_transaction_channels.callback(mixin, interaction, category, delete_stale=True)

        stale_channel.delete.assert_awaited_once()
        embed = interaction.edit_original_response.await_args.kwargs["embed"]
        deleted_field = next(field for field in embed.fields if field.name == "Deleted")
        assert deleted_field.value == "old-transactions"
