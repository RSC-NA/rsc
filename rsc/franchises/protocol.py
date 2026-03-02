"""Protocol definition for FranchiseMixIn."""

from __future__ import annotations

from typing import TYPE_CHECKING, Protocol, runtime_checkable


if TYPE_CHECKING:
    import discord
    from os import PathLike
    from rscapi.models.franchise import Franchise
    from rscapi.models.franchise_gm import FranchiseGM
    from rscapi.models.franchise_list import FranchiseList
    from rscapi.models.rebrand_a_franchise import RebrandAFranchise


@runtime_checkable
class FranchiseProtocol(Protocol):
    """Protocol for franchise-related operations."""

    async def franchises(
        self,
        guild: discord.Guild,
        prefix: str | None = None,
        gm_name: str | None = None,
        gm_discord_id: int | None = None,
        name: str | None = None,
        tier: int | None = None,
        tier_name: str | None = None,
    ) -> list[FranchiseList]:
        """Fetch franchises from the API with optional filters."""
        ...

    async def franchise_gm_by_name(self, guild: discord.Guild, name: str) -> FranchiseGM | None:
        """Get the GM of a franchise by franchise name."""
        ...

    async def fetch_franchise(self, guild: discord.Guild, name: str) -> FranchiseList | None:
        """Fetch a single franchise by name."""
        ...

    async def franchise_name_to_id(self, guild: discord.Guild, franchise_name: str) -> int:
        """Convert a franchise name to its ID."""
        ...

    async def delete_franchise_by_name(self, guild: discord.Guild, franchise_name: str) -> None:
        """Delete a franchise by its name."""
        ...

    async def full_logo_url(self, guild: discord.Guild, logo_url: str) -> str:
        """Get the full URL for a franchise logo."""
        ...

    async def franchise_by_id(self, guild: discord.Guild, id: int) -> Franchise | None:
        """Fetch a franchise by its ID."""
        ...

    async def upload_franchise_logo(
        self,
        guild: discord.Guild,
        id: int,
        logo: str | bytes | PathLike,
    ) -> Franchise:
        """Upload a logo for a franchise."""
        ...

    async def create_franchise(
        self,
        guild: discord.Guild,
        name: str,
        prefix: str,
        gm: discord.Member,
    ) -> Franchise:
        """Create a new franchise."""
        ...

    async def delete_franchise(self, guild: discord.Guild, id: int) -> None:
        """Delete a franchise by ID."""
        ...

    async def rebrand_franchise(self, guild: discord.Guild, id: int, rebrand: RebrandAFranchise) -> Franchise:
        """Rebrand a franchise with new name/prefix."""
        ...

    async def transfer_franchise(self, guild: discord.Guild, id: int, gm: discord.Member) -> Franchise:
        """Transfer franchise ownership to a new GM."""
        ...

    async def franchise_logo(self, guild: discord.Guild, id: int) -> str | None:
        """Get the logo URL for a franchise."""
        ...
