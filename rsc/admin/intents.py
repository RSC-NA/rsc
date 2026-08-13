import logging
from datetime import UTC, datetime

import discord
from redbot.core import app_commands
from rscapi.models.season import Season

from rsc.admin import AdminMixIn
from rsc.admin.modals import IntentMissingModal
from rsc.admin.views import DMConfirmView, build_intent_dm_view
from rsc.embeds import (
    ApiExceptionErrorEmbed,
    BlueEmbed,
    ErrorEmbed,
    GreenEmbed,
    OrangeEmbed,
    SuccessEmbed,
    YellowEmbed,
)
from rsc.exceptions import LeagueNotConfigured, RscException
from rsc.logs import GuildLogAdapter

logger = logging.getLogger("red.rsc.admin.intents")
log = GuildLogAdapter(logger)


class AdminIntentsMixIn(AdminMixIn):
    def __init__(self):
        log.debug("Initializing AdminMixIn:Intents")

        super().__init__()

    _intents = app_commands.Group(
        name="intents",
        description="Manage player Intent to Play settings",
        parent=AdminMixIn._admin,
        guild_only=True,
        default_permissions=discord.Permissions(manage_guild=True),
    )

    @_intents.command(name="set", description="Manually set intent for a player")
    @app_commands.describe(
        member="Discord member to declare intent on",
        returning="Returning status. (True for returning, False for not returning)",
        override="Admin override",
    )
    @app_commands.guild_only
    async def _admin_intents_set_cmd(
        self,
        interaction: discord.Interaction,
        member: discord.Member,
        returning: bool,
        override: bool = False,
    ):
        guild = interaction.guild
        if not guild or not isinstance(interaction.user, discord.Member):
            return

        # Process intent
        await interaction.response.defer()
        try:
            result = await self.declare_intent(
                guild=guild,
                member=member,
                returning=returning,
                executor=interaction.user,
                admin_overrride=override,
            )
            log.debug(f"Intent Result: {result}")
        except RscException as exc:
            if exc.status == 409:
                return await interaction.edit_original_response(
                    embed=YellowEmbed(title="Intent to Play", description=exc.reason),
                )
            return await interaction.edit_original_response(
                embed=ApiExceptionErrorEmbed(exc),
            )

        embed: discord.Embed = SuccessEmbed(title="Intent to Play Declared")
        if returning:
            embed.description = f"{member.mention} intent to play has been set to **RETURNING**"
        else:
            embed.description = f"{member.mention} intent to play has been set to **NOT RETURNING**"
        await interaction.edit_original_response(embed=embed, view=None)

    @_intents.command(name="setbyid", description="Manually set intent for a discord ID")
    @app_commands.describe(
        member="Discord ID to declare intent on",
        returning="Returning status. (True for returning, False for not returning)",
        override="Admin override",
    )
    @app_commands.guild_only
    async def _admin_intents_setbyid_cmd(
        self,
        interaction: discord.Interaction,
        member: int,
        returning: bool,
        override: bool = False,
    ):
        guild = interaction.guild
        if not guild or not isinstance(interaction.user, discord.Member):
            return

        # Process intent
        await interaction.response.defer()
        try:
            result = await self.declare_intent(
                guild=guild,
                member=member,
                returning=returning,
                executor=interaction.user,
                admin_overrride=override,
            )
            log.debug(f"Intent Result: {result}")
        except RscException as exc:
            if exc.status == 409:
                return await interaction.edit_original_response(
                    embed=YellowEmbed(title="Intent to Play", description=exc.reason),
                )
            return await interaction.edit_original_response(
                embed=ApiExceptionErrorEmbed(exc),
            )

        embed: discord.Embed = SuccessEmbed(title="Intent to Play Declared")
        if returning:
            embed.description = f"Discord ID {member} intent to play has been set to **RETURNING**"
        else:
            embed.description = f"Discord ID {member} intent to play has been set to **NOT RETURNING**"
        await interaction.edit_original_response(embed=embed, view=None)

    @_intents.command(
        name="missingrole",
        description="Configure the Intent to Play missing discord role",
    )
    async def _intents_set_missing_role_cmd(self, interaction: discord.Interaction, role: discord.Role):
        guild = interaction.guild
        if not guild:
            return

        await self._set_intent_missing_role(guild, role)
        await interaction.response.send_message(
            embed=BlueEmbed(
                title="Intent Missing Role",
                description=f"Intent to Play response missing role has been set to {role.mention}",
            ),
            ephemeral=True,
        )

    @_intents.command(
        name="missingchannel",
        description="Configure the Intent to Play missing channel",
    )
    async def _intents_set_missing_channel_cmd(self, interaction: discord.Interaction, channel: discord.TextChannel):
        guild = interaction.guild
        if not guild:
            return

        await self._set_intent_channel(guild, channel)
        await interaction.response.send_message(
            embed=BlueEmbed(
                title="Intent Missing Channel",
                description=f"Intent to Play response missing channel has been set to {channel.mention}",
            ),
            ephemeral=True,
        )

    @_intents.command(
        name="missingmsg",
        description="Configure the Intent to Play missing message on ping",
    )
    async def _intents_set_missing_msg_cmd(self, interaction: discord.Interaction):
        guild = interaction.guild
        if not guild:
            return

        intent_modal = IntentMissingModal()
        await interaction.response.send_modal(intent_modal)
        await intent_modal.wait()

        await self._set_intent_missing_message(guild, intent_modal.intent_msg.value)

    @_intents.command(name="populate", description="Apply Intent Missing role to applicable players")
    async def _intents_populate_role_cmd(self, interaction: discord.Interaction):
        guild = interaction.guild
        if not guild:
            return

        # Check for intent missing role
        intent_role = await self._get_intent_missing_role(guild)
        if not intent_role:
            return await interaction.response.send_message(embed=ErrorEmbed(description="Intent missing role has not been configured."))

        # Loading embed
        await interaction.response.send_message(
            embed=YellowEmbed(
                title="Intent Role Sync",
                description="Fetching Intent to Play data and applying roles... This can take some time.",
            ),
            ephemeral=True,
        )

        try:
            next_season = await self.next_signup_season(guild)
        except LeagueNotConfigured:
            return await interaction.followup.send(
                embed=YellowEmbed(
                    title="Not Configured",
                    description="League ID has not been configured for this guild.",
                )
            )
        except RscException as exc:
            if exc.type == "SignupsClosedException":
                log.debug("No signup season currently open. Defaulting to current season.")
                next_season = await self.current_season(guild)
            else:
                return await interaction.followup.send(embed=ApiExceptionErrorEmbed(exc))

        if not (next_season and next_season.id and next_season.number):
            return await interaction.followup.send(
                embed=YellowEmbed(
                    title="No Signup Season",
                    description="There is not currently a season open for signups.",
                )
            )

        try:
            intents = await self.player_intents(guild, season_id=next_season.id, missing=True)
        except RscException as exc:
            return await interaction.followup.send(embed=ApiExceptionErrorEmbed(exc))

        if not intents:
            return await interaction.edit_original_response(
                embed=GreenEmbed(
                    title="Intent Role Sync",
                    description="There are current no missing intent to play responses.",
                )
            )

        # Build set of members who should have the role (missing intent)
        missing_members: set[discord.Member] = set()
        for i in intents:
            if not (i.player and i.player.player):
                continue

            pid = i.player.player.discord_id
            if not pid:
                continue

            m = guild.get_member(pid)
            if not m:
                continue

            missing_members.add(m)

        # Members who currently have role but completed their intent
        existing_members = set(intent_role.members)
        to_remove = existing_members - missing_members
        to_add = missing_members - existing_members

        # Remove role from members who completed their intent
        for m in to_remove:
            await m.remove_roles(intent_role)

        # Add role to newly missing members
        for m in to_add:
            await m.add_roles(intent_role)

        await interaction.edit_original_response(
            embed=BlueEmbed(
                title="Intent Role Sync",
                description=(
                    f"Added {intent_role.mention} to {len(to_add)} player(s)\n"
                    f"Removed from {len(to_remove)} player(s) who completed their intent"
                ),
            )
        )

    # Intent DMs
    #
    # Unlike `ping`, these do not use the missing intent role at all. The missing
    # players come straight from the API, so `populate` does not need to have run.

    async def _signup_season_or_error(self, interaction: discord.Interaction, guild: discord.Guild) -> Season | None:
        """Resolve the open signup season, or reply with why it could not be used.

        Deliberately does NOT fall back to `current_season` the way `populate`
        does. There is no point DMing players to declare intent once signups have
        closed, so a closed window aborts instead.
        """
        # `next_signup_season` indexes `_api_conf`/`_league` directly, so an
        # unconfigured guild raises KeyError rather than LeagueNotConfigured.
        # Same guard as `rsc.decorator.apicall`.
        if not (self._api_conf.get(guild.id) and self._league.get(guild.id)):
            await interaction.followup.send(
                embed=YellowEmbed(
                    title="Not Configured",
                    description="This guild has not configured its league and RSC API settings.",
                ),
                ephemeral=True,
            )
            return None

        try:
            season = await self.next_signup_season(guild)
        except RscException as exc:
            if exc.type == "SignupsClosedException":
                await interaction.followup.send(
                    embed=OrangeEmbed(
                        title="Signups Are Closed",
                        description=(
                            "Signups are not currently open, so intent DMs would be pointless.\n\n"
                            "Players who still need to sign up should open a ModMail ticket."
                        ),
                    ),
                    ephemeral=True,
                )
                return None
            await interaction.followup.send(embed=ApiExceptionErrorEmbed(exc), ephemeral=True)
            return None

        if not (season and season.id and season.number):
            await interaction.followup.send(
                embed=YellowEmbed(
                    title="No Signup Season",
                    description="There is not currently a season open for signups.",
                ),
                ephemeral=True,
            )
            return None

        return season

    async def _build_intent_dm_embed(self, guild: discord.Guild, season: Season, custom_message: str | None = None) -> discord.Embed:
        """Build the DM body sent to players with a missing intent.

        Deliberately does not fall back to the configured `IntentMissingMsg`. That
        string is written for `/admin intents ping`, where it is appended after a
        role mention in a channel, so it tends to read wrong as a standalone DM.
        Use the `message` parameter to override this body.
        """
        description = custom_message or (
            f"You have **not** declared your Intent to Play for **Season {season.number}**.\n\n"
            "Please let us know whether you plan to return using the buttons below."
        )

        intent_channel = await self._get_intent_channel(guild)
        fallback = "\n\nYou can also run `/signup` in the server"
        if intent_channel:
            fallback += f" or head to [#{intent_channel.name}](https://discord.com/channels/{guild.id}/{intent_channel.id})"
        description += f"{fallback}."

        embed = YellowEmbed(
            title=f"Intent to Play - Season {season.number}",
            description=description,
        )
        if guild.icon:
            embed.set_thumbnail(url=guild.icon.url)
        embed.set_footer(text=guild.name)
        return embed

    async def _resolve_missing_members(self, guild: discord.Guild, season_id: int) -> tuple[list[discord.Member], list[int], list[int]]:
        """Split missing intents into DM-able members, players who left, and lookup failures."""
        intents = await self.player_intents(guild, season_id=season_id, missing=True)

        ids: list[int] = []
        for i in intents:
            if not (i.player and i.player.player):
                continue
            pid = i.player.player.discord_id
            if pid:
                ids.append(pid)

        return await self._resolve_members_by_id(guild, ids)

    async def _dm_single_player(
        self,
        interaction: discord.Interaction,
        guild: discord.Guild,
        season: Season,
        member: discord.Member,
        message: str | None,
    ):
        """Nudge one specific player. Sent directly rather than queued."""
        if not (season.id and season.number):
            return

        try:
            intents = await self.player_intents(guild, season_id=season.id, player=member, missing=True)
        except RscException as exc:
            return await interaction.followup.send(embed=ApiExceptionErrorEmbed(exc), ephemeral=True)

        if not intents:
            return await interaction.followup.send(
                embed=YellowEmbed(
                    title="Nothing To Send",
                    description=f"{member.mention} has already declared their intent for **Season {season.number}**.",
                ),
                ephemeral=True,
            )

        embed = await self._build_intent_dm_embed(guild, season, custom_message=message)
        try:
            await member.send(embed=embed, view=build_intent_dm_view(guild.id, season.number))
        except discord.Forbidden:
            return await interaction.followup.send(
                embed=ErrorEmbed(description=f"{member.mention} has DMs disabled."),
                ephemeral=True,
            )
        except discord.HTTPException as exc:
            log.warning(f"Unable to DM {member.id}: {exc}", guild=guild)
            return await interaction.followup.send(
                embed=ErrorEmbed(description=f"Unable to DM {member.mention}. Please try again."),
                ephemeral=True,
            )

        log.info(f"{interaction.user} sent an intent reminder to {member}", guild=guild)
        await interaction.followup.send(
            embed=GreenEmbed(title="Intent DM Sent", description=f"Reminder sent to {member.mention}."),
            ephemeral=True,
        )

    @_intents.command(name="dmtest", description="Preview the Intent to Play DM by sending it to yourself")
    @app_commands.describe(message="Custom message to include in the DM (optional)")
    async def _intents_dm_test_cmd(self, interaction: discord.Interaction, message: str | None = None):
        guild = interaction.guild
        if not guild:
            return

        await interaction.response.defer(ephemeral=True)

        season = await self._signup_season_or_error(interaction, guild)
        if not (season and season.number):
            return

        embed = await self._build_intent_dm_embed(guild, season, custom_message=message)
        view = build_intent_dm_view(guild.id, season.number)

        try:
            await interaction.user.send(embed=embed, view=view)
        except discord.Forbidden:
            return await interaction.followup.send(
                embed=ErrorEmbed(description="Unable to DM you. Check your DM settings."),
                ephemeral=True,
            )

        await interaction.followup.send(
            embed=GreenEmbed(description="Test DM sent. Check your direct messages."),
            ephemeral=True,
        )

    def _still_missing_intent(self, guild: discord.Guild, season_id: int, member: discord.Member):
        """Build a send-time check that the player still has not declared.

        A batch takes minutes to drain, so a player may declare between queueing
        and delivery. Cheaper than a redundant DM, and the button would only 409.
        """

        async def check() -> bool:
            intents = await self.player_intents(guild, season_id=season_id, player=member, missing=True)
            return bool(intents)

        return check

    @_intents.command(name="dm", description="DM players who have not declared their Intent to Play")
    @app_commands.describe(
        member="DM only this player instead of everyone with a missing intent",
        message="Custom message to include in the DM (optional)",
    )
    async def _intents_dm_cmd(
        self,
        interaction: discord.Interaction,
        member: discord.Member | None = None,
        message: str | None = None,
    ):
        guild = interaction.guild
        if not guild:
            return

        await interaction.response.defer(ephemeral=True)

        season = await self._signup_season_or_error(interaction, guild)
        if not (season and season.id and season.number):
            return

        # Single player nudge. No confirmation gate - the blast radius is one DM.
        if member:
            return await self._dm_single_player(interaction, guild, season, member, message)

        try:
            to_dm, left_guild, lookup_failed = await self._resolve_missing_members(guild, season.id)
        except RscException as exc:
            return await interaction.followup.send(embed=ApiExceptionErrorEmbed(exc), ephemeral=True)

        if not (to_dm or left_guild or lookup_failed):
            return await interaction.followup.send(
                embed=GreenEmbed(
                    title="Intent to Play",
                    description="There are currently no missing intent to play responses.",
                ),
                ephemeral=True,
            )

        if not to_dm:
            return await interaction.followup.send(
                embed=YellowEmbed(
                    title="Nobody To DM",
                    description=(
                        f"All **{len(left_guild) + len(lookup_failed)}** player(s) with a missing intent "
                        "are unreachable. They have left the server or could not be looked up."
                    ),
                ),
                ephemeral=True,
            )

        # Confirmation gate
        desc = (
            f"About to DM **{len(to_dm)}** player(s) with a missing intent for **Season {season.number}**.\n\n"
            f"Skipped (left the server): **{len(left_guild)}**\n"
            f"Skipped (lookup failed): **{len(lookup_failed)}**"
        )
        last_season, last_run, last_executor = await self._get_intent_dm_last_run(guild)
        if last_season == season.number and last_run:
            # <t:...:F> renders in each admin's own timezone
            by = f" by <@{last_executor}>" if last_executor else ""
            desc += f"\n\n\N{WARNING SIGN} Intent DMs were already sent for this season on <t:{last_run}:F>{by}."

        confirm_embed = BlueEmbed(title="Confirm Intent DMs", description=desc)
        # Show who, not just how many. Truncates to the embed field limit.
        confirm_embed.add_field(
            name="Recipients",
            value=self._format_truncated_list([m.mention for m in to_dm]),
            inline=False,
        )

        confirm_view = DMConfirmView(interaction, confirm_embed, loading_title="Queueing Intent DMs")
        await confirm_view.prompt()
        await confirm_view.wait()

        if not confirm_view.result:
            return

        # Claim the run before queueing so a second admin confirming concurrently
        # sees the warning rather than double DMing everyone.
        await self._set_intent_dm_last_run(guild, season.number, int(datetime.now(UTC).timestamp()), interaction.user.id)
        log.info(f"{interaction.user} queued intent DMs for {len(to_dm)} player(s) in S{season.number}", guild=guild)

        dm_embed = await self._build_intent_dm_embed(guild, season, custom_message=message)

        queued = 0
        for player in to_dm:
            # A fresh view per DM. `send()` stores the view against the message id,
            # so a shared instance would have its cache key rewritten on every send.
            await self._dm_helper.enqueue(
                player,
                embed=dm_embed,
                view=build_intent_dm_view(guild.id, season.number),
                precheck=self._still_missing_intent(guild, season.id, player),
            )
            queued += 1

        result = f"**{queued}** DMs queued. Use `/admin dmstatus` to track progress, `/admin dmcancel` to abort."
        if left_guild:
            result += f"\n\nSkipped **{len(left_guild)}** player(s) who left the server."
        if lookup_failed:
            result += f"\nSkipped **{len(lookup_failed)}** player(s) that could not be looked up."

        await interaction.edit_original_response(
            embed=GreenEmbed(title="Intent DMs Queued", description=result),
            view=None,
        )

    @_intents.command(name="ping", description="Send a ping to all players with missing intents")
    async def _intents_missing_ping_cmd(self, interaction: discord.Interaction):
        guild = interaction.guild
        if not guild:
            return

        intent_msg = await self._get_intent_missing_message(guild)
        if not intent_msg:
            return await interaction.response.send_message(embed=ErrorEmbed(description="Intent missing message has not been configured."))

        intent_role = await self._get_intent_missing_role(guild)
        if not intent_role:
            return await interaction.response.send_message(embed=ErrorEmbed(description="Intent missing role has not been configured."))

        intent_channel = await self._get_intent_channel(guild)
        if not intent_channel:
            return await interaction.response.send_message(embed=ErrorEmbed(description="Intent missing channel has not been configured."))

        await intent_channel.send(
            content=f"{intent_role.mention} {intent_msg}",
            allowed_mentions=discord.AllowedMentions(roles=True, users=True),
        )

        await interaction.response.send_message(embed=SuccessEmbed(description=f"Pinged {intent_role.mention} in {intent_channel.mention}"))
