import logging
from enum import IntEnum

import discord
from discord.ui import TextInput

from rsc.abc import RSCMixIn
from rsc.const import BEHAVIOR_RULES_URL, DEFAULT_TIMEOUT
from rsc.embeds import ApiExceptionErrorEmbed, BlueEmbed, ExceptionErrorEmbed, RedEmbed
from rsc.enums import Platform, PlayerType, Referrer, RegionPreference
from rsc.exceptions import RscException
from rsc.views import (
    AgreeButton,
    AuthorOnlyView,
    CancelButton,
    ConfirmButton,
    DeclineButton,
    LinkButton,
    NextButton,
    NoButton,
    YesButton,
)

log = logging.getLogger("red.rsc.members.views")

TrackerLink = str


class SignupState(IntEnum):
    TIMES = 0
    RULES = 1
    PLAYER_TYPE = 2
    REGION = 3
    PLATFORM = 4
    REFERRER = 5
    TRACKERS = 6
    FINISHED = 7
    CANCELLED = 8


class IntentState(IntEnum):
    DECLARE = 0
    FINISHED = 1
    CANCELLED = 2


class PlayerInfoModal(discord.ui.Modal, title="Rocket League Trackers"):
    rsc_name: TextInput = TextInput(label="In-game Name (Must match exactly)", style=discord.TextStyle.short, required=True)
    links: TextInput = TextInput(label="Tracker Links", style=discord.TextStyle.paragraph, required=True)

    async def on_submit(self, interaction: discord.Interaction):
        await interaction.response.defer(ephemeral=True)


class ReferrerSelect(discord.ui.Select):
    def __init__(self):
        super().__init__(placeholder="I found out about RSC from...")
        for p in Referrer:
            self.add_option(label=p, value=p)

    async def callback(self, interaction: discord.Interaction):
        if self.view:
            self.view.referrer = Referrer(self.values[0])
        await self.view.confirm(interaction)


class PlatformSelect(discord.ui.Select):
    def __init__(self):
        super().__init__(placeholder="Select your primary platform...")
        for p in Platform:
            self.add_option(label=p, value=p)

    async def callback(self, interaction: discord.Interaction):
        if self.view:
            self.view.platform = Platform(self.values[0])
        await self.view.confirm(interaction)


class RegionSelect(discord.ui.Select):
    def __init__(self):
        super().__init__(placeholder="Select your preferred region...")
        for p in RegionPreference:
            self.add_option(label=p.full_name.upper(), value=p)

    async def callback(self, interaction: discord.Interaction):
        if self.view:
            self.view.region = RegionPreference(self.values[0])
        await self.view.confirm(interaction)


class PlayerTypeSelect(discord.ui.Select):
    def __init__(self):
        super().__init__(placeholder="New or former player...")
        for p in PlayerType:
            self.add_option(label=f"{p.value} PLAYER", value=p)

    async def callback(self, interaction: discord.Interaction):
        if self.view:
            self.view.player_type = PlayerType(self.values[0])
        await self.view.confirm(interaction)


class IntentSelect(discord.ui.Select):
    def __init__(self):
        super().__init__(placeholder="What is your intent?", min_values=1, max_values=1)
        self.add_option(label="Returning next season", value="yes")
        self.add_option(label="Not returning next season", value="no")

    async def callback(self, interaction: discord.Interaction):
        if self.view:
            self.view.result = self.values[0] == "yes"
        await interaction.response.defer(ephemeral=True)


class IntentToPlayView(AuthorOnlyView):
    def __init__(self, interaction: discord.Interaction, timeout: float = DEFAULT_TIMEOUT):
        super().__init__(interaction=interaction, timeout=timeout)
        self.state = IntentState.DECLARE
        self.result = False
        self.selectbox = IntentSelect()
        self.add_item(self.selectbox)
        self.add_item(ConfirmButton())
        self.add_item(CancelButton())

    async def prompt(self):
        """Prompt user for intent"""
        match self.state:
            case IntentState.DECLARE:
                await self.send_declaration()
            # case IntentState.CONFIRM:
            #     await self.send_confirmation()
            case IntentState.CANCELLED:
                await self.send_cancelled()
                self.stop()
            case IntentState.FINISHED:
                self.stop()

    # async def send_confirmation(self):
    #     self.clear_items()
    #     self.add_item(ConfirmButton())
    #     self.add_item(CancelButton())
    #     status_fmt = (
    #         "Returning Next Season" if self.result else "Not Returning Next Season"
    #     )
    #     embed = BlueEmbed(
    #         title="Intent to Play",
    #         description=f"Please verify the following is correct.\n\nIntent: **{status_fmt}**",
    #     )
    #     await self.interaction.edit_original_response(embed=embed, view=self)

    async def send_declaration(self):
        embed = BlueEmbed(
            title="Intent to Play",
            description="Please declare your intent for the next season of RSC below.",
        )
        await self.interaction.response.send_message(embed=embed, view=self, ephemeral=True)

    async def confirm(self, interaction: discord.Interaction):
        """User pressed Yes Button"""
        log.debug(f"Select Values: {self.selectbox.values}")
        if not self.selectbox.values:
            return await interaction.response.send_message(
                content="Please select returning or not returning in the drop down.",
                ephemeral=True,
            )
        log.debug(f"[INTENT] User agreed to {self.state.name}")
        self.state = IntentState(self.state + 1)
        await self.prompt()

    async def decline(self, interaction: discord.Interaction):
        """User pressed No Button"""
        log.debug(f"[INTENT] User cancelled on {self.state.name}")
        self.state = IntentState.CANCELLED
        await interaction.response.defer(ephemeral=True)
        await self.send_cancelled()
        self.stop()

    async def send_cancelled(self):
        await self.interaction.edit_original_response(
            embed=RedEmbed(
                title="Intent Declaration Cancelled",
                description=(
                    "You have cancelled declaring your intent to play for next season.\n\n"
                    " If this was an error, please run the command again."
                ),
            ),
            view=None,
        )


class SignupView(AuthorOnlyView):
    def __init__(self, interaction: discord.Interaction, timeout: float = 600.0):
        super().__init__(interaction=interaction, timeout=timeout)
        self.state = SignupState.TIMES
        self.player_type = PlayerType.NEW
        self.platform = Platform.EPIC
        self.region = RegionPreference.EAST
        self.referrer = Referrer.OTHER
        self.rsc_name: str = ""
        self.trackers: list[TrackerLink] = []

    async def prompt(self):
        """Prompt user according to view state"""
        log.debug(f"Signup prompt() state: {self.state}")
        match self.state:
            case SignupState.TIMES:
                await self.send_times()
            case SignupState.RULES:
                await self.send_rules()
            case SignupState.PLAYER_TYPE:
                await self.send_player_type()
            case SignupState.REGION:
                await self.send_region_preference()
            case SignupState.PLATFORM:
                await self.send_platform()
            case SignupState.REFERRER:
                await self.send_referrer()
            case SignupState.TRACKERS:
                await self.send_trackers()
            case SignupState.FINISHED:
                log.debug("Signup view finished.")
                self.stop()
                return
            case SignupState.CANCELLED:
                log.debug("Signup view cancelled.")
                self.stop()
                return

        # Check if user cancelled the last form
        if self.state == SignupState.CANCELLED:
            self.stop()
            return

    async def confirm(self, interaction: discord.Interaction):
        """User pressed Yes Button"""
        log.debug(f"[SIGNUP] User agreed to {self.state.name}")

        if self.state == SignupState.TRACKERS:
            await self.send_trackers_modal(interaction)
        else:
            await interaction.response.defer(ephemeral=True)

        # Move to next step
        self.state = SignupState(self.state + 1)
        await self.prompt()

    async def decline(self, interaction: discord.Interaction):
        """User pressed No Button"""
        log.debug(f"[SIGNUP] User cancelled on {self.state.name}")
        self.state = SignupState.CANCELLED
        await interaction.response.defer(ephemeral=True)
        await self.prompt()

    async def send_region_preference(self):
        self.clear_items()
        self.add_item(RegionSelect())

        embed = discord.Embed(
            title="Region Preference",
            description="What is your preferred region when playing Rocket League?",
            color=discord.Color.blue(),
        )
        await self.interaction.edit_original_response(embed=embed, view=self)

    async def send_trackers_modal(self, interaction: discord.Interaction):
        info_modal = PlayerInfoModal()
        await interaction.response.send_modal(info_modal)
        await info_modal.wait()
        # Probably validate them here?
        self.rsc_name = info_modal.rsc_name.value
        self.trackers = info_modal.links.value.splitlines()

    async def send_trackers(self):
        self.clear_items()
        self.add_item(NextButton())
        self.add_item(CancelButton())

        embed = discord.Embed(
            title="RSC Sign Up Information",
            color=discord.Color.blue(),
        )
        embed.add_field(
            name="In-game Name",
            value=(
                "You will need to provide your desired in-game name for Rocket League.\n\n"
                "This **needs** to match the name you play matches on, there are no exceptions."
            ),
            inline=False,
        )

        if self.interaction.guild and self.interaction.guild.id == 809939294331994113:
            tracker_fmt = "**A tracker with 50 2v2 games played is required.**"
        else:
            tracker_fmt = "**A tracker with 50 3v3 games played is required.**"

        embed.add_field(
            name="Tracker Links",
            value=(
                "You will need to submit rocket league tracker links for **ALL** of your accounts."
                " Please separate each link by a new line.\n\n"
                "For example:\n"
                "https://rocketleague.tracker.network/rocket-league/profile/psn/Untamed-chaos/overview\n"
                "https://rocketleague.tracker.network/rocket-league/profile/steam/76561198028063203/overview\n\n"
                "Note: Steam accounts must list your Steam64ID.\n"
                "You can find your Steam64ID here: https://steamidfinder.com/\n"
                "Find your tracker link here: https://rocketleague.tracker.network\n\n"
                f"{tracker_fmt}"
            ),
            inline=False,
        )
        # First form, so we respond to the interaction instead of followup
        await self.interaction.edit_original_response(embed=embed, view=self)

    async def send_referrer(self):
        self.clear_items()
        self.add_item(ReferrerSelect())

        embed = discord.Embed(
            title="Referral Information",
            description="How did you find out about RSC?",
            color=discord.Color.blue(),
        )
        await self.interaction.edit_original_response(embed=embed, view=self)

    async def send_platform(self):
        self.clear_items()
        self.add_item(PlatformSelect())

        embed = discord.Embed(
            title="Primary Platform",
            description="Please select your primary platform for playing Rocket League.",
            color=discord.Color.blue(),
        )
        await self.interaction.edit_original_response(embed=embed, view=self)

    async def send_player_type(self):
        self.clear_items()
        self.add_item(PlayerTypeSelect())

        embed = discord.Embed(
            title="New or Returning Player",
            description="Are you a new RSC player or returning from a previous season?",
            color=discord.Color.blue(),
        )
        await self.interaction.edit_original_response(embed=embed, view=self)

    async def send_rules(self):
        self.clear_items()
        self.add_item(AgreeButton())
        self.add_item(DeclineButton())
        self.add_item(LinkButton(label="RSC Behavior Rules", url=BEHAVIOR_RULES_URL))

        embed = discord.Embed(
            title="RSC Rules",
            description=(
                "In RSC we maintain a non negotiable set of rules in regards to player behavior."
                " For more information, see the link below.\n\n"
                "By selecting **Agree**, you are agreeing to any RSC rules in our discord, website, and RSC related games."
            ),
            color=discord.Color.blue(),
        )
        await self.interaction.edit_original_response(embed=embed, view=self)

    async def send_times(self):
        self.add_item(YesButton())
        self.add_item(NoButton())

        embed = discord.Embed(
            title="RSC Game Times",
            color=discord.Color.blue(),
        )

        if self.interaction.guild and self.interaction.guild.id == 809939294331994113:
            embed.description = (
                "We play our games on **Thursday** nights at **10PM**.\n\n"
                "By selecting **Yes**, you are agreeing that you are available to play on those days and time."
            )
        else:
            embed.description = (
                "We play our games on **Monday** and **Wednesday** at **10PM EST**.\n\n"
                "By selecting **Yes**, you are agreeing that you are available to play on those days and time."
            )
        # First form, so we respond to the interaction instead of followup
        await self.interaction.response.send_message(embed=embed, view=self, ephemeral=True)


class PlayerInfoView(discord.ui.View):
    def __init__(
        self,
        mixin: RSCMixIn,
        player: discord.Member,
        team: str,
        franchise: str,
    ):
        super().__init__()
        self.mixin = mixin
        self.player = player
        self.team = team
        self.franchise = franchise

    @discord.ui.button(label="Team Roster", style=discord.ButtonStyle.primary)
    async def display_team_roster(self, interaction: discord.Interaction, button: discord.ui.Button):
        await interaction.response.defer(ephemeral=True)

        guild = interaction.guild
        if not guild:
            return

        try:
            plist = await self.mixin.players(guild, team_name=self.team, limit=10)
            embed = await self.mixin.build_roster_embed(guild, plist)
        except RscException as exc:
            return await interaction.followup.send(embed=ApiExceptionErrorEmbed(exc), ephemeral=True)
        except (ValueError, AttributeError) as exc:
            return await interaction.followup.send(embed=ExceptionErrorEmbed(exc_message=str(exc)))

        await interaction.followup.send(embed=embed, ephemeral=True)

    @discord.ui.button(label="Franchise Info", style=discord.ButtonStyle.primary)
    async def display_franchise_teams(self, interaction: discord.Interaction, button: discord.ui.Button):
        await interaction.response.defer(ephemeral=True)
        guild = interaction.guild
        if not guild:
            return

        log.debug(f"Fetching teams for {self.franchise}")
        try:
            teams = await self.mixin.teams(guild, franchise=self.franchise)
        except RscException as exc:
            return await interaction.followup.send(embed=ApiExceptionErrorEmbed(exc), ephemeral=True)

        if not teams:
            await interaction.followup.send(content="No results found.", ephemeral=True)
            return

        # Build Embed
        try:
            embed = await self.mixin.build_franchise_teams_embed(guild, teams)
        except (ValueError, AttributeError) as exc:
            return await interaction.followup.send(embed=ExceptionErrorEmbed(exc_message=str(exc)))

        await interaction.followup.send(embed=embed, ephemeral=True)
