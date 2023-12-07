import discord
import logging

from discord.ui import TextInput

from typing import List, Dict

log = logging.getLogger("red.rsc.franchises.modals")


class FranchiseRebrandModal(discord.ui.Modal, title="Franchise Rebrand"):
    name_input: TextInput = TextInput(
        label="Name", style=discord.TextStyle.short, required=True
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
        self.teams: List[str] = []

    async def on_submit(self, interaction: discord.Interaction):
        await self.parse_data()
        self.interaction = interaction

    async def parse_data(self):
        self.name = self.name_input.value
        self.prefix = self.prefix_input.value
        self.teams = self.team_input.value.splitlines()
