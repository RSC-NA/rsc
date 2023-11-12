import discord
import logging

from rscapi.models.league import League

from rsc.const import DEFAULT_TIMEOUT

from typing import List, Optional

log = logging.getLogger("red.rsc.views")


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
        timeout=DEFAULT_TIMEOUT,
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
