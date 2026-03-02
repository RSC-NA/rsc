"""Protocol definition for AdminMixIn."""

from __future__ import annotations

from typing import TYPE_CHECKING, Protocol, runtime_checkable

if TYPE_CHECKING:
    import discord


@runtime_checkable
class AdminProtocol(Protocol):
    """Protocol for admin-related operations used by other mixins."""

    async def setup_persistent_activity_check(self, guild: discord.Guild) -> None:
        """Check if inactivity check is present and make it persistent."""
        ...

    async def _get_dates(self, guild: discord.Guild) -> str:
        """Get the configured dates string for a guild."""
        ...
