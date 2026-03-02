"""Protocol definition for CombineMixIn."""

from __future__ import annotations

from typing import TYPE_CHECKING, Protocol, runtime_checkable


if TYPE_CHECKING:
    import discord
    from rsc.combines.models import CombinesLobby


@runtime_checkable
class CombineProtocol(Protocol):
    """Protocol for combine-related operations."""

    async def filter_combine_lobbies(
        self,
        guild: discord.Guild,
        lobbies: list[CombinesLobby],
        tier: str | None = None,
        player: discord.Member | None = None,
    ) -> list[CombinesLobby]:
        """Filter combine lobbies by criteria."""
        ...

    async def get_combine_room_list(self, guild: discord.Guild) -> list[discord.CategoryChannel]:
        """Get list of combine room categories."""
        ...

    async def total_players_in_combine_category(self, category: discord.CategoryChannel) -> int:
        """Count players in a combine category."""
        ...

    async def combine_players_from_lobby(self, guild: discord.Guild, lobby: CombinesLobby) -> list[discord.Member]:
        """Get discord members from a combine lobby."""
        ...

    async def _get_combines_active(self, guild: discord.Guild) -> bool: ...

    async def _get_combines_category(self, guild: discord.Guild) -> discord.CategoryChannel | None: ...
