import logging
from datetime import datetime

import discord
from redbot.core import app_commands

from rsc.admin import AdminMixIn
from rsc.embeds import (
    ApiExceptionErrorEmbed,
    BlueEmbed,
    ErrorEmbed,
    ExceptionErrorEmbed,
    SuccessEmbed,
)
from rsc.enums import Platform, PlayerType, Referrer, RegionPreference, Status
from rsc.exceptions import RscException
from rsc.logs import GuildLogAdapter
from rsc.teams import TeamMixIn
from rsc.tiers import TierMixIn
from rsc.transactions.roles import update_league_player_discord
from rsc.utils import utils

logger = logging.getLogger("red.rsc.admin.members")
log = GuildLogAdapter(logger)


class AdminMembersMixIn(AdminMixIn):
    def __init__(self):
        log.debug("Initializing AdminMixIn:Members")

        super().__init__()

    _members = app_commands.Group(
        name="members",
        description="RSC Member Management Commands",
        parent=AdminMixIn._admin,
        guild_only=True,
        default_permissions=discord.Permissions(manage_guild=True),
    )

    @_members.command(name="namehistory", description="Get an RSC discord members API name history")  # type: ignore
    @app_commands.describe(
        member="RSC discord member",
    )
    async def _member_namehistory_cmd(
        self,
        interaction: discord.Interaction,
        member: discord.Member,
    ):
        guild = interaction.guild
        if not guild:
            return

        await interaction.response.defer(ephemeral=False)

        try:
            history = await self.name_history(guild, member)
        except RscException as exc:
            await interaction.followup.send(
                embed=ApiExceptionErrorEmbed(exc), ephemeral=False
            )
            return

        log.debug(f"History: {history}")
        embed = BlueEmbed(title="Name History")

        if not history:
            embed.description = (
                f"{member.mention} does not have any past name changes in the API."
            )
            return await interaction.followup.send(embed=embed)
        else:
            embed.description = f"Member: {member.mention}"

        history.sort(
            key=lambda x: x.date_changed if x.date_changed else "None", reverse=True
        )
        log.debug(f"Post sort: {history}")

        embed.add_field(name="API Name", value="\n".join([h.old_name for h in history]))
        embed.add_field(
            name="Date",
            value="\n".join(
                [
                    (
                        h.date_changed.strftime("%-m/%-d/%y")
                        if isinstance(h.date_changed, datetime)
                        else "None"
                    )
                    for h in history
                ]
            ),
        )
        await interaction.followup.send(embed=embed)

    @_members.command(name="changename", description="Change RSC name for a member")  # type: ignore
    @app_commands.describe(
        member="RSC discord member",
        name="New player name",
        tracker="Add a tracker link to the user. (Optional)",
    )
    async def _member_changename(
        self,
        interaction: discord.Interaction,
        member: discord.Member,
        name: str,
        tracker: str | None = None,
    ):
        guild = interaction.guild
        if not guild:
            return

        await interaction.response.defer(ephemeral=False)

        try:
            if tracker:
                await self.add_tracker(guild, member, tracker)
            mdata = await self.change_member_name(guild, id=member.id, name=name)
        except RscException as exc:
            await interaction.followup.send(
                embed=ApiExceptionErrorEmbed(exc), ephemeral=False
            )
            return

        # Update nickname in RSC
        accolades = await utils.member_accolades(member)
        pfx = await utils.get_prefix(member)

        if pfx:
            new_nick = f"{pfx} | {name} {accolades}".strip()
        else:
            new_nick = f"{name} {accolades}".strip()

        try:
            await member.edit(nick=new_nick)
        except discord.Forbidden as exc:
            await interaction.followup.send(
                content=f"Unable to update nickname {member.mention}: {exc}"
            )

        # Update franchise role if player is GM
        if mdata.elevated_roles:
            for elevated in mdata.elevated_roles:
                if elevated.gm and elevated.league.id == self._league[guild.id]:
                    frole = await utils.franchise_role_from_disord_member(member)
                    if not frole:
                        return await interaction.followup.send(
                            embed=ErrorEmbed(
                                description=f"Name change was successful but could not find {member.mention} franchise role. Unable to update GM name in role, Please open a modmail ticket."
                            )
                        )

                    fsplit = frole.name.split("(", maxsplit=1)
                    if len(fsplit) != 2:
                        return await interaction.followup.send(
                            embed=ErrorEmbed(
                                description=f"Error updating franchise role {frole.mention}. Unable to parse name and GM."
                            )
                        )

                    log.debug("Updating Franchise Role")
                    fname = fsplit[0].strip()
                    await frole.edit(name=f"{fname} ({name})")

        await interaction.followup.send(
            embed=SuccessEmbed(
                description=f"Player RSC name has been updated to {member.mention}"
            )
        )

    @_members.command(name="transfer", description="Transfer membership to a new Discord account")  # type: ignore
    @app_commands.describe(
        old="Old Discord ID",
        new="New Discord Member",
    )
    async def _member_transfer(
        self,
        interaction: discord.Interaction,
        old: str,
        new: discord.Member,
    ):
        guild = interaction.guild
        if not guild:
            return

        # App commands have issues with discord ID as ints being invalid.
        # Use a string and convert it
        try:
            old_discord_id = int(old.strip())
            log.debug(f"Looking up league player discord ID: {old_discord_id}")
        except ValueError:
            return await interaction.response.send_message(
                embed=ErrorEmbed(description="Old Discord ID must be a number")
            )

        await interaction.response.defer()
        # Transfer membership to new account
        try:
            await self.transfer_membership(
                guild=guild,
                old=old_discord_id,
                new=new,
            )
        except RscException as exc:
            await interaction.followup.send(
                embed=ApiExceptionErrorEmbed(exc), ephemeral=True
            )
            return

        await interaction.followup.send(
            embed=SuccessEmbed(
                description=f"Transferred membership of {old} to {new.mention}"
            ),
        )

    @_members.command(name="patch", description="Patch a league player in the API")  # type: ignore
    @app_commands.describe(
        player="Discord member to patch",
        status="Player status",
        tier="Tier name",
        team="Team name",
        base_mmr="Base MMR",
        current_mmr="Current MMR",
    )
    @app_commands.autocomplete(
        tier=TierMixIn.tier_autocomplete, team=TeamMixIn.teams_autocomplete
    )
    async def _member_patch_cmd(
        self,
        interaction: discord.Interaction,
        player: discord.Member,
        status: Status | None = None,
        tier: str | None = None,
        team: str | None = None,
        base_mmr: int | None = None,
        current_mmr: int | None = None,
    ):
        guild = interaction.guild
        if not guild:
            return
        await interaction.response.defer()

        # Get Tier ID
        tid = None
        tier_list = []
        try:
            plist = await self.players(guild, discord_id=player.id, limit=1)
            if tier:
                tier_list = await self.tiers(guild)
                tid = await self.tier_id_by_name(guild, tier=tier)
                log.debug(f"Tier ID: {tid}")
        except RscException as exc:
            return await interaction.followup.send(
                embed=ApiExceptionErrorEmbed(exc), ephemeral=True
            )
        except ValueError as exc:
            return await interaction.followup.send(
                embed=ExceptionErrorEmbed(exc_message=str(exc))
            )

        if not plist:
            return await interaction.response.send_message(
                embed=ErrorEmbed(
                    description="Player was updated but league player does not exist."
                )
            )

        lplayer = plist.pop(0)
        if not lplayer.id:
            return await interaction.response.send_message(
                embed=ErrorEmbed(description="LeaguePlayer object has no ID")
            )

        # Patch Player
        try:
            log.debug(f"Updating League Player ID: {lplayer.id}")
            result = await self.update_league_player(
                guild=guild,
                player_id=lplayer.id,
                current_mmr=current_mmr,
                base_mmr=base_mmr,
                tier=tid,
                status=status,
                team=team,
            )
            # Get updated league player object
            plist = await self.players(guild, discord_id=player.id, limit=1)
        except RscException as exc:
            return await interaction.followup.send(
                embed=ApiExceptionErrorEmbed(exc), ephemeral=True
            )
        except ValueError as exc:
            return await interaction.followup.send(
                embed=ExceptionErrorEmbed(exc_message=str(exc))
            )

        if not plist:
            return await interaction.response.send_message(
                embed=ErrorEmbed(
                    description="Player was updated but league player does not exist."
                )
            )

        # Update discord roles, etc
        try:
            log.debug("Updating player in discord")
            lplayer = plist.pop(0)
            await update_league_player_discord(
                guild=guild, player=player, league_player=lplayer, tiers=tier_list
            )
        except (ValueError, AttributeError) as exc:
            return await interaction.followup.send(
                embed=ExceptionErrorEmbed(exc_message=str(exc))
            )

        # Craft embed
        embed = BlueEmbed(title="League Player Updated")
        if tier:
            tcolor = await utils.tier_color_by_name(guild, name=tier)
            embed.colour = tcolor

        # Format player status
        pstatus = "Error"
        if result.status:
            pstatus = Status(result.status).full_name

        team_name = "None"
        if result.team and result.team.name:
            team_name = result.team.name

        tier = "None"
        if result.tier and result.tier.name and result.tier.id:
            tier = f"{result.tier.name} ({result.tier.id})"

        embed.add_field(name="Player", value=player.mention, inline=True)
        embed.add_field(name="Status", value=pstatus, inline=True)
        embed.add_field(name="", value="", inline=False)  # Line Break
        embed.add_field(name="Team", value=team_name, inline=True)
        embed.add_field(name="Tier", value=tier, inline=True)
        embed.add_field(name="", value="", inline=False)  # Line Break
        embed.add_field(name="Base MMR", value=str(result.base_mmr), inline=True)
        embed.add_field(name="Current MMR", value=str(result.current_mmr), inline=True)

        await interaction.followup.send(embed=embed)

    @_members.command(name="create", description="Create an RSC member in the API")  # type: ignore
    @app_commands.describe(
        member="Discord member being added",
        rsc_name="RSC player name (Defaults to members display name)",
    )
    async def _member_create(
        self,
        interaction: discord.Interaction,
        member: discord.Member,
        rsc_name: str | None = None,
    ):
        if not interaction.guild:
            return

        try:
            await self.create_member(
                interaction.guild,
                member=member,
                rsc_name=rsc_name or member.display_name,
            )
        except RscException as exc:
            await interaction.response.send_message(
                embed=ApiExceptionErrorEmbed(exc), ephemeral=True
            )
            return

        # Change nickname if specified
        if rsc_name:
            await member.edit(nick=rsc_name)

        await interaction.response.send_message(
            embed=SuccessEmbed(
                description=f"{member.mention} has been created in the RSC API."
            ),
            ephemeral=True,
        )

    @_members.command(name="delete", description="Delete an RSC member in the API")  # type: ignore
    @app_commands.describe(member="RSC discord member")
    async def _member_delete(
        self, interaction: discord.Interaction, member: discord.Member
    ):
        if not interaction.guild:
            return

        try:
            await self.delete_member(interaction.guild, member=member)
        except RscException as exc:
            await interaction.response.send_message(
                embed=ApiExceptionErrorEmbed(exc), ephemeral=True
            )
            return
        await interaction.response.send_message(
            embed=SuccessEmbed(
                description=f"{member.mention} has been deleted from the RSC API."
            ),
            ephemeral=True,
        )

    @_members.command(  # type: ignore
        name="list", description="Fetch a list of members based on specified criteria."
    )
    @app_commands.describe(
        rsc_name="RSC in-game player name (Do not include prefix)",
        discord_username="Player discord username without discriminator",
        discord_id="Player discord ID",
        limit="Number of results to return (Default: 10, Max: 64)",
        offset="Return results starting at specified offset (Default: 0)",
    )
    async def _member_list(
        self,
        interaction: discord.Interaction,
        rsc_name: str | None = None,
        discord_username: str | None = None,
        discord_id: str | None = None,
        limit: app_commands.Range[int, 1, 64] = 10,
        offset: app_commands.Range[int, 0, 64] = 0,
    ):
        guild = interaction.guild
        if not guild:
            return

        if not (rsc_name or discord_username or discord_id):
            await interaction.response.send_message(
                "You must specify at least one search option.", ephemeral=True
            )
            return

        discord_id_int = None
        if discord_id:
            try:
                discord_id_int = int(discord_id)
            except ValueError:
                await interaction.response.send_message(
                    "Discord ID must be an integer.", ephemeral=True
                )
                return

        await interaction.response.defer(ephemeral=True)
        ml = await self.members(
            guild,
            rsc_name=rsc_name,
            discord_username=discord_username,
            discord_id=discord_id_int,
            limit=limit,
            offset=offset,
        )

        league_id = self._league[guild.id]
        m_fmt = []
        for m in ml:
            player = None
            if m.discord_id:
                p_member = guild.get_member(m.discord_id)
                if p_member:
                    player = p_member.mention
            else:
                player = m.rsc_name

            league = None
            if m.player_leagues:
                league = next(
                    (i for i in m.player_leagues if i.league.id == league_id), None
                )

            status = "Spectator"
            if league and league.status:
                status = Status(league.status).full_name

            m_fmt.append(
                (
                    player,
                    m.discord_id,
                    status,
                )
            )

        embed = BlueEmbed(
            title="RSC Member Results",
            description="The following members matched the specified criteria",
        )
        embed.add_field(
            name="Member", value="\n".join([str(x[0]) for x in m_fmt]), inline=True
        )
        embed.add_field(
            name="ID", value="\n".join([str(x[1]) for x in m_fmt]), inline=True
        )
        embed.add_field(
            name="Status", value="\n".join([x[2] for x in m_fmt]), inline=True
        )

        if embed.exceeds_limits():
            await interaction.followup.send(
                content="Result exceeds discord character limits. Please refine your search."
            )
            return

        await interaction.followup.send(embed=embed, ephemeral=True)

    @_members.command(name="signup", description="Sign a player up for the latest RSC season")  # type: ignore
    @app_commands.describe(
        player_type="New or Former Player",
        member="Discord member being added",
        rsc_name="RSC player name (Defaults to members display name)",
        tracker="Rocket league tracker link",
        platform="Preferred platform",
        override="Admin override",
    )
    async def _admin_member_signup_cmd(
        self,
        interaction: discord.Interaction,
        player_type: PlayerType,
        member: discord.Member,
        rsc_name: str | None = None,
        tracker: str | None = None,
        platform: Platform = Platform.STEAM,
        override: bool = False,
    ):
        if not interaction.guild or not isinstance(interaction.user, discord.Member):
            return

        await interaction.response.defer()
        trackers = [tracker] if tracker else []

        try:
            await self.signup(
                interaction.guild,
                member=member,
                rsc_name=rsc_name or member.display_name,
                trackers=trackers,
                player_type=player_type,
                platform=platform,
                region_preference=RegionPreference.EAST,
                referrer=Referrer.OTHER,
                executor=interaction.user,
                override=override,
            )
        except RscException as exc:
            await interaction.followup.send(
                embed=ApiExceptionErrorEmbed(exc), ephemeral=True
            )
            return

        # Change nickname if specified
        if rsc_name:
            await member.edit(nick=rsc_name)

        await interaction.followup.send(
            embed=SuccessEmbed(
                description=f"{member.mention} has been signed up for the latest season of RSC."
            )
        )
