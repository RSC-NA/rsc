"""Protocol definition for TransactionMixIn."""

from __future__ import annotations

from typing import TYPE_CHECKING, Protocol, runtime_checkable


if TYPE_CHECKING:
    import discord
    from rscapi.models import TransactionResponse, PlayerTransactionUpdates, TradeItem, LeaguePlayer
    from rsc.types import Substitute


@runtime_checkable
class TransactionProtocol(Protocol):
    """Protocol for transaction-related operations."""

    async def get_franchise_transaction_channel(self, guild: discord.Guild, franchise_name: str) -> discord.TextChannel | None:
        """Get the transaction channel for a franchise."""
        ...

    async def get_franchise_transaction_channel_name(self, franchise_name: str) -> str:
        """Get the name for a franchise transaction channel."""
        ...

    async def sign(
        self,
        guild: discord.Guild,
        player: discord.Member,
        team: str,
        executor: discord.Member,
        notes: str | None = None,
        override: bool = False,
    ) -> TransactionResponse:
        """Sign a player to a team."""
        ...

    async def cut(
        self,
        guild: discord.Guild,
        player: discord.Member,
        executor: discord.Member,
        notes: str | None = None,
        override: bool = False,
    ) -> TransactionResponse:
        """Cut a player from their team."""
        ...

    async def resign(
        self,
        guild: discord.Guild,
        player: discord.Member,
        team: str,
        executor: discord.Member,
        notes: str | None = None,
        override: bool = False,
    ) -> TransactionResponse:
        """Re-sign a player to their team."""
        ...

    async def set_captain(self, guild: discord.Guild, id: int) -> LeaguePlayer:
        """Set a player as team captain."""
        ...

    async def substitution(
        self,
        guild: discord.Guild,
        player_in: discord.Member,
        player_out: discord.Member,
        executor: discord.Member,
        notes: str | None = None,
        override: bool = False,
    ) -> TransactionResponse:
        """Create a substitution for a player."""
        ...

    async def expire_sub(
        self,
        guild: discord.Guild,
        player: discord.Member,
        executor: discord.Member,
    ) -> LeaguePlayer:
        """Expire a player's substitution."""
        ...

    async def get_sub(self, member: discord.Member) -> Substitute | None:
        """Get substitution info for a member."""
        ...

    async def build_transaction_embed(
        self,
        guild: discord.Guild,
        response: TransactionResponse,
        player_in: discord.Member,
        player_out: discord.Member | None = None,
    ) -> tuple[discord.Embed, list[discord.File]]: ...

    async def send_cut_msg(self, guild: discord.Guild, player: discord.Member) -> discord.Message | None:
        """Send a cut notification message."""
        ...

    async def league_player_from_transaction(
        self,
        transaction: TransactionResponse,
        player: discord.Member,
    ) -> PlayerTransactionUpdates | None:
        """Get league player from transaction data."""
        ...

    async def announce_to_transaction_committee(self, guild: discord.Guild, **kwargs) -> discord.Message | None:
        """Announce to the transaction committee channel."""
        ...

    async def announce_to_franchise_transactions(
        self, guild: discord.Guild, franchise: str, gm: discord.Member | int, **kwargs
    ) -> discord.Message | None:
        """Announce to a franchise's transaction channel."""
        ...

    async def parse_trade_text(self, guild: discord.Guild, data: str) -> list[TradeItem]:
        """Parse trade text into trade items."""
        ...

    async def build_trade_embed(self, guild: discord.Guild, trades: list[TradeItem]) -> tuple[list[int], discord.Embed]:
        """Build a trade announcement embed."""
        ...

    async def announce_transaction(
        self,
        guild: discord.Guild,
        embed: discord.Embed,
        files: list[discord.File] | None = None,
        player: discord.Member | int | None = None,
        gm: discord.Member | int | None = None,
    ) -> discord.Message | None: ...

    async def _trans_channel(self, guild: discord.Guild) -> discord.TextChannel | None: ...

    async def _trans_role(self, guild: discord.Guild) -> discord.Role | None: ...
