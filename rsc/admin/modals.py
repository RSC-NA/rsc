import logging

import discord
from discord.ui import TextInput

from rsc.embeds import SuccessEmbed

log = logging.getLogger("red.rsc.franchises.modals")


class LeagueDatesModal(discord.ui.Modal, title="Import League Dates"):
    date_input: TextInput = TextInput(
        label="Date String",
        style=discord.TextStyle.paragraph,
        placeholder="Enter dates here with formatting...",
        required=True,
    )

    async def on_submit(self, interaction: discord.Interaction):
        embed = SuccessEmbed(description="Dates command has been configured.")
        await interaction.response.send_message(embed=embed, ephemeral=True)


class IntentMissingModal(discord.ui.Modal, title="Missing Intent to Play Message"):
    intent_msg: TextInput = TextInput(
        label="Message to missing players",
        style=discord.TextStyle.paragraph,
        placeholder="Enter the message to ping missing intent players here...",
        required=True,
    )

    async def on_submit(self, interaction: discord.Interaction):
        embed = SuccessEmbed(
            description="Missing intent ping message has been configured."
        )
        await interaction.response.send_message(embed=embed, ephemeral=True)


class FranchiseRebrandModal(discord.ui.Modal, title="Franchise Rebrand"):
    name_input: TextInput = TextInput(
        label="Name",
        style=discord.TextStyle.short,
        required=True,
    )
    prefix_input: TextInput = TextInput(
        label="Prefix", style=discord.TextStyle.short, required=True
    )
    team_input: TextInput = TextInput(
        label="Teams (New line sperated, high to low tiers)",
        style=discord.TextStyle.paragraph,
        required=True,
    )

    def __init__(self):
        super().__init__()
        self.name: str = ""
        self.prefix: str = ""
        self.teams: list[str] = []

    async def on_submit(self, interaction: discord.Interaction):
        await self.parse_data()
        self.interaction = interaction

    async def parse_data(self):
        self.name = self.name_input.value
        self.prefix = self.prefix_input.value
        self.teams = self.team_input.value.splitlines()
