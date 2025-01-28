import logging

import discord
from discord.ui import TextInput

from rsc.views import ConfirmButton, DeclineButton

log = logging.getLogger("red.rsc.transactions.views")


class TradeInfo(discord.ui.TextInput):
    def __init__(self):
        super().__init__(
            label="announcement",
            placeholder="GM1 receives: ...",
            style=discord.TextStyle.paragraph,
            required=True,
        )

    async def callback(self, interaction: discord.Interaction):
        if self.view:
            self.view.announcement = self.value


class TradeAnnouncementView(discord.ui.View):
    def __init__(self, timeout: float = 30.0):
        self.announcement: str | None = None
        super().__init__(timeout=30.0)
        self.add_item(TradeInfo())
        self.add_item(ConfirmButton())
        self.add_item(DeclineButton())

    async def confirm(self, interaction: discord.Interaction):
        log.debug("Trade confirmed.")

    async def decline(self, interaction: discord.Interaction):
        log.debug("Trade declined.")


class TradeAnnouncementModal(discord.ui.Modal, title="Trade Announcement"):
    trade: TextInput = TextInput(
        label="Enter what GM receives",
        placeholder="GM receives...",
        style=discord.TextStyle.paragraph,
        required=True,
    )

    async def on_submit(self, interaction: discord.Interaction):
        await interaction.response.defer(ephemeral=True)
        if not self.trade:
            await interaction.followup.send(content="No trade data provided...", ephemeral=True)
            return
        self.stop()
