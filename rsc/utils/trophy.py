import logging
import discord
from redbot.core import app_commands

from rsc.abc import RSCMixIn
from rsc import const
from rsc.embeds import ErrorEmbed, ExceptionErrorEmbed
from rsc.types import Accolades
from rsc.logs import GuildLogAdapter
from rsc.utils import utils
from rsc.utils.views.mass_trophy import MassTrophyModal

logger = logging.getLogger("red.rsc.trophy")
log = GuildLogAdapter(logger)


class TrophyMixIn(RSCMixIn):
    def __init__(self):
        log.debug("Initializing TrophyMixIn")
        super().__init__()

    # Top Level Group

    _accolades: app_commands.Group = app_commands.Group(
        name="accolades",
        description="Manage player accolades and season rewards",
        guild_only=True,
        default_permissions=discord.Permissions(manage_guild=True),
    )

    # Settings

    @_accolades.command(name="addtrophy", description="Add a trophy for a championship win")  # type: ignore[type-var]
    async def _accolades_add_trophy_cmd(self, interaction: discord.Interaction, player: discord.Member):
        guild = interaction.guild
        if not guild:
            return

        accolades = await utils.member_accolades(player)
        accolades.trophy += 1

        try:
            new_nick = await self.format_nickname(player, accolades)
            await player.edit(nick=new_nick)
        except ValueError as e:
            return await interaction.response.send_message(str(e), ephemeral=True)

        return await interaction.response.send_message(f"Added a trophy for {player.mention}.", ephemeral=True)

    @_accolades.command(name="adddevleague", description="Add a dev league championship trophy")  # type: ignore[type-var]
    async def _accolades_add_dev_league_cmd(self, interaction: discord.Interaction, player: discord.Member):
        guild = interaction.guild
        if not guild:
            return

        accolades = await utils.member_accolades(player)

        accolades.devleague += 1

        try:
            new_nick = await self.format_nickname(player, accolades)
            await player.edit(nick=new_nick)
        except ValueError as e:
            return await interaction.response.send_message(str(e), ephemeral=True)

        return await interaction.response.send_message(f"Added dev league trophy for {player.mention}.", ephemeral=True)

    @_accolades.command(name="addstar", description="Add a star for MVP/All-Star season")  # type: ignore[type-var]
    async def _accolades_add_star_cmd(self, interaction: discord.Interaction, player: discord.Member):
        guild = interaction.guild
        if not guild:
            return

        accolades = await utils.member_accolades(player)

        accolades.star += 1

        try:
            new_nick = await self.format_nickname(player, accolades)
            await player.edit(nick=new_nick)
        except ValueError as e:
            return await interaction.response.send_message(str(e), ephemeral=True)

        return await interaction.response.send_message(f"Added dev league trophy for {player.mention}.", ephemeral=True)

    @_accolades.command(name="addcombinecup", description="Add a combine cup trophy")  # type: ignore[type-var]
    async def _accolades_add_combine_cup_cmd(self, interaction: discord.Interaction, player: discord.Member):
        guild = interaction.guild
        if not guild:
            return

        accolades = await utils.member_accolades(player)

        accolades.combine_cup += 1

        try:
            new_nick = await self.format_nickname(player, accolades)
            await player.edit(nick=new_nick)
        except ValueError as e:
            return await interaction.response.send_message(str(e), ephemeral=True)

        return await interaction.response.send_message(f"Added combine cup trophy for {player.mention}.", ephemeral=True)

    @_accolades.command(name="masstrophy", description="Add multiple trophies at once by discord IDs")  # type: ignore[type-var]
    @app_commands.choices(
        trophy=[
            app_commands.Choice(name="Championship", value=const.TROPHY_EMOJI),
            app_commands.Choice(name="Star", value=const.STAR_EMOJI),
            app_commands.Choice(name="Dev League", value=const.DEV_LEAGUE_EMOJI),
            app_commands.Choice(name="Combine Cup", value=const.COMBINE_CUP_EMOJI),
        ]
    )
    async def _accolades_mass_trophy_cmd(self, interaction: discord.Interaction, trophy: str):
        guild = interaction.guild
        if not guild:
            return

        # Show modal to collect trophy type and discord IDs
        trophy_modal = MassTrophyModal()
        await interaction.response.send_modal(trophy_modal)
        await trophy_modal.wait()
        trophy_modal.stop()

        try:
            members = await trophy_modal.get_members(guild)
        except ValueError as exc:
            return await interaction.followup.send(embed=ExceptionErrorEmbed(exc_message=str(exc)))

        for member in members:
            accolades = await utils.member_accolades(member)

            match trophy:
                case const.TROPHY_EMOJI:
                    accolades.trophy += 1
                case const.STAR_EMOJI:
                    accolades.star += 1
                case const.DEV_LEAGUE_EMOJI:
                    accolades.devleague += 1
                case const.COMBINE_CUP_EMOJI:
                    accolades.combine_cup += 1
                case _:
                    return await interaction.followup.send(embed=ErrorEmbed("Invalid trophy type."))

            try:
                new_nick = await self.format_nickname(member, accolades)
                await member.edit(nick=new_nick)
            except ValueError as e:
                return await interaction.followup.send(embed=ExceptionErrorEmbed(exc_message=str(e)))

        return await interaction.followup.send(f"Added {trophy!s} for {len(members)} players.", ephemeral=True)

    # Helper Functions

    @staticmethod
    async def format_nickname(member: discord.Member, accolades: Accolades) -> str:
        stripped_name = await utils.strip_discord_accolades(member.display_name)
        new_nick = f"{stripped_name} {accolades!s}"

        if len(new_nick) > 32:
            raise ValueError(f"Discord name is too long ({member.id}): {new_nick}")

        if not new_nick or len(new_nick) < 1:
            raise ValueError(f"Error changing name. Empty or <1 characters: {member.mention}")
        return new_nick.strip()
