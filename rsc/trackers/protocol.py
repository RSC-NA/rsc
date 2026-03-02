"""Protocol definition for TrackerMixIn."""

from __future__ import annotations

from typing import TYPE_CHECKING, Protocol, runtime_checkable


if TYPE_CHECKING:
    import discord
    from rscapi.models.tracker_link import TrackerLink
    from rscapi.models.tracker_link_stats import TrackerLinkStats

    from rsc.enums import TrackerLinksStatus


@runtime_checkable
class TrackerProtocol(Protocol):
    """Protocol for tracker-related operations."""

    async def trackers(
        self,
        guild: discord.Guild,
        status: TrackerLinksStatus | None = None,
        player: discord.Member | int | None = None,
        name: str | None = None,
        limit: int = 0,
        offset: int = 0,
    ) -> list[TrackerLink]:
        """Fetch tracker links with optional filters."""
        ...

    async def tracker_stats(
        self,
        guild: discord.Guild,
    ) -> TrackerLinkStats:
        """Fetch RSC Tracker Stats."""
        ...

    async def next_tracker(
        self,
        guild: discord.Guild,
        limit: int = 25,
    ) -> list[TrackerLink]:
        """Get list of trackers ready to be updated."""
        ...

    async def add_tracker(
        self,
        guild: discord.Guild,
        player: discord.Member,
        tracker: str,
    ) -> None:
        """Add a tracker for a player."""
        ...

    async def rm_tracker(
        self,
        guild: discord.Guild,
        tracker_id: int,
    ) -> None:
        """Remove a tracker."""
        ...

    async def unlink_tracker(
        self,
        guild: discord.Guild,
        tracker_id: int,
        player: discord.Member,
        executor: discord.Member,
    ) -> TrackerLink:
        """Unlink a tracker from a player."""
        ...

    async def link_tracker(
        self,
        guild: discord.Guild,
        tracker_id: int,
        player: discord.Member,
        executor: discord.Member,
    ) -> TrackerLink:
        """Link a tracker to a player."""
        ...

    async def fetch_tracker_by_id(
        self,
        guild: discord.Guild,
        tracker_id: int,
    ) -> TrackerLink:
        """Fetch a tracker by its ID."""
        ...

    async def migrate_tracker_pulls(
        self,
        guild: discord.Guild,
        source: int,
        dest: int,
    ) -> TrackerLink:
        """Migrate tracker pull data."""
        ...
