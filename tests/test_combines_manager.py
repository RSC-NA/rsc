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
    @pytest.fixture
    def category(self) -> MagicMock:
        category = MagicMock(spec=discord.CategoryChannel)
        category.name = "Combines"
        category.delete = AsyncMock()
        return category

    @pytest.fixture
    def cog(self, category) -> MagicMock:
        cog = MagicMock()
        cog._get_combines_active = AsyncMock(return_value=True)
        cog._get_combines_category = AsyncMock(return_value=category)
        cog._set_combines_active = AsyncMock()
        cog._combines_runner.league = CombinesLeague(MagicMock())
        cog._combines_runner.open_lobbies = AsyncMock(return_value=set())
        cog._combines_runner.end_now = AsyncMock(return_value=[])
        cog.delete_overflow_category = AsyncMock()
        return cog

    async def test_turns_off_then_ends_lobbies(self, cog, guild, interaction):
        order = []
        cog._set_combines_active.side_effect = lambda *args, **kwargs: order.append("off")
        cog._combines_runner.open_lobbies.return_value = {4813, 4812}
        cog._combines_runner.end_now.side_effect = lambda *args: order.append("end") or []

        await command_callback(CombineManagerMixIn._combines_stop)(cog, interaction)

        # Off first, so no new lobby starts while the open ones end
        assert order == ["off", "end"]
        cog._combines_runner.end_now.assert_awaited_once_with(guild, [4812, 4813])
        assert interaction.followup.send.await_args is not None
        embed = interaction.followup.send.await_args.kwargs["embed"]
        assert embed.description == (
            "Combines have been stopped. The combines category and its channels are kept.\nEnded 2 lobbies: 4812, 4813."
        )
        assert embed.color == discord.Color.green()

    async def test_keeps_the_combines_category(self, cog, category, interaction):
        await command_callback(CombineManagerMixIn._combines_stop)(cog, interaction)

        category.delete.assert_not_awaited()
        cog.delete_overflow_category.assert_not_awaited()
        assert interaction.followup.send.await_args is not None
        embed = interaction.followup.send.await_args.kwargs["embed"]
        assert embed.description == "Combines have been stopped. The combines category and its channels are kept."

    async def test_deletes_overflow_categories(self, cog, guild, interaction):
        overflow = MagicMock(spec=discord.CategoryChannel)
        overflow.name = "Combines-2"
        unrelated = MagicMock(spec=discord.CategoryChannel)
        unrelated.name = "General"
        guild.categories = [unrelated, overflow]

        await command_callback(CombineManagerMixIn._combines_stop)(cog, interaction)

        cog.delete_overflow_category.assert_awaited_once_with(overflow)

    async def test_stops_even_when_the_category_is_gone(self, cog, interaction):
        cog._get_combines_category.return_value = None
        cog._combines_runner.open_lobbies.return_value = {4812}

        await command_callback(CombineManagerMixIn._combines_stop)(cog, interaction)

        cog._set_combines_active.assert_awaited_once()
        assert cog._set_combines_active.await_args.kwargs == {"active": False}
        cog._combines_runner.end_now.assert_awaited_once()

    async def test_not_active_is_only_shown_to_the_caller(self, interaction):
        cog = MagicMock()
        cog._get_combines_active = AsyncMock(return_value=False)
        interaction.response.send_message = AsyncMock()

        await command_callback(CombineManagerMixIn._combines_stop)(cog, interaction)

        assert interaction.response.send_message.await_args is not None
        assert interaction.response.send_message.await_args.kwargs["ephemeral"] is True


class TestStart:
    @pytest.fixture
    def cog(self) -> MagicMock:
        cog = MagicMock()
        cog._get_combines_active = AsyncMock(return_value=False)
        cog._get_combines_api = AsyncMock(return_value="https://devleague.rscna.com/c-api/")
        cog._get_combines_category = AsyncMock(return_value=None)
        # The real messages, over the mocked config
        cog._no_category_msg = lambda guild: CombineManagerMixIn._no_category_msg(cog, guild)
        return cog

    @pytest.fixture
    def interaction(self, interaction) -> MagicMock:
        interaction.response.send_message = AsyncMock()
        return interaction

    def _reply(self, interaction) -> str:
        assert interaction.response.send_message.await_args is not None
        return interaction.response.send_message.await_args.kwargs["embed"].description

    async def test_says_when_the_category_was_deleted(self, cog, interaction):
        cog._combines_category_deleted = AsyncMock(return_value=True)

        await command_callback(CombineManagerMixIn._combines_start)(cog, interaction)

        assert self._reply(interaction) == "The combines category no longer exists. Set a new one with `/combinemanager category`."
        cog._set_combines_active.assert_not_called()

    async def test_says_when_no_category_was_set(self, cog, interaction):
        cog._combines_category_deleted = AsyncMock(return_value=False)

        await command_callback(CombineManagerMixIn._combines_start)(cog, interaction)

        assert self._reply(interaction) == "Combines category channel has not been configured!"


class TestCategoryDeleted:
    def _cog(self, saved_id: int | None, category: discord.CategoryChannel | None) -> MagicMock:
        cog = MagicMock()
        cog.config.custom.return_value.CombinesCategory = AsyncMock(return_value=saved_id)
        cog._get_combines_category = AsyncMock(return_value=category)
        return cog

    async def test_saved_but_missing(self, guild):
        assert await CombineManagerMixIn._combines_category_deleted(self._cog(55, None), guild) is True

    async def test_never_set(self, guild):
        assert await CombineManagerMixIn._combines_category_deleted(self._cog(None, None), guild) is False

    async def test_still_there(self, guild):
        category = MagicMock(spec=discord.CategoryChannel)
        assert await CombineManagerMixIn._combines_category_deleted(self._cog(55, category), guild) is False


class TestDeleteOverflowCategory:
    async def test_skips_channels_lobby_teardown_already_deleted(self):
        gone = _voice("Premier-101-home")
        gone.delete.side_effect = discord.NotFound(MagicMock(status=404), "Unknown Channel")
        keep_going = _voice("Premier-102-home")
        category = MagicMock(spec=discord.CategoryChannel)
        category.channels = [gone, keep_going]
        category.delete = AsyncMock()

        await CombineManagerMixIn.delete_overflow_category(MagicMock(), category)

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
