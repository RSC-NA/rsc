import logging
from enum import StrEnum
from random import choice, randint
from typing import Final

import discord
from redbot.core import app_commands

from rsc.abc import RSCMixIn

log = logging.getLogger("red.rsc.extras")


class RPS(StrEnum):
    rock = "\N{MOYAI}"
    paper = "\N{PAGE FACING UP}"
    scissors = "\N{BLACK SCISSORS}\N{VARIATION SELECTOR-16}"


class RPSOptions(StrEnum):
    rock = "rock"
    paper = "paper"
    scissors = "scissors"


class RPSParser:
    def __init__(self, argument: str):
        argument = argument.lower()
        match argument:
            case "rock":
                self.choice = RPS.rock
            case "paper":
                self.choice = RPS.paper
            case "scissors":
                self.choice = RPS.scissors


MAX_ROLL: Final[int] = 2**63 - 1


class ExtrasMixIn(RSCMixIn):
    ball = [
        "As I see it, yes",
        "It is certain",
        "It is decidedly so",
        "Most likely",
        "Outlook good",
        "Signs point to yes",
        "Without a doubt",
        "Yes",
        "Yes - definitely",
        "You may rely on it",
        "Reply hazy, try again",
        "Ask again later",
        "Better not tell you now",
        "Cannot predict now",
        "Concentrate and ask again",
        "Don't count on it",
        "My reply is no",
        "My sources say no",
        "Outlook not so good",
        "Very doubtful",
    ]

    def __init__(self):
        log.debug("Initializing ExtrasMixIn")
        super().__init__()

    # App Commands

    @app_commands.command(name="8ball", description="Ask the magic 8 ball a question")  # type: ignore[type-var]
    @app_commands.guild_only
    async def _magic_8ball(self, interaction: discord.Interaction, question: str):
        """Ask 8 ball a question.

        Question must end with a question mark.
        """
        if question.endswith("?") and question != "?":
            await interaction.response.send_message(f"{interaction.user.mention}: **{question}**\n\n`{choice(self.ball)}`")  # noqa: S311
        else:
            await interaction.response.send_message("That doesn't look like a question.")

    @app_commands.command(name="roll", description="Roll a random number")  # type: ignore[type-var]
    @app_commands.guild_only
    async def _roll_number(self, interaction: discord.Interaction, number: int = 100):
        """Roll a random number.

        The result will be between 1 and `<number>`.

        `<number>` defaults to 100.
        """
        author = interaction.user
        if 1 < number <= MAX_ROLL:
            n = randint(1, number)  # noqa: S311
            await interaction.response.send_message(f"{author.mention} :game_die: {n} :game_die:")
        elif number <= 1:
            await interaction.response.send_message(f"{author.mention} Maybe higher than 1? ;P")
        else:
            await interaction.response.send_message(f"{author.mention} Max allowed number is {MAX_ROLL}.")

    @app_commands.command(name="rps", description="Rock, Paper, Scissors")  # type: ignore[type-var]
    @app_commands.guild_only
    async def _rock_paper_scissors(self, interaction: discord.Interaction, your_choice: RPSOptions):
        """Play Rock Paper Scissors."""
        author = interaction.user
        player_choice = RPSParser(your_choice.value).choice
        if not player_choice:
            return await interaction.response.send_message("This isn't a valid option. Try rock, paper, or scissors")

        red_choice = choice((RPS.rock, RPS.paper, RPS.scissors))  # noqa: S311
        cond = {
            (RPS.rock, RPS.paper): False,
            (RPS.rock, RPS.scissors): True,
            (RPS.paper, RPS.rock): True,
            (RPS.paper, RPS.scissors): False,
            (RPS.scissors, RPS.rock): False,
            (RPS.scissors, RPS.paper): True,
        }

        if red_choice == player_choice:  # noqa: SIM108
            outcome = None  # Tie
        else:
            outcome = cond[(player_choice, red_choice)]

        if outcome is True:
            await interaction.response.send_message(f"{player_choice.value} beats {red_choice.value} You win {author.mention}!")
        elif outcome is False:
            await interaction.response.send_message(f"{red_choice.value} beats {player_choice.value} You lose {author.mention}!")
        else:
            await interaction.response.send_message(f"{player_choice.value} tied {red_choice.value} We're square {author.mention}!")
