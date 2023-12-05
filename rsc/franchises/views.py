import discord
import logging

from discord.ui import TextInput
from rscapi.models.tier import Tier

from rsc.const import DEFAULT_TIMEOUT, BEHAVIOR_RULES_URL
from rsc.views import (
    AgreeButton,
    AuthorOnlyView,
    CancelButton,
    ConfirmButton,
    DeclineButton,
    LinkButton,
    NextButton,
    NoButton,
    YesButton,
)

from rsc.embeds import SuccessEmbed, ErrorEmbed, BlueEmbed

from enum import StrEnum, IntEnum

from typing import List, Dict

log = logging.getLogger("red.rsc.franchises.views")


class CreateState(IntEnum):
    START = 1
    TEAMS = 2
    CONFIRM = 3
    FINISHED = 4
    CANCELLED = 5
    NOTIERS = 6


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


class RebrandFranchiseView(AuthorOnlyView):
    def __init__(
        self,
        interaction: discord.Interaction,
        old_name: str,
        name: str,
        prefix: str,
        teams: Dict[str, str],
        timeout: float = 30.0,
    ):
        super().__init__(interaction=interaction, timeout=timeout)
        self.old_name = old_name
        self.name = name
        self.prefix = prefix
        self.teams = teams
        self.result = False
        self.add_item(ConfirmButton())
        self.add_item(CancelButton())

    async def prompt(self):
        """Confirm franchise deletion"""
        tier_names = self.teams.keys()
        team_names = self.teams.values()
        embed = BlueEmbed(
            title="Rebrand Franchise",
            description=(
                f"Are you sure you want to rebrand **{self.old_name}** to the following?\n\n"
                f"**Name**: {self.name}\n"
                f"**Prefix**: {self.prefix}"
            ),
        )
        embed.add_field(name="Tier", value="\n".join(tier_names), inline=True)
        embed.add_field(name="Teams", value="\n".join(team_names), inline=True)
        await self.interaction.response.send_message(
            embed=embed,
            view=self,
            ephemeral=True,
        )

    async def confirm(self, interaction: discord.Interaction):
        log.debug("User confirmed franchise deletion")
        self.result = True
        self.stop()

    async def decline(self, interaction: discord.Interaction):
        log.debug("Franchise deletion cancelled by user...")
        self.result = False
        await self.interaction.edit_original_response(
            embed=ErrorEmbed(
                title="Cancelled",
                description="You have cancelled deleting this franchise.",
            ),
            view=None
        )
        self.stop()



class DeleteFranchiseView(AuthorOnlyView):
    def __init__(
        self,
        interaction: discord.Interaction,
        name: str,
        timeout: float = 30.0,
    ):
        super().__init__(interaction=interaction, timeout=timeout)
        self.name = name
        self.result = False
        self.add_item(ConfirmButton())
        self.add_item(CancelButton())

    async def prompt(self):
        """Confirm franchise deletion"""
        embed = discord.Embed(
            title="Delete Franchise",
            description="Are you sure you want to delete the following franchise?",
            color=discord.Color.orange()
        )
        embed.add_field(name="Name", value=self.name, inline=True)
        await self.interaction.followup.send(
            embed=embed,
            view=self,
            ephemeral=True,
        )

    async def confirm(self, interaction: discord.Interaction):
        log.debug("User confirmed franchise deletion")
        self.result = True
        self.stop()

    async def decline(self, interaction: discord.Interaction):
        log.debug("Franchise deletion cancelled by user...")
        self.result = False
        await self.interaction.edit_original_response(
            embed=ErrorEmbed(
                title="Cancelled",
                description="You have cancelled deleting this franchise.",
            ),
            view=None
        )
        self.stop()


class CreateFranchiseView(AuthorOnlyView):
    def __init__(
        self,
        interaction: discord.Interaction,
        name: str,
        gm: discord.Member,
        timeout: float = 30.0,
    ):
        super().__init__(interaction=interaction, timeout=timeout)
        self.gm = gm
        self.name = name
        self.result = False
        self.add_item(ConfirmButton())
        self.add_item(CancelButton())

    async def prompt(self):
        """Confirm franchise name and GM"""
        embed = BlueEmbed(
            title="Create Franchise",
            description="Are you sure you want to create the following franchise?",
        )
        embed.add_field(name="Name", value=self.name, inline=True)
        embed.add_field(name="GM", value=self.gm.mention, inline=True)
        await self.interaction.response.send_message(
            embed=embed,
            view=self,
            ephemeral=True,
        )

    async def confirm(self, interaction: discord.Interaction):
        log.debug("User confirmed franchise creation")
        self.result = True
        self.stop()

    async def decline(self, interaction: discord.Interaction):
        log.debug("Franchise creation cancelled by user...")
        self.result = False
        await self.interaction.edit_original_response(
            embed=ErrorEmbed(
                title="Cancelled",
                description="You have cancelled creating a new franchise.",
            ),
            view=None
        )
        self.stop()
