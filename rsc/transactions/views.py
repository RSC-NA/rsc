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

    # The small label: "TEMPORARY CONTRACT · Elite"
    move: str
    # The player's name, already markdown-escaped
    name: str
    # "joins **Quantum** · Hex Systems", already markdown-escaped
    summary: str
    player_id: int
    colour: discord.Colour
    banner: Path
    created_at: datetime
    # The starter a substitute replaces
    player_out_id: int | None = None
    gm_id: int | None = None
    # Shown beside the text: a franchise logo or server icon URL, or a bundled image such as a free agent tier badge
    logo: str | Path | None = None

    def render(self) -> tuple[ui.LayoutView, list[discord.File]]:
        """The card and the files it references. Fresh Files each call, since a send consumes them."""
        # Built like the match result: label, then the name as the headline, then where they went.
        # Separate TextDisplays, since a heading after other text in one block gets extra space above it.
        texts = (ui.TextDisplay(f"-# {self.move}"), ui.TextDisplay(f"## {self.name}"), ui.TextDisplay(self.summary))
        files: list[discord.File] = []
        container = ui.Container(accent_colour=self.colour)
        if self.logo is None:
            for text in texts:
                container.add_item(text)
        else:
            if isinstance(self.logo, Path):
                logo = discord.File(self.logo, filename=self.logo.name)
                files.append(logo)
                thumbnail = ui.Thumbnail(logo)
            else:
                thumbnail = ui.Thumbnail(self.logo)
            container.add_item(ui.Section(*texts, accessory=thumbnail))

        gm = f"**GM** <@{self.gm_id}>" if self.gm_id else None
        if self.player_out_id:
            people = [f"**In** <@{self.player_id}> · **Out** <@{self.player_out_id}>", gm]
        else:
            people = [" · ".join(filter(None, [f"**Player** <@{self.player_id}>", gm]))]
        container.add_item(ui.Separator())
        # A TextDisplay, so these mentions ping; embed mentions never do
        container.add_item(ui.TextDisplay("\n".join(filter(None, people))))

        # The banner image is padded so it fills ~70% of the card, close to the old embed's size
        banner = discord.File(self.banner, filename=self.banner.name)
        files.append(banner)
        container.add_item(ui.Separator(visible=False, spacing=discord.SeparatorSpacing.small))
        container.add_item(ui.MediaGallery(discord.MediaGalleryItem(banner)))
        # The Discord ID wording matches the old embed footer, so one search finds old and new posts
        container.add_item(ui.TextDisplay(f"-# Discord ID: {self.player_id} · {discord.utils.format_dt(self.created_at, 'f')}"))

        view = ui.LayoutView(timeout=None)
        view.add_item(container)
        return view, files
