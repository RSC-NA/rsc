import logging
from enum import IntEnum

import discord
from discord.ui import ActionRow, Container, Separator, TextDisplay

from rsc.const import DEFAULT_TIMEOUT
from rsc.views import AuthorOnlyLayoutView

log = logging.getLogger("red.rsc.members.views.intent")


class IntentState(IntEnum):
    DECLARE = 0
    FINISHED = 1
    CANCELLED = 2


class _IntentSelect(discord.ui.Select):
    def __init__(self):
        super().__init__(placeholder="What is your intent?", min_values=1, max_values=1)
        self.add_option(label="Returning next season", value="yes", emoji="\N{WHITE HEAVY CHECK MARK}")
        self.add_option(label="Not returning next season", value="no", emoji="\N{CROSS MARK}")

    async def callback(self, interaction: discord.Interaction):
        view: IntentToPlayView = self.view  # type: ignore[assignment]
        view.result = self.values[0] == "yes"
        # Mark chosen option as default so it shows when disabled
        for opt in self.options:
            opt.default = opt.value == self.values[0]
        await interaction.response.defer(ephemeral=True)


class _ConfirmButton(discord.ui.Button):
    def __init__(self):
        super().__init__(
            label="Confirm",
            style=discord.ButtonStyle.success,
        )

    async def callback(self, interaction: discord.Interaction):
        view: IntentToPlayView = self.view  # type: ignore[assignment]
        await view.confirm(interaction)


class _CancelButton(discord.ui.Button):
    def __init__(self):
        super().__init__(
            label="Cancel",
            style=discord.ButtonStyle.danger,
        )

    async def callback(self, interaction: discord.Interaction):
        view: IntentToPlayView = self.view  # type: ignore[assignment]
        view.state = IntentState.CANCELLED
        view.stop()
        await interaction.response.defer(ephemeral=True)


class IntentToPlayView(AuthorOnlyLayoutView):
    def __init__(self, interaction: discord.Interaction, timeout: float = DEFAULT_TIMEOUT):
        super().__init__(interaction=interaction, timeout=timeout)
        self.state = IntentState.DECLARE
        self.result = False

        self._select = _IntentSelect()
        self._confirm_btn = _ConfirmButton()
        self._cancel_btn = _CancelButton()

        self._container = Container(
            TextDisplay("## \N{CLIPBOARD}  Intent to Play"),
            TextDisplay(
                "Please declare your intent for the **next season** of RSC.\n\nSelect an option below and press **Confirm** to submit."
            ),
            Separator(spacing=discord.SeparatorSpacing.small),
            ActionRow(self._select),
            ActionRow(self._confirm_btn, self._cancel_btn),
            accent_colour=discord.Colour.blue(),
        )
        self.add_item(self._container)

    async def prompt(self):
        """Send the initial layout view message."""
        await self.interaction.response.send_message(view=self, ephemeral=True)

    async def confirm(self, interaction: discord.Interaction):
        """User pressed Confirm button."""
        if not self._select.values:
            return await interaction.response.send_message(
                content="Please select returning or not returning in the drop down.",
                ephemeral=True,
            )
        log.debug(f"[INTENT] User confirmed: returning={self.result}")
        self._select.disabled = True
        self._confirm_btn.disabled = True
        self._cancel_btn.disabled = True
        self._container.accent_colour = discord.Colour.green()
        self.state = IntentState.FINISHED
        self.stop()
        await interaction.response.edit_message(view=self)
