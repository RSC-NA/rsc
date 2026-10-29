"""What Dev League lobbies do differently. `rsc.lobbies.runner.LobbyRunner` does the rest."""

from typing import TYPE_CHECKING

import discord
from redbot.core.config import Group

from rsc.combines.models import CombinesLobby
from rsc.combines.views import LobbyKind
from rsc.devleague.api import DEVLEAGUE_API_URL
from rsc.devleague.tiers import channel_sort_key, lobby_channel_name
from rsc.lobbies.channels import Side
from rsc.lobbies.runner import LobbyLeague

if TYPE_CHECKING:
    from discord.types.guild import ChannelPositionUpdate


class DevLeague(LobbyLeague):
    kind = LobbyKind.DEV_LEAGUE
    name = "Dev League"
    label = "Dev League match"
    noun = "match"
    nouns = "matches"

    def store(self, guild: discord.Guild) -> Group:
        return self.cog.config.custom("DevLeague", str(guild.id))

    async def active(self, guild: discord.Guild) -> bool:
        return await self.cog._get_devleague_active(guild)

    async def category(self, guild: discord.Guild) -> discord.CategoryChannel | None:
        return await self.cog._get_devleague_category(guild)

    async def announce_channel(self, guild: discord.Guild) -> discord.TextChannel | None:
        return await self.cog._get_devleague_announce_channel(guild)

    def channel_name(self, lobby: CombinesLobby, side: Side) -> str:
        return lobby_channel_name(lobby.tier, lobby.id, side)

    def match_url(self, lobby: CombinesLobby) -> str:
        return f"{DEVLEAGUE_API_URL}/match/{lobby.id}"

    async def place(self, category: discord.CategoryChannel, home: discord.VoiceChannel, away: discord.VoiceChannel) -> None:
        """Place a new lobby's channels so game channels stay ordered S+ -> F.

        Sent as a single position update because two `channel.move()` calls
        build their payloads from the channel cache, which does not yet include
        the new channels' positions.
        """
        new_ids = {home.id, away.id}
        existing = sorted(
            (c for c in category.voice_channels if c.id not in new_ids),
            key=lambda c: (c.position, c.id),
        )

        home_key = channel_sort_key(home.name)
        index = len(existing)
        for i, channel in enumerate(existing):
            key = channel_sort_key(channel.name)
            if key is not None and home_key is not None and key > home_key:
                index = i
                break

        ordered = [*existing[:index], home, away, *existing[index:]]
        payload: list[ChannelPositionUpdate] = [{"id": c.id, "position": position} for position, c in enumerate(ordered)]
        await category.guild._state.http.bulk_channel_update(
            category.guild.id,
            payload,
            reason="Sorting dev league channels by tier",
        )
