import logging
import discord
from discord.ui import TextInput, UserSelect

from rsc.views import ConfirmButton, DeclineButton

from typing import Optional

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
        log.debug(f"Trade Data")

    async def decline(self, interaction: discord.Interaction):
        log.debug("Trade declined.")


class TradeAnnouncementModal(discord.ui.Modal, title="Trade Announcement"):
    gm1 = UserSelect(placeholder="General Manager 1")
    trade = TextInput(
        label="Enter what GM receives",
        placeholder="GM receives...",
        style=discord.TextStyle.paragraph,
        required=True,
    )
    gm2 = UserSelect(placeholder="General Manager 2")
    trade2 = TextInput(
        label="Enter what GM receives",
        placeholder="GM receives...",
        style=discord.TextStyle.paragraph,
        required=True,
    )
    # gm3 = UserSelect(placeholder="General Manager 3")
    # trade3 = TextInput(
    #     label="Enter what GM receives",
    #     placeholder="GM receives...",
    #     style=discord.TextStyle.paragraph,
    #     required=False
    # )
    # gm4 = UserSelect(placeholder="General Manager 4")
    # trade4 = TextInput(
    #     label="Enter what GM receives",
    #     placeholder="GM receives...",
    #     style=discord.TextStyle.paragraph,
    #     required=False
    # )

    async def on_submit(self, interaction: discord.Interaction):
        if not self.trade:
            await interaction.response.send_message(
                content="No trade announcement provided.", ephemeral=True
            )
            return

        await interaction.response.send_message(content="Done.", ephemeral=True)
