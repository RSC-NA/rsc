from unittest.mock import AsyncMock, MagicMock, patch

import discord
import pytest

from rsc.combines.manager import CombineManagerMixIn
from rsc.combines.runner import CombinesLeague

from .utils import command_callback


def _voice(name: str) -> MagicMock:
    channel = MagicMock(spec=discord.VoiceChannel)
    channel.name = name
    channel.delete = AsyncMock()
    return channel


@pytest.fixture
def guild() -> MagicMock:
    guild = MagicMock(spec=discord.Guild)
    guild.categories = []
    return guild


@pytest.fixture
def interaction(guild) -> MagicMock:
    interaction = MagicMock(spec=discord.Interaction)
    interaction.guild = guild
    interaction.response.defer = AsyncMock()
    interaction.followup.send = AsyncMock()
    return interaction


class TestTeardownCommand:
    async def test_runs_the_shared_teardown_on_combines(self, interaction):
        cog = MagicMock()

        with patch("rsc.combines.manager.teardown_command", AsyncMock()) as teardown:
            await command_callback(CombineManagerMixIn._combines_teardown_cmd)(cog, interaction, lobby_id=4812)

        teardown.assert_awaited_once_with(interaction, cog._combines_runner, 4812)


class TestStop:
    async def test_turns_off_ends_lobbies_then_deletes_categories(self, guild, interaction):
        order = []
        category = MagicMock(spec=discord.CategoryChannel)
        category.name = "Combines"
        cog = MagicMock()
        cog._get_combines_active = AsyncMock(return_value=True)
        cog._get_combines_category = AsyncMock(return_value=category)
        cog._set_combines_active = AsyncMock(side_effect=lambda *args, **kwargs: order.append("off"))
        cog._combines_runner.league = CombinesLeague(MagicMock())
        cog._combines_runner.open_lobbies = AsyncMock(return_value={4813, 4812})
        cog._combines_runner.end_now = AsyncMock(side_effect=lambda *args: order.append("end") or [])
        cog.delete_combine_category = AsyncMock(side_effect=lambda *args: order.append("delete"))

        await command_callback(CombineManagerMixIn._combines_stop)(cog, interaction)

        # Off first, so no new lobby starts. Cards turn Final before the categories go.
        assert order == ["off", "end", "delete"]
        cog._combines_runner.end_now.assert_awaited_once_with(guild, [4812, 4813])
        assert interaction.followup.send.await_args is not None
        embed = interaction.followup.send.await_args.kwargs["embed"]
        assert embed.description == "Combines have been ended and channels deleted.\nEnded 2 lobbies: 4812, 4813."
        assert embed.color == discord.Color.green()

    async def test_nothing_open(self, interaction):
        category = MagicMock(spec=discord.CategoryChannel)
        category.name = "Combines"
        cog = MagicMock()
        cog._get_combines_active = AsyncMock(return_value=True)
        cog._get_combines_category = AsyncMock(return_value=category)
        cog._set_combines_active = AsyncMock()
        cog._combines_runner.league = CombinesLeague(MagicMock())
        cog._combines_runner.open_lobbies = AsyncMock(return_value=set())
        cog._combines_runner.end_now = AsyncMock(return_value=[])
        cog.delete_combine_category = AsyncMock()

        await command_callback(CombineManagerMixIn._combines_stop)(cog, interaction)

        cog.delete_combine_category.assert_awaited_once_with(category)
        assert interaction.followup.send.await_args is not None
        embed = interaction.followup.send.await_args.kwargs["embed"]
        assert embed.description == "Combines have been ended and channels deleted."
        assert embed.color == discord.Color.green()

    async def test_not_active_is_only_shown_to_the_caller(self, interaction):
        cog = MagicMock()
        cog._get_combines_active = AsyncMock(return_value=False)
        interaction.response.send_message = AsyncMock()

        await command_callback(CombineManagerMixIn._combines_stop)(cog, interaction)

        assert interaction.response.send_message.await_args is not None
        assert interaction.response.send_message.await_args.kwargs["ephemeral"] is True


class TestDeleteCombineCategory:
    async def test_skips_channels_lobby_teardown_already_deleted(self):
        gone = _voice("Premier-101-home")
        gone.delete.side_effect = discord.NotFound(MagicMock(status=404), "Unknown Channel")
        keep_going = _voice("combines-waiting-room-1")
        category = MagicMock(spec=discord.CategoryChannel)
        category.channels = [gone, keep_going]
        category.delete = AsyncMock()

        await CombineManagerMixIn.delete_combine_category(MagicMock(), category)

        keep_going.delete.assert_awaited_once()
        category.delete.assert_awaited_once()


class TestGuideCommand:
    @pytest.fixture
    def channel(self) -> MagicMock:
        channel = MagicMock(spec=discord.TextChannel)
        channel.name = "how-to-play"
        channel.mention = "<#7>"
        channel.send = AsyncMock()
        return channel

    @pytest.fixture
    def cog(self, channel) -> MagicMock:
        category = MagicMock(spec=discord.CategoryChannel)
        category.text_channels = [channel]
        cog = MagicMock()
        cog._get_combines_category = AsyncMock(return_value=category)
        cog.combines_guide_card = AsyncMock(return_value=(MagicMock(), []))
        return cog

    def _posted(self, guild, channel, *messages) -> None:
        async def history(**kwargs):
            for message in messages:
                yield message

        channel.history = history
        for message in messages:
            message.author = guild.me

    def _guide(self) -> MagicMock:
        message = MagicMock(spec=discord.Message)
        message.jump_url = "https://discord.com/channels/1/7/100"
        message.edit = AsyncMock(return_value=message)
        return message

    def _reply(self, interaction) -> str:
        assert interaction.followup.send.await_args is not None
        description = interaction.followup.send.await_args.kwargs["embed"].description
        assert isinstance(description, str)
        return description

    async def test_posts_in_how_to_play_when_none_is_there(self, guild, interaction, cog, channel):
        self._posted(guild, channel)

        await command_callback(CombineManagerMixIn._combines_guide_cmd)(cog, interaction)

        channel.send.assert_awaited_once()
        assert self._reply(interaction).startswith("Posted the guide")

    async def test_links_the_existing_guide_instead_of_posting_another(self, guild, interaction, cog, channel):
        guide = self._guide()
        self._posted(guild, channel, guide)

        with patch("rsc.combines.manager.is_combines_guide", return_value=True):
            await command_callback(CombineManagerMixIn._combines_guide_cmd)(cog, interaction)

        channel.send.assert_not_awaited()
        guide.edit.assert_not_awaited()
        assert guide.jump_url in self._reply(interaction)

    async def test_overwrite_updates_the_existing_guide_in_place(self, guild, interaction, cog, channel):
        guide = self._guide()
        self._posted(guild, channel, guide)

        with patch("rsc.combines.manager.is_combines_guide", return_value=True):
            await command_callback(CombineManagerMixIn._combines_guide_cmd)(cog, interaction, overwrite=True)

        channel.send.assert_not_awaited()
        guide.edit.assert_awaited_once()
        assert self._reply(interaction).startswith("Updated the guide")
