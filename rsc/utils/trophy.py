import logging
import discord
from redbot.core import app_commands

from rsc.abc import RSCMixIn
from rsc import const
from rsc.embeds import BetterEmbed, ErrorEmbed, ExceptionErrorEmbed, SuccessEmbed, YellowEmbed
from rsc.types import Accolades
from rsc.logs import GuildLogAdapter
from rsc.utils import utils
from rsc.utils.views.mass_trophy import MassTrophyModal

logger = logging.getLogger("red.rsc.trophy")
log = GuildLogAdapter(logger)

# How often to refresh the progress embed during a mass assignment
PROGRESS_INTERVAL = 10


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

    @_accolades.command(name="addtrophy", description="Add a trophy for a championship win")
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

    @_accolades.command(name="adddevleague", description="Add a dev league championship trophy")
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

    @_accolades.command(name="addstar", description="Add a star for MVP/All-Star season")
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

    @_accolades.command(name="addcombinecup", description="Add a combine cup trophy")
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

    @_accolades.command(name="masstrophy", description="Add multiple trophies at once by discord IDs")
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

        # Validate up front. Doing this inside the loop would abort a batch
        # halfway through after some members were already updated.
        if trophy not in (const.TROPHY_EMOJI, const.STAR_EMOJI, const.DEV_LEAGUE_EMOJI, const.COMBINE_CUP_EMOJI):
            return await interaction.response.send_message(embed=ErrorEmbed(description="Invalid trophy type."), ephemeral=True)

        # Show modal to collect trophy type and discord IDs
        trophy_modal = MassTrophyModal()
        await interaction.response.send_modal(trophy_modal)
        if await trophy_modal.wait():
            log.debug("Mass trophy modal timed out", guild=guild)
            return
        trophy_modal.stop()

        try:
            members, errors = await trophy_modal.get_members(guild)
        except ValueError as exc:
            return await interaction.followup.send(embed=ExceptionErrorEmbed(exc_message=str(exc)), ephemeral=True)

        # The modal deferred its own response. Report against it so the caller
        # isn't left staring at a "thinking" spinner for the whole run.
        modal_interaction = trophy_modal.interaction

        total = len(members)
        status = YellowEmbed(title="Processing", description=f"Applying {trophy!s} to {total} member(s). This may take a moment...")
        if modal_interaction:
            await modal_interaction.edit_original_response(embed=status)
        else:
            await interaction.followup.send(embed=status, ephemeral=True)

        applied = 0
        for idx, member in enumerate(members, start=1):
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

            # A failure on one member must not abandon the rest of the batch.
            try:
                new_nick = await self.format_nickname(member, accolades)
                await member.edit(nick=new_nick)
                applied += 1
            except ValueError as exc:
                errors.append(f"{member.mention}: {exc}")
            except discord.Forbidden:
                errors.append(f"{member.mention}: Missing permission to change nickname (role hierarchy or server owner)")
            except discord.HTTPException as exc:
                log.warning(f"Error updating nickname for {member.id}: {exc}", guild=guild)
                errors.append(f"{member.mention}: Discord API error ({exc.text or exc.status})")

            if modal_interaction and idx % PROGRESS_INTERVAL == 0 and idx != total:
                await modal_interaction.edit_original_response(
                    embed=YellowEmbed(
                        title="Processing",
                        description=f"Applying {trophy!s}... {idx}/{total} processed ({len(errors)} error(s))",
                    )
                )

        summary = f"Added {trophy!s} for **{applied}/{total}** member(s)."
        result: BetterEmbed = (
            SuccessEmbed(title="Mass Trophy Applied", description=summary)
            if applied
            else ErrorEmbed(title="Mass Trophy Failed", description=summary)
        )
        if errors:
            # The full list goes to the log. A long batch can produce more
            # errors than an embed can hold, so say so rather than truncating
            # quietly.
            error_text = "\n".join(errors)
            log.warning(f"Mass trophy finished with {len(errors)} error(s):\n{error_text}", guild=guild)
            leftover = result.add_long_field(name=f"Errors ({len(errors)})", value=error_text)
            if leftover:
                result.set_footer(text="Some errors were too long to display. See the bot logs for the full list.")

        if modal_interaction:
            return await modal_interaction.edit_original_response(embed=result)
        return await interaction.followup.send(embed=result, ephemeral=True)

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
