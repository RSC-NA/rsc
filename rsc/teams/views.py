import discord

from rsc.abc import RSCMixIn


class RosterView(discord.ui.View):
    def __init__(
        self,
        mixin: RSCMixIn,
        player: discord.Member,
        team: str,
    ):
        super().__init__()
        self.mixin = mixin
        self.player = player
        self.team = team

    @discord.ui.button(label="Team Roster", style=discord.ButtonStyle.primary)
    async def display_team_roster(self, button, interaction):
        pass
