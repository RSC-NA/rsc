from unittest.mock import AsyncMock, MagicMock

import discord

from rsc.combines.manager import CombineManagerMixIn


def _voice(name: str) -> MagicMock:
    channel = MagicMock(spec=discord.VoiceChannel)
    channel.name = name
    channel.delete = AsyncMock()
    return channel


class TestDeleteCombineGameRooms:
    async def test_deletes_lobby_channels_and_keeps_the_rest(self):
        lobbies = [_voice(n) for n in ("Premier-101-home", "Premier-101-away", "Elite-4812-home", "Master League-7-away")]
        keep = [_voice(n) for n in ("combines-waiting-room-1", "combines-waiting-room-2", "general")]
        category = MagicMock(spec=discord.CategoryChannel)
        category.name = "Combines"
        category.voice_channels = [*lobbies, *keep]

        await CombineManagerMixIn.delete_combine_game_rooms(MagicMock(), category)

        for channel in lobbies:
            channel.delete.assert_awaited_once()
        for channel in keep:
            channel.delete.assert_not_called()
