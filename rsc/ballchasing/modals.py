import logging

import discord
from discord.ui import TextInput, TextDisplay, FileUpload, Label


log = logging.getLogger("red.rsc.ballchasing.modals")


class ReportMatchModal(discord.ui.Modal, title="Report Match"):
    def __init__(self, home_team: str, away_team: str, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.home_team = home_team
        self.away_team = away_team
        self.home_wins = 0
        self.away_wins = 0
        self.replays: list[discord.Attachment] = []
        self.add_components()

    def add_components(self) -> None:
        # Instructions
        log.debug("Adding instruction components to report match modal")
        self.add_item(TextDisplay(content="If you encounter any issues, please DM the ModMail bot."))

        # Scores
        log.debug("Creating score input components")
        self.home_score = Label(
            text=f"Home Team - {self.home_team}",
            # description=f"Enter number of wins for {self.home_team}",
            component=TextInput(style=discord.TextStyle.short, placeholder="Enter wins here... (Ex: 2)", max_length=1, required=True),
        )
        self.away_score = Label(
            text=f"Away Team - {self.away_team}",
            # description=f"Enter number of wins for {self.away_team}",
            component=TextInput(style=discord.TextStyle.short, placeholder="Enter wins here... (Ex: 2)", max_length=1, required=True),
        )
        self.add_item(self.home_score)
        self.add_item(self.away_score)

        # Uploads
        log.debug("Adding replay upload component")
        self.upload_replays = Label(
            text="Replays",
            description="Upload replay files for the match",
            component=FileUpload(required=True, min_values=1, max_values=10),
        )
        self.add_item(self.upload_replays)
        log.debug("Done creating modal components")

    async def on_submit(self, interaction: discord.Interaction) -> None:
        if not (
            isinstance(self.home_score.component, TextInput)
            and isinstance(self.away_score.component, TextInput)
            and isinstance(self.upload_replays.component, FileUpload)
        ):
            await interaction.response.send_message(
                "An unknown error occurred while processing the scores. Please try again.", ephemeral=True
            )
            return

        # Parse score
        try:
            self.home_wins = int(self.home_score.component.value)
            self.away_wins = int(self.away_score.component.value)
        except ValueError:
            await interaction.response.send_message("Game scores must be integers...", ephemeral=True)
            return

        if self.home_wins < 0 or self.away_wins < 0:
            await interaction.response.send_message("Scores cannot be negative.", ephemeral=True)
            return

        # Fetch replays
        self.replays = self.upload_replays.component.values

        await interaction.response.defer(ephemeral=True)
