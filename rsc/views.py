import logging

import discord
from discord.ui import TextInput
from rscapi.models.league import League

from rsc.const import DEFAULT_TIMEOUT

log = logging.getLogger("red.rsc.views")


# Generic View structures for use in any module


class AuthorOnlyView(discord.ui.View):
    """View class designed to only interact with the interaction author. Can subclass"""

    def __init__(
        self, interaction: discord.Interaction, timeout: float = DEFAULT_TIMEOUT
    ):
        super().__init__(timeout=timeout)
        self.interaction = interaction
        self.author = interaction.user

    async def on_timeout(self):
        """Display time out message if we have reference to original"""
        if self.interaction:
            embed = discord.Embed(
                title="Time out",
                description="Sorry, you didn't respond quick enough. Please try again.",
                colour=discord.Colour.orange(),
            )

            await self.interaction.edit_original_response(embed=embed, view=None)

    async def interaction_check(self, interaction: discord.Interaction) -> bool:
        """Check if the interaction user is the author. Allow or deny callbacks"""
        if interaction.user != self.author:
            return False
        return True


# Generic Buttons


class ConfirmButton(discord.ui.Button):
    """Generic Confirm Button"""

    def __init__(self):
        super().__init__(
            label="Confirm", custom_id="confirmed", style=discord.ButtonStyle.green
        )

    async def callback(self, interaction: discord.Interaction):
        """Button will callback to the containing view `confirm()` function"""
        await self.view.confirm(interaction)  # type: ignore


class DeclineButton(discord.ui.Button):
    """Generic Decline Button"""

    def __init__(self):
        super().__init__(
            label="Decline", custom_id="declined", style=discord.ButtonStyle.red
        )

    async def callback(self, interaction: discord.Interaction):
        """Button will callback to the containing view `decline()` function"""
        await self.view.decline(interaction)  # type: ignore


class CancelButton(discord.ui.Button):
    """Generic Cancel Button"""

    def __init__(self):
        super().__init__(
            label="Cancel", custom_id="cancel", style=discord.ButtonStyle.red
        )

    async def callback(self, interaction: discord.Interaction):
        """Button will callback to the containing view `cancel()` function"""
        await self.view.decline(interaction)  # type: ignore


class NextButton(discord.ui.Button):
    """Generic Next Button"""

    def __init__(self):
        super().__init__(
            label="Next", custom_id="next", style=discord.ButtonStyle.green
        )

    async def callback(self, interaction: discord.Interaction):
        """Button will callback to the containing view `decline()` function"""
        await self.view.confirm(interaction)  # type: ignore


class NoButton(discord.ui.Button):
    """Generic No Button"""

    def __init__(self):
        super().__init__(label="No", custom_id="no", style=discord.ButtonStyle.red)

    async def callback(self, interaction: discord.Interaction):
        """Button will callback to the containing view `no()` function"""
        await self.view.decline(interaction)  # type: ignore


class YesButton(discord.ui.Button):
    """Generic Yes Button"""

    def __init__(self):
        super().__init__(label="Yes", custom_id="yes", style=discord.ButtonStyle.green)

    async def callback(self, interaction: discord.Interaction):
        """Button will callback to the containing view `confirm()` function"""
        await self.view.confirm(interaction)  # type: ignore


class AgreeButton(discord.ui.Button):
    """Generic Agree Button"""

    def __init__(self):
        super().__init__(
            label="Agree", custom_id="agree", style=discord.ButtonStyle.green
        )

    async def callback(self, interaction: discord.Interaction):
        """Button will callback to the containing view `confirm()` function"""
        await self.view.confirm(interaction)  # type: ignore


class LinkButton(discord.ui.Button):
    def __init__(self, label: str, url: str):
        super().__init__(label=label, url=url, style=discord.ButtonStyle.link)


# RSC League Selection


class LeagueSelect(discord.ui.Select):
    def __init__(self, leagues: list[League]):
        super().__init__(placeholder="Select a league...")
        self.build(leagues)

    def build(self, leagues: list[League]):
        for league in leagues:
            self.add_option(label=league.name, value=str(league.id))

    async def callback(self, interaction: discord.Interaction):
        await self.view.save_selection(interaction, self.values)


class LeagueSelectView(AuthorOnlyView):
    def __init__(
        self,
        interaction: discord.Interaction,
        leagues: list[League],
        timeout: float = DEFAULT_TIMEOUT,
    ):
        self.result: int | None = None
        self.interaction = interaction
        self.leagues = leagues
        super().__init__(timeout=timeout)
        self.add_item(LeagueSelect(self.leagues))

    async def on_timeout(self):
        """Display time out message if we have reference to original"""
        embed = discord.Embed(
            title="Time out",
            description="Sorry, you didn't respond quick enough. Please try again.",
            colour=discord.Colour.orange(),
        )
        await self.interaction.edit_original_response(embed=embed, view=None)

    async def prompt(self):
        embed = discord.Embed(
            title="RSC League Selection",
            description="Please select the appropriate league from the drop down",
            color=discord.Color.blue(),
        )
        await self.interaction.response.send_message(
            embed=embed, view=self, ephemeral=True
        )

    async def save_selection(
        self, interaction: discord.Interaction, league_id: list[str]
    ):
        log.debug(f"League Selection: {league_id}")
        self.result = int(league_id[0])
        league = next((x for x in self.leagues if x.id == self.result))
        embed = discord.Embed(
            title="RSC League Configured",
            description=f"League has been set to **{league.name}**",
            color=discord.Color.green(),
        )
        await self.interaction.edit_original_response(embed=embed, view=None)
        self.stop()


# RSC Setup Modal


class RSCSetupModal(discord.ui.Modal, title="RSC Setup"):
    url: TextInput = TextInput(
        label="Provide the RSC API url.",
        placeholder="https://staging-api.rscna.com/api/v1",
        min_length=10,  # Url size validation
        style=discord.TextStyle.short,
        required=True,
    )
    key: TextInput = TextInput(
        label="Provide your RSC API key",
        placeholder="...",
        min_length=30,  # Key size validation
        style=discord.TextStyle.short,
        required=True,
    )

    async def on_submit(self, interaction: discord.Interaction):
        await interaction.response.defer(ephemeral=True)
