import logging
from collections.abc import Awaitable, Callable

import discord

from rsc.const import DEFAULT_TIMEOUT
from rsc.embeds import BlueEmbed, SuccessEmbed, YellowEmbed
from rsc.enums import EventAction, EventCategory, EventSeverity
from rsc.views import AuthorOnlyView, ConfirmButton, DeclineButton

log = logging.getLogger("red.rsc.events.views")

#: Called with (categories, actions, severities) whenever a selection changes.
FilterSaveCallback = Callable[[list[str], list[str], list[str]], Awaitable[None]]


class EventCategorySelect(discord.ui.Select):
    def __init__(self, selected: list[str]):
        options = [discord.SelectOption(label=c.full_name, value=c.value, default=c.value in selected) for c in EventCategory]
        super().__init__(
            placeholder="Categories to log (none selected = all)",
            min_values=0,
            max_values=len(options),
            options=options,
        )

    async def callback(self, interaction: discord.Interaction):
        if isinstance(self.view, EventFilterView):
            await self.view.update_categories(interaction, self.values)


class EventActionSelect(discord.ui.Select):
    def __init__(self, selected: list[str]):
        options = [discord.SelectOption(label=a.full_name, value=a.value, default=a.value in selected) for a in EventAction]
        super().__init__(
            placeholder="Actions to log (none selected = all)",
            min_values=0,
            max_values=len(options),
            options=options,
        )

    async def callback(self, interaction: discord.Interaction):
        if isinstance(self.view, EventFilterView):
            await self.view.update_actions(interaction, self.values)


class EventSeveritySelect(discord.ui.Select):
    def __init__(self, selected: list[str]):
        options = [discord.SelectOption(label=s.full_name, value=s.value, default=s.value in selected) for s in EventSeverity]
        super().__init__(
            placeholder="Severities to log (none selected = all)",
            min_values=0,
            max_values=len(options),
            options=options,
        )

    async def callback(self, interaction: discord.Interaction):
        if isinstance(self.view, EventFilterView):
            await self.view.update_severities(interaction, self.values)


class EventFilterView(AuthorOnlyView):
    """Pick which event categories, actions and severities reach the log channel.

    Filters are display only. They never reach the API: narrowing server side
    would keep the highest visible id below the true max and stall the watermark
    behind every excluded event.

    Each change is saved immediately via `on_save`, so there is no confirm step
    and a timeout loses nothing.
    """

    def __init__(
        self,
        interaction: discord.Interaction,
        *,
        categories: list[str],
        actions: list[str],
        severities: list[str],
        on_save: FilterSaveCallback,
        timeout: float = DEFAULT_TIMEOUT,
    ):
        super().__init__(interaction=interaction, timeout=timeout)
        self.categories = list(categories)
        self.actions = list(actions)
        self.severities = list(severities)
        self.on_save = on_save
        self.add_item(EventCategorySelect(self.categories))
        self.add_item(EventActionSelect(self.actions))
        self.add_item(EventSeveritySelect(self.severities))

    @staticmethod
    def summary(values: list[str]) -> str:
        if not values:
            return "All"
        return ", ".join(sorted(values))

    async def prompt(self):
        embed = BlueEmbed(
            title="League Event Filters",
            description=(
                "Select which categories and actions are posted to the event log channel.\n\n"
                "Leaving a menu empty logs **all** values for it. Filtering only affects what is "
                "posted to Discord. Every event is still processed and dispatched internally."
            ),
        )
        embed.add_field(name="Categories", value=self.summary(self.categories), inline=False)
        embed.add_field(name="Actions", value=self.summary(self.actions), inline=False)
        embed.add_field(name="Severities", value=self.summary(self.severities), inline=False)
        await self.interaction.response.send_message(embed=embed, view=self, ephemeral=True)

    async def update_categories(self, interaction: discord.Interaction, values: list[str]):
        self.categories = list(values)
        await self.save_and_render(interaction)

    async def update_actions(self, interaction: discord.Interaction, values: list[str]):
        self.actions = list(values)
        await self.save_and_render(interaction)

    async def update_severities(self, interaction: discord.Interaction, values: list[str]):
        self.severities = list(values)
        await self.save_and_render(interaction)

    async def save_and_render(self, interaction: discord.Interaction):
        await self.on_save(self.categories, self.actions, self.severities)
        embed = SuccessEmbed(
            title="Filters Updated",
            description="Changes are saved immediately. Dismiss this message when you are done.",
        )
        embed.add_field(name="Categories", value=self.summary(self.categories), inline=False)
        embed.add_field(name="Actions", value=self.summary(self.actions), inline=False)
        embed.add_field(name="Severities", value=self.summary(self.severities), inline=False)
        await interaction.response.edit_message(embed=embed, view=self)

    async def on_timeout(self):
        # Selections persist on each change, so a timeout is not a failure.
        if self.interaction:
            await self.interaction.edit_original_response(view=None)


class ConfirmCursorView(AuthorOnlyView):
    """Confirm a manual cursor move, which can replay a lot of events."""

    def __init__(
        self,
        interaction: discord.Interaction,
        current: int,
        target: int,
        timeout: float = DEFAULT_TIMEOUT,
    ):
        super().__init__(interaction=interaction, timeout=timeout)
        self.current = current
        self.target = target
        self.result = False
        self.add_item(ConfirmButton())
        self.add_item(DeclineButton())

    async def prompt(self):
        embed = YellowEmbed(
            title="Move League Event Cursor",
            description=(
                f"Move the confirmed cursor from **{self.current}** to **{self.target}**?\n\n"
                "Rewinding re-processes and re-posts every event above the new value, which can be "
                "a large number of messages."
            ),
        )
        await self.interaction.response.send_message(embed=embed, view=self, ephemeral=True)

    async def confirm(self, interaction: discord.Interaction):
        self.result = True
        await interaction.response.defer(ephemeral=True)
        self.stop()

    async def decline(self, interaction: discord.Interaction):
        self.result = False
        await interaction.response.defer(ephemeral=True)
        await self.interaction.edit_original_response(
            embed=BlueEmbed(title="Cancelled", description="The league event cursor was not changed."),
            view=None,
        )
        self.stop()
