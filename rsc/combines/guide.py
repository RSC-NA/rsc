"""The combines how-to-play guide: one Components V2 card in place of five messages."""

import logging
import re
from collections.abc import Iterator, Sequence
from pathlib import Path
from typing import Any

import discord
from discord import app_commands, ui

log = logging.getLogger("red.rsc.combines.guide")

GUIDE_IMAGES = Path(__file__).parent.parent / "resources" / "combines"
DEV_LEAGUE_URL = "https://devleague.rscna.com"
# Wrote the original guide. Credited without a ping (the guide is sent with AllowedMentions.none()).
GUIDE_AUTHOR_ID = 308295592033910784
REPLAYS_PATH = r"Documents\My Games\Rocket League\TAGame\Demos"
GUIDE_COMMANDS = ("checkin", "checkout", "lobbyinfo")

REPLAY_LOCATION_TEMPLATE = r"combines:replays"


class ReplayLocationButton(discord.ui.DynamicItem[discord.ui.Button], template=REPLAY_LOCATION_TEMPLATE):
    """ "Where are my replays?" on the guide. Persistent, so it keeps working on a guide posted long ago."""

    def __init__(self):
        super().__init__(
            discord.ui.Button(label="Where are my replays?", style=discord.ButtonStyle.secondary, custom_id=REPLAY_LOCATION_TEMPLATE)
        )

    @classmethod
    async def from_custom_id(
        cls,
        interaction: discord.Interaction,
        item: discord.ui.Item[Any],
        match: re.Match[str],
        /,
    ) -> "ReplayLocationButton":
        return cls()

    async def callback(self, interaction: discord.Interaction) -> None:
        await interaction.response.send_message(
            f"On PC, Rocket League saves replays in:\n`{REPLAYS_PATH}`\n"
            "-# On console? Ask a teammate on PC, or the home team, to upload them.",
            ephemeral=True,
        )


def combines_guide(commands: dict[str, str], announcements: str = "#combines-announcements") -> tuple[ui.LayoutView, list[discord.File]]:
    """The guide card and its four screenshots.

    `commands` maps "checkin", "checkout" and "lobbyinfo" to a clickable command mention;
    any that are missing fall back to inline code.
    """

    def command(name: str) -> str:
        return commands.get(name) or f"`/combines {name}`"

    files: list[discord.File] = []

    def step(title: str, body: str, image: str) -> ui.Section:
        file = discord.File(GUIDE_IMAGES / image, filename=image)
        files.append(file)
        return ui.Section(ui.TextDisplay(f"### {title}"), ui.TextDisplay(body), accessory=ui.Thumbnail(file))

    container = ui.Container(
        ui.TextDisplay("## How to play combines"),
        step("1 · Log in", f"Go to [devleague.rscna.com]({DEV_LEAGUE_URL}) and log in with Discord.", "combines_login.png"),
        step(
            "2 · Check in",
            f"Opens 10 minutes before start. Hit **Check In** on the site or run {command('checkin')}.",
            "combines_check_in.png",
        ),
        step(
            "3 · Wait for your ping",
            f"Watch {announcements}. Missed it? Run {command('lobbyinfo')}.",
            "combines_announcement.png",
        ),
        step("4 · Report", "Home hosts and reports the score. Away uploads replays, then confirms.", "combines_report.png"),
        ui.TextDisplay(f"### 5 · Queue again\nCheck in again for every series. Leave the queue with {command('checkout')}."),
        ui.Separator(),
        ui.TextDisplay(
            "### Someone misplaced? Send a Numbers Report\n"
            "If a player's MMR looks wrong, open your match on the Dev League site and click **Numbers Report** next to their name. "
            "The form fills in the player, their RSC ID and your lobby for you, and gives Numbers Committee replays to review.\n"
            "-# Balanced tiers depend on these reports. Report early, report often!"
        ),
        ui.Separator(),
        # add_item, since a DynamicItem is typed for either kind of view and the constructor wants a LayoutView item
        ui.ActionRow(ui.Button(label="Open Dev League", url=DEV_LEAGUE_URL)).add_item(ReplayLocationButton()),
        ui.TextDisplay(f"-# Thanks to <@{GUIDE_AUTHOR_ID}> for putting this guide together"),
        accent_colour=discord.Colour.blue(),
    )
    view = ui.LayoutView(timeout=None)
    view.add_item(container)
    return view, files


def is_combines_guide(message: discord.Message) -> bool:
    """Whether a message is a posted guide card, recognised by its replays button."""
    return any(isinstance(c, discord.Button) and c.custom_id == REPLAY_LOCATION_TEMPLATE for c in _walk(message.components))


def _walk(components: Sequence[discord.Component]) -> Iterator[discord.Component]:
    for component in components:
        yield component
        if isinstance(component, (discord.Container, discord.ActionRow)):
            yield from _walk(component.children)


def combines_command_mentions(commands: Sequence[app_commands.AppCommand]) -> dict[str, str]:
    """Clickable mentions for the guide's /combines subcommands, from the synced command list."""
    combines = next((c for c in commands if c.name == "combines"), None)
    if not combines:
        return {}
    return {
        option.name: option.mention
        for option in combines.options
        if isinstance(option, app_commands.AppCommandGroup) and option.name in GUIDE_COMMANDS
    }
