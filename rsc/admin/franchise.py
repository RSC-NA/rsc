import logging
import tempfile
from typing import cast

import discord
from redbot.core import app_commands
from rscapi.models.franchise import Franchise
from rscapi.models.rebrand_a_franchise import RebrandAFranchise
from rscapi.models.team_details import TeamDetails

from rsc import const
from rsc.admin import AdminMixIn
from rsc.admin.modals import FranchiseRebrandModal
from rsc.admin.views import (
    CreateFranchiseView,
    DeleteFranchiseView,
    RebrandFranchiseView,
    TransferFranchiseView,
)
from rsc.embeds import (
    ApiExceptionErrorEmbed,
    ErrorEmbed,
    GreenEmbed,
    LoadingEmbed,
    OrangeEmbed,
    SuccessEmbed,
    YellowEmbed,
)
from rsc.exceptions import RscException
from rsc.franchises import FranchiseMixIn
from rsc.logs import GuildLogAdapter
from rsc.teams import TeamMixIn
from rsc.tiers import TierMixIn
from rsc.types import RebrandTeamDict
from rsc.utils import utils
from rsc.views import LinkButton

logger = logging.getLogger("red.rsc.admin.franchise")
log = GuildLogAdapter(logger)


class AdminFranchiseMixIn(AdminMixIn):
    def __init__(self):
        log.debug("Initializing AdminMixIn:Franchise")

        super().__init__()

    _franchise = app_commands.Group(
        name="franchise",
        description="Manage RSC franchises",
        parent=AdminMixIn._admin,
        guild_only=True,
        default_permissions=discord.Permissions(manage_guild=True),
    )

    @_franchise.command(name="addteam", description="Add a new team to a franchise")  # type: ignore
    @app_commands.describe(
        franchise="Franchise name", tier="Team Tier", name="Team Name"
    )
    @app_commands.autocomplete(
        franchise=FranchiseMixIn.franchise_autocomplete,
        tier=TierMixIn.tier_autocomplete,
    )
    async def _franchise_addteam_cmd(
        self, interaction: discord.Interaction, franchise: str, tier: str, name: str
    ):
        guild = interaction.guild
        if not guild:
            return

        await interaction.response.defer(ephemeral=True)

        tier = tier.capitalize()

        try:
            result = await self.create_team(
                guild, franchise=franchise, tier=tier, name=name
            )
            log.debug(f"Result: {result}")
        except RscException as exc:
            return await interaction.followup.send(
                embed=ApiExceptionErrorEmbed(exc), ephemeral=True
            )

        # Update team cache
        if name not in self._team_cache[guild.id]:
            self._team_cache[guild.id].append(name)

        embed = GreenEmbed(title="Team Created", description="Team has been created.")
        embed.add_field(name="Name", value=result.name, inline=True)
        embed.add_field(name="Franchise", value=result.franchise.name, inline=True)
        if result.tier:
            embed.add_field(name="Tier", value=result.tier.name, inline=True)
        await interaction.followup.send(embed=embed, ephemeral=True)

    @_franchise.command(name="delteam", description="Remove a team from a franchise")  # type: ignore
    @app_commands.describe(
        franchise="Franchise name", tier="Team Tier", team="Team to delete"
    )
    @app_commands.autocomplete(
        franchise=FranchiseMixIn.franchise_autocomplete,
        tier=TierMixIn.tier_autocomplete,
        team=TeamMixIn.teams_autocomplete,
    )
    async def _franchise_rmteam_cmd(
        self, interaction: discord.Interaction, franchise: str, tier: str, team: str
    ):
        guild = interaction.guild
        if not guild:
            return

        await interaction.response.defer(ephemeral=True)

        tier = tier.capitalize()

        fteams = await self.teams(guild, franchise=franchise, tier=tier, name=team)
        if not fteams:
            return await interaction.followup.send(
                embed=ErrorEmbed(description="Unable to find a matching team in API."),
                ephemeral=True,
            )

        if len(fteams) > 1:
            return await interaction.followup.send(
                embed=ErrorEmbed(
                    description="API returned multiple results for that team."
                ),
                ephemeral=True,
            )

        fteam = fteams.pop(0)

        if not fteam.id:
            return await interaction.followup.send(
                embed=ErrorEmbed(description="API returned a team without an ID."),
                ephemeral=True,
            )

        try:
            await self.delete_team(guild, team_id=fteam.id)
        except RscException as exc:
            return await interaction.followup.send(
                embed=ApiExceptionErrorEmbed(exc), ephemeral=True
            )

        # Update team cache
        if team in self._team_cache[guild.id]:
            self._team_cache[guild.id].append(team)

        embed = GreenEmbed(title="Team Deleted", description="Team has been deleted.")
        embed.add_field(name="Name", value=team, inline=True)
        embed.add_field(name="Franchise", value=franchise, inline=True)
        embed.add_field(name="Tier", value=tier, inline=True)
        await interaction.followup.send(embed=embed, ephemeral=True)

    @_franchise.command(name="logo", description="Upload a logo for the franchise")  # type: ignore
    @app_commands.describe(franchise="Franchise name", logo="Franchise logo file (PNG)")
    @app_commands.autocomplete(franchise=FranchiseMixIn.franchise_autocomplete)  # type: ignore
    async def _franchise_logo(
        self, interaction: discord.Interaction, franchise: str, logo: discord.Attachment
    ):
        guild = interaction.guild
        if not guild:
            return

        # Defer in case file is large
        await interaction.response.defer(ephemeral=True)

        # validate franchise
        flist = await self.franchises(guild, name=franchise)
        if not flist:
            await interaction.followup.send(
                embed=ErrorEmbed(description=f"**{franchise}** does not exist."),
                ephemeral=True,
            )
            return

        if len(flist) > 1:
            await interaction.followup.send(
                embed=ErrorEmbed(
                    description=f"**{franchise}** matches more than one franchise name."
                ),
                ephemeral=True,
            )
            return

        fdata = flist.pop()

        # Validate franchise data
        if not (fdata.id and fdata.prefix and fdata.name):
            await interaction.followup.send(
                embed=ErrorEmbed(
                    description=f"**{franchise}** returned malformed data from API."
                ),
                ephemeral=True,
            )
            return

        logo_bytes = await logo.read()
        # have to do this because monty sux
        try:
            with tempfile.NamedTemporaryFile() as fp:
                fp.write(logo_bytes)
                fp.seek(0)
                result: Franchise = await self.upload_franchise_logo(
                    guild, fdata.id, fp.name
                )
        except RscException as exc:
            await interaction.followup.send(
                embed=ApiExceptionErrorEmbed(exc=exc),
                ephemeral=True,
            )
            return

        # Validate result
        if not result.logo:
            await interaction.followup.send(
                embed=ErrorEmbed(
                    description="Something went wrong during logo upload. API did not return a logo url."
                ),
                ephemeral=True,
            )
            return

        # Remove old emoji. Discord API doesn't let us update it in place
        old_emoji = await utils.emoji_from_prefix(guild, fdata.prefix)
        if old_emoji:
            log.debug(f"Deleting old franchise emoji: {old_emoji.name}")
            await old_emoji.delete(reason="Updating emoji to new logo")
        else:
            await interaction.followup.send(
                content=f"Unable to find franchise emoji ({fdata.prefix}). It has not been removed."
            )

        # Discord Max
        MAX_EMOJIS = 200 if "ROLE_ICONS" in guild.features else 50
        MAX_EMOJI_SIZE = 256000  # 256kb

        # Make sure we have enough emoji slots
        log.debug(
            f"[{guild.name}] Max Emojis: {MAX_EMOJIS} Emoji Size: {MAX_EMOJI_SIZE}"
        )
        if len(guild.emojis) >= MAX_EMOJIS:
            await interaction.followup.send(
                embed=ErrorEmbed(
                    title="Logo Upload Error",
                    description=(
                        "Franchise logo was uploaded but guild doesn't have enough emoji slots available.\n\n"
                        f"Guild Emoji Count: {len(guild.emojis)}\n"
                        f"Max Emoji Count: {MAX_EMOJIS}"
                    ),
                )
            )
            return

        # Validate image size for emoji/icon. Resize to 128x128 if needed.
        log.debug(f"Img Size: {len(logo_bytes)}")
        if len(logo_bytes) >= MAX_EMOJI_SIZE:
            log.debug("Image is too large... resizing to 128x128")
            orig_size = len(logo_bytes)
            logo_bytes = await utils.img_to_thumbnail(logo_bytes, 128, 128, "PNG")
            log.debug(f"New Img Size: {len(logo_bytes)}")
            # Final size validation
            if len(logo_bytes) >= MAX_EMOJI_SIZE:
                await interaction.followup.send(
                    embed=ErrorEmbed(
                        title="Logo Upload Error",
                        description=(
                            "Franchise logo was uploaded but we were unable to resize it as a guild emoji.\n\n"
                            f"Original Image Size: {orig_size}\n"
                            f"Resized 128x128 Size: {len(logo_bytes)}\n"
                            f"Max Emoji Size: {MAX_EMOJI_SIZE}"
                        ),
                    )
                )
                return

        # Update franchise display icon
        icons_allowed = "ROLE_ICONS" in guild.features
        if icons_allowed:
            frole = await utils.franchise_role_from_name(guild, fdata.name)
            if not frole:
                log.error(f"Unable to find franchise role: {fdata.name}")
                await interaction.followup.send(
                    embed=YellowEmbed(
                        title="Logo Updated",
                        description=(
                            "Franchise logo was uploaded but we were unable to find the franchise role in the guild.\n\n"
                            f"Franchise Name: `{fdata.name}`"
                        ),
                    )
                )
                return
            else:
                await frole.edit(display_icon=logo_bytes)
        log.debug("Franchise role display icon was updated.")

        # Validate emoji name
        log.debug(f"Emoji Name: {fdata.prefix}")
        if not await utils.valid_emoji_name(fdata.prefix):
            await interaction.followup.send(
                embed=YellowEmbed(
                    title="Logo Updated",
                    description=(
                        "Franchise logo was uploaded but desired emoji name is invalid. "
                        "Must only contain the following characters. `[a-z0-9_]`.\n\n"
                        f"Emoji Name: `{fdata.prefix}`"
                    ),
                )
            )
            return

        # Recreate emoji
        new_emoji = await guild.create_custom_emoji(
            name=fdata.prefix, image=logo_bytes, reason=f"{franchise} has a new logo"
        )
        log.debug(f"New franchise emoji: {new_emoji.name}")

        full_logo_url = await self.full_logo_url(guild, result.logo)

        embed = SuccessEmbed(
            title="Logo Updated",
            description=(
                f"{franchise} logo has been uploaded to the API.\n\n"
                "Franchise emoji and display icon have also been updated."
            ),
        )
        embed.add_field(name="Height", value=logo.height, inline=True)
        embed.add_field(name="Width", value=logo.width, inline=True)
        embed.add_field(name="Size", value=logo.size, inline=True)
        embed.add_field(name="Emoji", value=f"`:{fdata.prefix}:`", inline=False)

        url_button = LinkButton(label="Logo Link", url=full_logo_url)
        logo_view = discord.ui.View()
        logo_view.add_item(url_button)

        # Add new logo as thumbnail in embed
        embed.set_thumbnail(url=logo.url)
        await interaction.followup.send(embed=embed, view=logo_view, ephemeral=True)

    @_franchise.command(name="rebrand", description="Rebrand a franchise")  # type: ignore
    @app_commands.autocomplete(franchise=FranchiseMixIn.franchise_autocomplete)  # type: ignore
    @app_commands.describe(
        franchise="Franchise to rebrand", override="Admin only override"
    )
    async def _franchise_rebrand(
        self,
        interaction: discord.Interaction,
        franchise: str,
        override: bool = False,
    ):
        guild = interaction.guild
        if not guild:
            return

        # Send modal
        rebrand_modal = FranchiseRebrandModal()
        await interaction.response.send_modal(rebrand_modal)

        # Fetch franchise data while user is in modal
        fl = await self.franchises(guild, name=franchise)
        await rebrand_modal.wait()

        # Validate original franchise exists
        if not fl:
            return await rebrand_modal.interaction.response.send_message(
                embed=ErrorEmbed(description="No franchise found with that name."),
                ephemeral=True,
            )
        if len(fl) > 1:
            return await rebrand_modal.interaction.response.send_message(
                embed=ErrorEmbed(
                    description="Found multiple franchises matching that name... Please be more specific."
                ),
                ephemeral=True,
            )

        fdata = fl.pop()

        if not fdata.id:
            return await rebrand_modal.interaction.response.send_message(
                embed=ErrorEmbed(
                    description="API returned franchise without an ID attached."
                ),
                ephemeral=True,
            )

        if not (fdata.gm and fdata.gm.rsc_name):
            return await rebrand_modal.interaction.response.send_message(
                embed=ErrorEmbed(
                    description="API returned franchise without a GM or GM name."
                ),
                ephemeral=True,
            )

        # Validate type but allow empty tier list
        if not isinstance(fdata.tiers, list):
            return await rebrand_modal.interaction.response.send_message(
                embed=ErrorEmbed(
                    description=f"API returned non-list type for franchise tiers. Franchise ID: {fdata.id}"
                ),
                ephemeral=True,
            )

        # Number of rebranded teams must match number of franchise tiers
        if len(rebrand_modal.teams) != len(fdata.tiers):
            return await rebrand_modal.interaction.response.send_message(
                embed=ErrorEmbed(
                    description=(
                        "Number of team names does not match number of tiers in franchise.\n\n"
                        f"**Tiers:** {len(fdata.tiers)}\n"
                        f"**Team Names:** {len(rebrand_modal.teams)}"
                    )
                ),
                ephemeral=True,
            )

        # Match teams to tiers
        rebrands = []
        fdata.tiers.sort(key=lambda x: cast(int, x.id))
        for t in fdata.tiers:
            if t.name and t.id:
                rebrands.append(
                    RebrandTeamDict(
                        name=rebrand_modal.teams.pop(0), tier=t.name, tier_id=t.id
                    )
                )
            else:
                raise RuntimeError("Franchise team has no name or ID.")

        rebrand_view = RebrandFranchiseView(
            rebrand_modal.interaction,
            old_name=franchise,
            name=rebrand_modal.name,
            prefix=rebrand_modal.prefix,
            teams=rebrands,
        )
        await rebrand_view.prompt()
        await rebrand_view.wait()

        if not rebrand_view.result:
            return

        await rebrand_modal.interaction.edit_original_response(
            embed=LoadingEmbed(), view=None
        )

        # Get franchise role
        frole = await utils.franchise_role_from_name(guild, franchise)
        if not frole:
            log.error(
                f"Unable to find franchise role for rebrand: {franchise}", guild=guild
            )
            return await rebrand_modal.interaction.edit_original_response(
                embed=ErrorEmbed(
                    description="Franchise was rebranded but franchise role was not found."
                )
            )

        # Populate TeamDetails list with new names and team IDs
        tdetails: list[TeamDetails] = []
        for r in rebrands:
            tdetails.append(TeamDetails(tier=r["tier_id"], name=r["name"]))

        # Rebrand Franchise
        log.debug(f"Rebranding {franchise} to {rebrand_modal.name}")
        rebrand = RebrandAFranchise(
            name=rebrand_modal.name,
            prefix=rebrand_modal.prefix,
            teams=tdetails,
            admin_override=override,
        )
        try:
            new_fdata = await self.rebrand_franchise(
                guild, id=fdata.id, rebrand=rebrand
            )
            log.debug(new_fdata)
        except RscException as exc:
            return await rebrand_modal.interaction.edit_original_response(
                embed=ApiExceptionErrorEmbed(exc), view=None
            )

        # Update franchise cache
        if franchise in self._franchise_cache[guild.id]:
            self._franchise_cache[guild.id].remove(franchise)

        if rebrand_modal.name not in self._franchise_cache[guild.id]:
            self._franchise_cache[guild.id].append(rebrand_modal.name)
            self._franchise_cache[guild.id].sort()

        # Update transaction channel
        trans_channel = await self.get_franchise_transaction_channel(guild, franchise)
        if trans_channel:
            log.debug(f"Before position: {trans_channel.position}")
            rebrand_fmt = await self.get_franchise_transaction_channel_name(
                rebrand_modal.name
            )
            trans_channel = await trans_channel.edit(name=rebrand_fmt)
            if trans_channel.category:
                # Debug print
                log.debug(
                    f"Category Channel Count: {len(trans_channel.category.channels)}"
                )
                for c in trans_channel.category.channels:
                    log.debug(f"Channel: {c.name} Position: {c.position}")

                channels = sorted(trans_channel.category.channels, key=lambda x: x.name)
                min_idx = min(c.position for c in trans_channel.category.channels)
                log.debug(f"Min Index: {min_idx}")
                idx = channels.index(trans_channel) + 1
                log.debug(f"Transaction Channel Index: {idx} ({min_idx+idx})")
                await trans_channel.edit(position=min_idx + idx)
        else:
            await interaction.followup.send(
                content="Unable to find franchise transaction channel. Must be manually updated.",
                ephemeral=True,
            )

        # Update franchise role
        await frole.edit(name=f"{rebrand_modal.name} ({new_fdata.gm.rsc_name})")

        # Update emoji
        if fdata.prefix:
            emoji = await utils.emoji_from_prefix(guild, prefix=fdata.prefix)
            if emoji:
                await emoji.edit(name=new_fdata.prefix)
            else:
                await interaction.followup.send(
                    content=f"Unable to update franchise emoji. `{fdata.prefix}` not found.",
                    ephemeral=True,
                )

        # Update all prefix
        try:
            for m in frole.members:
                name = await utils.remove_prefix(m)
                await m.edit(nick=f"{rebrand_modal.prefix} | {name}")
        except discord.Forbidden as exc:
            await interaction.followup.send(
                content=f"Unable to update nickname {m.mention}: `{exc}`",
                ephemeral=True,
            )

        embed = SuccessEmbed(
            description=f"**{fdata.name}** has been rebranded to **{rebrand_modal.name}**"
        )
        await rebrand_modal.interaction.edit_original_response(embed=embed, view=None)

    @_franchise.command(name="delete", description="Delete a franchise")  # type: ignore
    @app_commands.describe(franchise="Franchise name")
    @app_commands.autocomplete(franchise=FranchiseMixIn.franchise_autocomplete)  # type: ignore
    async def _franchise_delete(
        self,
        interaction: discord.Interaction,
        franchise: str,
    ):
        guild = interaction.guild
        if not guild:
            return

        await interaction.response.defer(ephemeral=True)
        fl = await self.franchises(guild, name=franchise)
        if not fl:
            return await interaction.followup.send(
                embed=ErrorEmbed(description=f"**{franchise}** does not exist."),
                ephemeral=True,
            )
        if len(fl) > 1:
            return await interaction.followup.send(
                embed=ErrorEmbed(
                    description=f"**{franchise}** matches more than one franchise name."
                ),
                ephemeral=True,
            )

        delete_view = DeleteFranchiseView(interaction, name=franchise)
        await delete_view.prompt()

        if not fl[0].id:
            return await interaction.followup.send(
                embed=ErrorEmbed(
                    description="API did not return a franchise ID attached to franchise data."
                ),
                ephemeral=True,
            )

        # Get detailed information on players
        fdata = await self.franchise_by_id(guild, fl[0].id)
        await delete_view.wait()

        if not delete_view.result:
            return

        if not fdata:
            return await interaction.followup.send(
                embed=ErrorEmbed(
                    description=f"No franchise data returned for ID: {fl[0].id}"
                ),
                ephemeral=True,
            )

        # Validate franchise data
        if not fdata.id:
            return await interaction.followup.send(
                embed=ErrorEmbed(
                    description="API did not return a franchise ID attached to franchise data."
                ),
                ephemeral=True,
            )

        if not fdata.id:
            return await interaction.followup.send(
                embed=ErrorEmbed(
                    description="API did not return a franchise ID attached to franchise data."
                ),
                ephemeral=True,
            )

        # Delete franchise in API
        try:
            await self.delete_franchise(guild, id=fdata.id)
        except RscException as exc:
            await interaction.edit_original_response(
                embed=ApiExceptionErrorEmbed(exc), view=None
            )
            return

        # Roles
        fa_role = await utils.get_free_agent_role(guild)
        gm_role = await utils.get_gm_role(guild)
        former_gm_role = await utils.get_former_gm_role(guild)
        frole = await utils.franchise_role_from_name(guild, fdata.name)

        # Transaction Channel
        tchan = await self._trans_channel(guild)

        # Edit GM
        gm = None
        if fdata.gm.discord_id:
            gm = guild.get_member(fdata.gm.discord_id)
        if gm:
            await gm.remove_roles(gm_role)
            await gm.add_roles(former_gm_role)

        # Edit roles and prefix
        if fdata.teams:
            for t in fdata.teams:
                tier = t.tier
                tier_fa_role = await utils.get_tier_fa_role(guild, tier)

                # Not sure why these types are `list[Player|None] | None`
                if not t.players:
                    continue

                for p in t.players:
                    m = guild.get_member(p.discord_id)
                    if not m:
                        continue

                    await utils.give_fa_prefix(m)
                    await m.add_roles(fa_role, tier_fa_role)
                    if tchan:
                        await tchan.send(
                            f"{m.mention} has been released to Free Agency ({tier})",
                            allowed_mentions=discord.AllowedMentions(users=True),
                        )

        # Don't give FA prefix to non-playing GM
        if gm and not gm.display_name.startswith("FA |"):
            new_nick = await utils.remove_prefix(gm)
            await gm.edit(nick=new_nick)

        # Delete role
        if frole:
            log.debug(f"Deleting franchise role: {frole.name}")
            await frole.delete(reason="Franchise has been deleted")
        else:
            log.error(f"Unable to find franchise role: {fdata.name}", guild=guild)

        # Send result
        await interaction.edit_original_response(
            embed=SuccessEmbed(
                description=f"**{franchise}** has been successfully deleted. All players have been sent to free agency."
            ),
            view=None,
        )

    @_franchise.command(  # type: ignore
        name="create", description="Create a new franchise in the league"
    )
    @app_commands.describe(
        name="Franchise name",
        prefix='Franchise prefix (Ex: "TG")',
        gm="General Manager",
    )
    async def _franchise_create(
        self,
        interaction: discord.Interaction,
        name: str,
        prefix: str,
        gm: discord.Member,
    ):
        guild = interaction.guild
        if not guild:
            return

        create_view = CreateFranchiseView(interaction, name, gm)
        await create_view.prompt()
        await create_view.wait()

        if not create_view.result:
            return

        # GM role
        gm_role = discord.utils.get(guild.roles, name=const.GM_ROLE)
        if not gm_role:
            return await interaction.edit_original_response(
                embed=ErrorEmbed(description="General Manager role not found in guild.")
            )

        try:
            log.debug(f"Creating franchise: {name}")
            f: Franchise = await self.create_franchise(guild, name, prefix, gm)
        except RscException as exc:
            await interaction.edit_original_response(
                embed=ApiExceptionErrorEmbed(exc),
                view=None,
            )
            return

        # Create franchise role
        frole_name = f"{name} ({f.gm.rsc_name})"
        existing_frole = discord.utils.get(guild.roles, name=frole_name)
        if not existing_frole:
            log.debug(f"Creating new franchise role: {frole_name}")
            frole = await guild.create_role(
                name=f"{name} ({f.gm.rsc_name})", reason="New franchise created"
            )
        else:
            log.debug("Franchise role already exists")

        await gm.add_roles(frole, gm_role)

        # Update GM Prefix
        gm_name = await utils.remove_prefix(gm)
        await gm.edit(nick=f"{prefix} | {gm_name}")

        embed = SuccessEmbed(description="Franchise has been created.")
        embed.add_field(name="Name", value=name, inline=True)
        embed.add_field(name="GM", value=gm.mention, inline=True)
        await interaction.edit_original_response(embed=embed, view=None)

    @_franchise.command(  # type: ignore
        name="transfer", description="Transfer ownership of a franchise"
    )
    @app_commands.describe(franchise="Franchise name", gm="General Manager")
    @app_commands.autocomplete(franchise=FranchiseMixIn.franchise_autocomplete)  # type: ignore
    async def _franchise_transfer(
        self,
        interaction: discord.Interaction,
        franchise: str,
        gm: discord.Member,
    ):
        guild = interaction.guild
        if not guild:
            return

        transfer_view = TransferFranchiseView(interaction, franchise=franchise, gm=gm)
        await transfer_view.prompt()
        # Fetch franchise data during view
        fl = await self.franchises(guild, name=franchise)
        await transfer_view.wait()

        if not fl:
            return await interaction.edit_original_response(
                embed=ErrorEmbed(
                    description="No franchises found with the name **{franchise}**"
                )
            )
        if len(fl) > 1:
            return await interaction.edit_original_response(
                embed=ErrorEmbed(
                    description="Multiple franchises found with the name **{franchise}**"
                )
            )

        if not transfer_view.result:
            return
        log.debug("GM transfer confirmed.")

        # Display working screen
        await interaction.edit_original_response(
            embed=YellowEmbed(
                title="Transferring Franchise",
                description="Please wait while the GM transfer is processed...",
            ),
            view=None,
        )

        fdata = fl.pop()
        if not fdata.id:
            return await interaction.edit_original_response(
                embed=ErrorEmbed(
                    description="API did not return a franchise ID attached to franchise data."
                )
            )

        try:
            log.debug(f"Transferring {franchise} to {gm.id}")
            f: Franchise = await self.transfer_franchise(guild, fdata.id, gm)
        except RscException as exc:
            return await interaction.edit_original_response(
                embed=ApiExceptionErrorEmbed(exc),
                view=None,
            )

        # Get franchise role
        frole = await utils.franchise_role_from_name(guild, franchise)
        if not frole:
            return await interaction.edit_original_response(
                embed=ErrorEmbed(
                    description=f"Franchise was transferred to {gm.mention} but franchise role was not found."
                )
            )

        # Get GM role
        gm_role = await utils.get_gm_role(guild)
        if not gm_role:
            return await interaction.edit_original_response(
                embed=ErrorEmbed(
                    description=f"Franchise was transferred to {gm.mention} but GM role was not found."
                )
            )

        # Get FA role
        fa_role = await utils.get_free_agent_role(guild)
        if not fa_role:
            return await interaction.edit_original_response(
                embed=ErrorEmbed(
                    description=f"Franchise was transferred to {gm.mention} but FA role was not found."
                )
            )

        # Get AGM role
        agm_role = await utils.get_agm_role(guild)
        if not agm_role:
            return await interaction.edit_original_response(
                embed=ErrorEmbed(
                    description=f"Franchise was transferred to {gm.mention} but AGM role was not found."
                )
            )

        # Get captain role
        captain_role = await utils.get_captain_role(guild)
        if not captain_role:
            return await interaction.edit_original_response(
                embed=ErrorEmbed(
                    description=f"Franchise was transferred to {gm.mention} but Captain role was not found."
                )
            )

        # Update franchise role to new GM
        log.debug("Updating Franchise Role")
        await frole.edit(name=f"{f.name} ({f.gm.rsc_name})")

        # Remove old franchise role from new GM if it exist
        new_gm_old_frole = await utils.franchise_role_from_disord_member(gm)
        if new_gm_old_frole:
            await gm.remove_roles(new_gm_old_frole)

        # Update new GM roles and name
        log.debug(f"Adding GM role to {gm.id}")
        await gm.add_roles(gm_role, frole, reason="Promoted to GM")
        await gm.remove_roles(fa_role, captain_role, agm_role, reason="Promoted to GM")
        await gm.edit(nick=await utils.format_discord_prefix(gm, prefix=f.prefix))

        # Remove TierFA role if it exists on new GM
        for role in gm.roles:
            log.debug(f"GM Role: {role.name}")
            if role.name.endswith("FA"):
                log.debug(f"Removing new GM tier FA role: {role}")
                await gm.remove_roles(role, reason="Promoted to GM")
                break

        # Get old gm discord reference
        old_gm = None
        if fdata.gm and fdata.gm.discord_id:
            old_gm = guild.get_member(fdata.gm.discord_id)

        # Update old GM roles and name
        if old_gm:
            former_gm_role = await utils.get_former_gm_role(guild)
            if former_gm_role and former_gm_role not in old_gm.roles:
                await old_gm.add_roles(former_gm_role)

            await old_gm.remove_roles(
                frole, gm_role, captain_role, reason="Removed from GM"
            )
            await old_gm.edit(
                nick=f"FA | {await utils.remove_prefix(old_gm)}",
                reason="Removed from GM",
            )

            # Fetch tier and add tier FA roles
            old_gm_plist = await self.players(guild, discord_id=old_gm.id, limit=1)
            if old_gm_plist:
                old_gm_lp = old_gm_plist.pop(0)
                if old_gm_lp.tier and old_gm_lp.tier.name:
                    await old_gm.add_roles(fa_role, reason="Removed from GM")
                    old_gm_tier = old_gm_lp.tier.name
                    log.debug(f"Old GM Tier: {old_gm_tier}")
                    old_gm_tierfa_role = await utils.get_tier_fa_role(
                        guild, old_gm_tier
                    )
                    log.debug(f"Old GM Tier Role: {old_gm_tierfa_role}")
                    await old_gm.add_roles(old_gm_tierfa_role, reason="Removed from GM")

        tchannel = await self.get_franchise_transaction_channel(guild, franchise)
        if not tchannel:
            return await interaction.followup.send(
                embed=OrangeEmbed(
                    description=f"**{franchise}** has been transferred to {gm.mention} but could not find transaction channel."
                )
            )

        # Update transaction channel permissions
        gm_overwrite = discord.PermissionOverwrite(
            view_channel=True,
            send_messages=True,
            embed_links=True,
            attach_files=True,
            add_reactions=True,
            use_external_emojis=False,
            read_message_history=True,
            read_messages=True,
            use_application_commands=True,
        )

        await tchannel.set_permissions(gm, overwrite=gm_overwrite)
        if old_gm:
            await tchannel.set_permissions(old_gm, overwrite=None)

        await interaction.edit_original_response(
            embed=SuccessEmbed(
                description=f"**{franchise}** has been transferred to {gm.mention}"
            ),
            view=None,
        )
