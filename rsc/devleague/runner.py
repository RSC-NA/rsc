"""What Dev League lobbies do differently. `rsc.lobbies.runner.LobbyRunner` does the rest."""

import discord
from redbot.core.config import Group

from rsc.combines.models import CombinesLobby
from rsc.combines.views import LobbyKind
from rsc.devleague.api import DEVLEAGUE_API_URL
from rsc.devleague.tiers import channel_sort_key, lobby_channel_name
from rsc.lobbies.channels import Side
from rsc.lobbies.runner import LobbyLeague


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

    def sort_key(self, name: str) -> tuple[int, ...] | None:
        """S+ down to F, then match ID, home before away."""
        return channel_sort_key(name)
