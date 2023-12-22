import logging

import discord

from rsc.const import DEFAULT_TIMEOUT
from rsc.embeds import OrangeEmbed, RedEmbed
from rsc.enums import BulkRoleAction
from rsc.views import AuthorOnlyView, CancelButton, ConfirmButton

log = logging.getLogger("red.rsc.utils.views")


class BulkRoleConfirmView(AuthorOnlyView):
    def __init__(
        self,
        interaction: discord.Interaction,
        action: BulkRoleAction,
        role: discord.Role,
        count: int,
        timeout: float = DEFAULT_TIMEOUT,
    ):
        super().__init__(interaction=interaction, timeout=timeout)
        self.action = action
        self.count = count
        self.role = role
        self.add_item(ConfirmButton())
        self.add_item(CancelButton())

    async def prompt(self):
        """Confirm bulk role add or removal"""
        embed = OrangeEmbed(
            title=f"Bulk {self.action.value.capitalize()} Role",
            description=(
                f"This action will affect **{self.count}** user(s) in {self.role.mention}\n\n"
                "**Are you sure you want to do this?**"
            ),
        )
        await self.interaction.response.send_message(
            embed=embed,
            view=self,
            ephemeral=True,
        )

    async def confirm(self, interaction: discord.Interaction):
        log.debug("User confirmed bulk role change")
        self.result = True
        self.stop()

    async def decline(self, interaction: discord.Interaction):
        log.debug("User cancelled bulk role change")
        self.result = False
        await self.interaction.edit_original_response(
            embed=RedEmbed(
                title="Cancelled",
                description="You have cancelled the bulk role action.",
            ),
            view=None,
        )
        self.stop()
