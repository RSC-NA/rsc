
import discord
from typing import Callable, Union
from rsc.const import DEFAULT_TIMEOUT
from rsc.embeds import ErrorEmbed, SuccessEmbed, LoadingEmbed
from rsc.views import AuthorOnlyView, ConfirmButton, DeclineButton

from typing import Optional


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
        prompt = discord.Embed(
            title="Sync Roles",
            description="You are about to sync data from the API directly into the discord server.\n\n**Are you sure you want to do this?**",
            color=discord.Color.orange(),
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
            embed=ErrorEmbed(
                title="Sync Canelled",
                description=f"You have cancelled syncing from the API.",
            ),
            view=None,
        )
        self.stop()