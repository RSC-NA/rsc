import discord

from rsc.const import DEFAULT_TIMEOUT
from rsc.embeds import ErrorEmbed, SuccessEmbed
from rsc.views import AuthorOnlyView, ConfirmButton, DeclineButton


class CheckInView(AuthorOnlyView):
    def __init__(
        self,
        interaction: discord.Interaction,
        tier: str,
        color: discord.Color | None = None,
        timeout: float = DEFAULT_TIMEOUT,
    ):
        super().__init__(interaction=interaction, timeout=timeout)
        self.add_item(ConfirmButton())
        self.add_item(DeclineButton())
        self.tier = tier
        self.color = color or discord.Color.blue()
        self.result = False

    async def prompt(self):
        prompt = discord.Embed(
            title="Check In",
            description=(
                "By checking in you are letting GMs know that you are available to play."
            ),
            color=self.color,
        )
        prompt.add_field(name="Tier", value=self.tier, inline=False)
        await self.interaction.response.send_message(
            embed=prompt, view=self, ephemeral=True
        )
        await self.wait()

    async def confirm(self, interaction: discord.Interaction):
        self.result = True
        await self.interaction.edit_original_response(
            embed=SuccessEmbed(
                title="Checked In",
                description="Thank you for checking in! GMs will now be able to see that you're available.",
            ),
            view=None,
        )
        self.stop()

    async def decline(self, interaction: discord.Interaction):
        self.result = False
        await self.interaction.edit_original_response(
            embed=ErrorEmbed(
                title="Unlucky...",
                description="You were not checked in. If you wish to check in, use the command again.",
            ),
            view=None,
        )
        self.stop()


class CheckOutView(AuthorOnlyView):
    def __init__(
        self,
        interaction: discord.Interaction,
        tier: str,
        color: discord.Color | None = None,
        timeout: float = DEFAULT_TIMEOUT,
    ):
        super().__init__(interaction=interaction, timeout=timeout)
        self.add_item(ConfirmButton())
        self.add_item(DeclineButton())
        self.tier = tier
        self.color = color or discord.Color.yellow()
        self.result = False

    async def prompt(self):
        prompt = discord.Embed(
            title="Check Out",
            description=(
                "You are currently checked in as available for the following match day and tier.\n\n"
                "Do you wish to take yourself off the availability list?"
            ),
            color=self.color,
        )
        prompt.add_field(name="Tier", value=self.tier, inline=False)
        await self.interaction.response.send_message(
            embed=prompt, view=self, ephemeral=True
        )
        await self.wait()

    async def confirm(self, interaction: discord.Interaction):
        self.result = True
        await self.interaction.edit_original_response(
            embed=SuccessEmbed(
                title="Checked Out",
                description=(
                    "You have been removed from the available free agent list.\n\n"
                    "Thank you for updating your availability."
                ),
            ),
            view=None,
        )
        self.stop()

    async def decline(self, interaction: discord.Interaction):
        self.result = False
        await self.interaction.edit_original_response(
            embed=ErrorEmbed(
                title="Great news!",
                description="You are still checked in.\n\nIf you wish to check out, please use the command again.",
            ),
            view=None,
        )
        self.stop()
