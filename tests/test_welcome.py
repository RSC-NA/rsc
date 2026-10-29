from unittest.mock import AsyncMock, MagicMock

import discord
import pytest

from rsc.welcome.welcome import WelcomeMixIn, defaults_guild


@pytest.fixture
def member() -> MagicMock:
    member = MagicMock(spec=discord.Member)
    member.guild = MagicMock(spec=discord.Guild)
    member.mention = "<@1>"
    member.add_roles = AsyncMock()
    return member


@pytest.fixture
def channel() -> MagicMock:
    channel = MagicMock(spec=discord.TextChannel)
    channel.send = AsyncMock()
    return channel


def _cog(channel: discord.TextChannel, *, enabled: bool, roles: list[discord.Role]) -> MagicMock:
    cog = MagicMock()
    cog._get_welcome_roles = AsyncMock(return_value=roles)
    cog._get_welcome_channel = AsyncMock(return_value=channel)
    cog._get_welcome_msg = AsyncMock(return_value="Welcome {member.mention}!")
    cog._get_welcome_status = AsyncMock(return_value=enabled)
    return cog


class TestOnJoin:
    async def test_enabled_posts_the_message(self, member, channel):
        await WelcomeMixIn.on_join_welcome(_cog(channel, enabled=True, roles=[]), member)

        channel.send.assert_awaited_once()
        assert channel.send.await_args is not None
        assert channel.send.await_args.kwargs["content"] == "Welcome <@1>!"

    async def test_disabled_posts_nothing(self, member, channel):
        await WelcomeMixIn.on_join_welcome(_cog(channel, enabled=False, roles=[]), member)

        channel.send.assert_not_awaited()

    async def test_disabled_still_gives_the_roles(self, member, channel):
        role = MagicMock(spec=discord.Role)

        await WelcomeMixIn.on_join_welcome(_cog(channel, enabled=False, roles=[role]), member)

        member.add_roles.assert_awaited_once_with(role)


def test_message_is_on_by_default():
    # Servers that never ran /welcome toggle were already posting the message
    assert defaults_guild["WelcomeStatus"] is True
