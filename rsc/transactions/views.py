"""Transaction modals, and the transaction card posted to the transactions channel (Components V2)."""

import logging
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path

import discord
from discord import ui
from discord.ui import TextInput

log = logging.getLogger("red.rsc.transactions.views")


class TradeAnnouncementModal(discord.ui.Modal, title="Trade Announcement"):
    trade: TextInput = TextInput(
        label="Enter what GM receives",
        placeholder="GM receives...",
        style=discord.TextStyle.paragraph,
        required=True,
    )

    async def on_submit(self, interaction: discord.Interaction):
        await interaction.response.defer(ephemeral=True)
        if not self.trade.value:
            await interaction.followup.send(content="No trade data provided...", ephemeral=True)
            return
        self.stop()


@dataclass(frozen=True)
class TransactionCard:
    """One player's transaction: signed, released, re-signed, subbed, retired or moved on or off IR."""

    # "X has been signed by Team (Tier)", already markdown-escaped
    title: str
    player_id: int
    colour: discord.Colour
    banner: Path
    created_at: datetime
    # The starter a substitute replaces
    player_out_id: int | None = None
    franchise: str | None = None
    gm_id: int | None = None

    def render(self) -> tuple[ui.LayoutView, list[discord.File]]:
        """The card and its banner. A fresh File each call, since a send consumes it."""
        franchise = [discord.utils.escape_markdown(self.franchise)] if self.franchise else []
        gm = [f"GM <@{self.gm_id}>"] if self.gm_id else []
        if self.player_out_id:
            facts = f"In <@{self.player_id}> · Out <@{self.player_out_id}>"
            if franchise or gm:
                facts += f"\n{' · '.join(franchise + gm)}"
        else:
            facts = " · ".join([f"<@{self.player_id}>", *franchise, *gm])

        banner = discord.File(self.banner, filename=self.banner.name)
        # The Discord ID wording matches the old embed footer, so one search finds old and new posts
        footer = f"-# Discord ID: {self.player_id} · {discord.utils.format_dt(self.created_at, 'f')}"
        container = ui.Container(
            ui.TextDisplay(f"### {self.title}"),
            # A TextDisplay, so these mentions ping; embed mentions never do
            ui.TextDisplay(facts),
            ui.MediaGallery(discord.MediaGalleryItem(banner)),
            ui.TextDisplay(footer),
            accent_colour=self.colour,
        )

        view = ui.LayoutView(timeout=None)
        view.add_item(container)
        return view, [banner]
