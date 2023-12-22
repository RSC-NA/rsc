import logging
from enum import IntEnum

import discord

from rsc.const import DEFAULT_TIMEOUT
from rsc.embeds import LoadingEmbed, OrangeEmbed, RedEmbed
from rsc.types import RebrandTeamDict
from rsc.views import AuthorOnlyView, CancelButton, ConfirmButton, DeclineButton

log = logging.getLogger("red.rsc.admin.views")


class CreateState(IntEnum):
    START = 1
    TEAMS = 2
    CONFIRM = 3
    FINISHED = 4
    CANCELLED = 5
    NOTIERS = 6


class ConfirmSyncView(AuthorOnlyView):
    def __init__(
        self,
        interaction: discord.Interaction,
        timeout: float = DEFAULT_TIMEOUT,
    ):
        super().__init__(interaction=interaction, timeout=timeout)
        self.add_item(ConfirmButton())
        self.add_item(DeclineButton())
        self.result = False

    async def prompt(self):
        """Note: The prompt does not all wait()"""
        prompt = OrangeEmbed(
            title="API Sync",
            description=(
                "You are about to sync data from the API directly into the discord server.\n\n"
                "**Are you sure you want to do this?**"
            ),
        )
        await self.interaction.response.send_message(
            embed=prompt, view=self, ephemeral=True
        )

    async def confirm(self, interaction: discord.Interaction):
        self.result = True
        await self.interaction.edit_original_response(
            embed=LoadingEmbed(title="Processing Sync"),
            view=None,
        )
        self.stop()

    async def decline(self, interaction: discord.Interaction):
        self.result = False
        await self.interaction.edit_original_response(
            embed=RedEmbed(
                title="Sync Canelled",
                description="You have cancelled syncing from the API.",
            ),
            view=None,
        )
        self.stop()


class RebrandFranchiseView(AuthorOnlyView):
    def __init__(
        self,
        interaction: discord.Interaction,
        old_name: str,
        name: str,
        prefix: str,
        teams: list[RebrandTeamDict],
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
        embed = OrangeEmbed(
            title="Rebrand Franchise",
            description=(
                f"Are you sure you want to rebrand **{self.old_name}** to the following?\n\n"
                f"**Name**: {self.name}\n"
                f"**Prefix**: {self.prefix}"
            ),
        )
        embed.add_field(
            name="Tier", value="\n".join([t["tier"] for t in self.teams]), inline=True
        )
        embed.add_field(
            name="Teams", value="\n".join(t["name"] for t in self.teams), inline=True
        )
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
            embed=RedEmbed(
                title="Cancelled",
                description="You have cancelled deleting this franchise.",
            ),
            view=None,
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
        embed = OrangeEmbed(
            title="Delete Franchise",
            description="Are you sure you want to delete the following franchise?",
            color=discord.Color.orange(),
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
            embed=RedEmbed(
                title="Cancelled",
                description="You have cancelled deleting this franchise.",
            ),
            view=None,
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
        embed = OrangeEmbed(
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
            embed=RedEmbed(
                title="Cancelled",
                description="You have cancelled creating a new franchise.",
            ),
            view=None,
        )
        self.stop()


class TransferFranchiseView(AuthorOnlyView):
    def __init__(
        self,
        interaction: discord.Interaction,
        franchise: str,
        gm: discord.Member,
        timeout: float = 30.0,
    ):
        super().__init__(interaction=interaction, timeout=timeout)
        self.gm = gm
        self.franchise = franchise
        self.result = False
        self.add_item(ConfirmButton())
        self.add_item(CancelButton())

    async def prompt(self):
        """Confirm transfer franchise"""
        embed = OrangeEmbed(
            title="Transfer Franchise",
            description="Are you sure you want to transfer the following franchise?",
        )
        embed.add_field(name="Franchise", value=self.franchise, inline=True)
        embed.add_field(name="New GM", value=self.gm.mention, inline=True)
        await self.interaction.response.send_message(
            embed=embed,
            view=self,
            ephemeral=True,
        )

    async def confirm(self, interaction: discord.Interaction):
        log.debug("User confirmed franchise transfer")
        self.result = True
        self.stop()

    async def decline(self, interaction: discord.Interaction):
        log.debug("Franchise transfer cancelled by user...")
        self.result = False
        await self.interaction.edit_original_response(
            embed=RedEmbed(
                title="Cancelled",
                description="You have cancelled transferring franchise.",
            ),
            view=None,
        )
        self.stop()
