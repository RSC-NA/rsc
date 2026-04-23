import discord
from discord.ui import TextInput


class CutMsgModal(discord.ui.Modal, title="RSC Cut Message"):
    cutmsg: TextInput = TextInput(
        label="Cut Message",
        style=discord.TextStyle.paragraph,
        placeholder="Enter cut message with formatting here...",
        max_length=4000,
        required=True,
    )

    async def on_submit(self, interaction: discord.Interaction):
        await interaction.response.defer(ephemeral=True)


class TransactionAnnouncementModal(discord.ui.Modal, title="Transaction Announcement"):
    message: TextInput = TextInput(
        label="Announcement Message",
        style=discord.TextStyle.paragraph,
        placeholder="Enter announcement text here...",
        max_length=1000,
        required=True,
    )

    async def on_submit(self, interaction: discord.Interaction):
        await interaction.response.defer(ephemeral=True)
        self.stop()
