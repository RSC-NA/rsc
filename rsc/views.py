import discord
import logging

from rscapi.models.league import League

from rsc.const import DEFAULT_TIMEOUT

from typing import List, Optional, Union, Callable

log = logging.getLogger("red.rsc.views")


# Generic View structures for use in any module

class AuthorOnlyView(discord.ui.View):
    """View class designed to only interact with the interaction author. Can subclass"""

    def __init__(
        self, interaction: discord.Interaction, timeout: float=DEFAULT_TIMEOUT
    ):
        super().__init__()
        self.timeout = timeout
        self.interaction = interaction
        self.author = interaction.user

    async def on_timeout(self):
        """Display time out message if we have reference to original"""
        if self.message:
            embed = discord.Embed(
                title="Time out",
                description=f"{self.author.mention} Sorry, you didn't respond quick enough. Please try again.",
                colour=discord.Colour.orange(),
            )

            await self.message.edit(embed=embed, view=None)

    async def interaction_check(self, interaction: discord.Interaction) -> bool:
        """Check if the interaction user is the author. Allow or deny callbacks"""
        if interaction.user != self.author:
            return False
        return True


class ConfirmButton(discord.ui.Button):
    """Generic Confirm Button"""
    def __init__(self):
        super().__init__(label="Confirm", custom_id="confirmed", style=discord.ButtonStyle.green)

    async def callback(self, interaction: discord.Interaction):
        """Button will callback to the containing view `confirm()` function"""
        await self.view.confirm()

class DeclineButton(discord.ui.Button):
    """Generic Decline Button"""
    def __init__(self):
        super().__init__(label="Decline", custom_id="declined", style=discord.ButtonStyle.red)

    async def callback(self, interaction: discord.Interaction):
        """Button will callback to the containing view `decline()` function"""
        await self.view.decline()


# RSC Core

class LeagueSelect(discord.ui.Select):
    def __init__(self, leagues: List[League]):
        super().__init__(placeholder="Select a league...")
        self.build(leagues)

    def build(self, leagues: List[League]):
        for league in leagues:
            self.add_option(label=league.name, value=str(league.id))

    async def callback(self, interaction: discord.Interaction):
        await self.view.save_selection(interaction, self.values)


class LeagueSelectView(discord.ui.View):
    def __init__(
        self,
        interaction: discord.Interaction,
        leagues: List[League],
        timeout: float=DEFAULT_TIMEOUT,
    ):
        self.result: Optional[int] = None
        self.interaction = interaction
        self.leagues = leagues
        super().__init__(timeout=timeout)
        self.add_item(LeagueSelect(self.leagues))

    async def on_timeout(self):
        """Display time out message if we have reference to original"""
        embed = discord.Embed(
            title="Time out",
            description=f"Sorry, you didn't respond quick enough. Please try again.",
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
        self, interaction: discord.Interaction, league_id: List[str]
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
