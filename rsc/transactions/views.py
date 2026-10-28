import logging

import discord
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
