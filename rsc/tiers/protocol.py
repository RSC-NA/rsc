"""Protocol definition for TierMixIn."""

from __future__ import annotations

from typing import TYPE_CHECKING, Protocol, runtime_checkable


if TYPE_CHECKING:
    import discord
    from rscapi.models import TeamStandings, Tier


@runtime_checkable
class TierProtocol(Protocol):
    """Protocol for tier-related operations."""

    async def is_valid_tier(self, guild: discord.Guild, name: str) -> bool:
        """Check if a tier name is valid."""
        ...

    async def tier_fa_roles(self, guild: discord.Guild) -> list[discord.Role]:
        """Get free agent roles for all tiers."""
        ...

    async def tier_id_by_name(self, guild: discord.Guild, tier: str) -> int:
        """Get tier ID from tier name."""
        ...

    async def tier_by_id(self, guild: discord.Guild, id: int) -> Tier:
        """Get a tier by its ID."""
        ...

    async def tiers(self, guild: discord.Guild, name: str | None = None) -> list[Tier]:
        """Fetch tiers with optional name filter."""
        ...

    async def tier_standings(self, guild: discord.Guild, tier_id: int, season: int) -> list[TeamStandings]:
        """Get standings for a tier."""
        ...

    async def create_tier(self, guild: discord.Guild, name: str, color: int, position: int) -> Tier:
        """Create a new tier."""
        ...

    async def delete_tier(self, guild: discord.Guild, id: int) -> None:
        """Delete a tier."""
        ...
