import logging

import discord
from redbot.core import app_commands

from rsc.admin import AdminMixIn
from rsc.admin.modals import IntentMissingModal
from rsc.embeds import (
    ApiExceptionErrorEmbed,
    BlueEmbed,
    ErrorEmbed,
    GreenEmbed,
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

    @_intents.command(name="set", description="Manually set intent for a player")  # type: ignore
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
            embed.description = (
                f"{member.mention} intent to play has been set to **RETURNING**"
            )
        else:
            embed.description = (
                f"{member.mention} intent to play has been set to **NOT RETURNING**"
            )
        await interaction.edit_original_response(embed=embed, view=None)

    @_intents.command(name="missingrole", description="Configure the Intent to Play missing discord role")  # type: ignore
    async def _intents_set_missing_role_cmd(
        self, interaction: discord.Interaction, role: discord.Role
    ):
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

    @_intents.command(name="missingchannel", description="Configure the Intent to Play missing channel")  # type: ignore
    async def _intents_set_missing_channel_cmd(
        self, interaction: discord.Interaction, channel: discord.TextChannel
    ):
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

    @_intents.command(name="missingmsg", description="Configure the Intent to Play missing message on ping")  # type: ignore
    async def _intents_set_missing_msg_cmd(self, interaction: discord.Interaction):
        guild = interaction.guild
        if not guild:
            return

        intent_modal = IntentMissingModal()
        await interaction.response.send_modal(intent_modal)
        await intent_modal.wait()

        await self._set_intent_missing_message(guild, intent_modal.intent_msg.value)

    @_intents.command(name="populate", description="Apply Intent Missing role to applicable players")  # type: ignore
    async def _intents_populate_role_cmd(self, interaction: discord.Interaction):
        guild = interaction.guild
        if not guild:
            return

        # Check for intent missing role
        intent_role = await self._get_intent_missing_role(guild)
        if not intent_role:
            return await interaction.response.send_message(
                embed=ErrorEmbed(
                    description="Intent missing role has not been configured."
                )
            )

        # Loading embed
        await interaction.response.send_message(
            embed=YellowEmbed(
                title="Intent Role Sync",
                description="Fetching Intent to Play data and applying roles... This can take some time.",
            ),
            ephemeral=True,
        )

        try:
            next_season = await self.next_season(guild)
            if not next_season:
                return await interaction.edit_original_response(
                    embed=ErrorEmbed(
                        description="The next season of RSC has not started yet.",
                    )
                )

            if not next_season.id:
                return await interaction.edit_original_response(
                    embed=ErrorEmbed(
                        description="API returned a Season without an ID. Please open a modmail ticket."
                    )
                )

            intents = await self.player_intents(
                guild, season_id=next_season.id, missing=True
            )
        except LeagueNotConfigured:
            return await interaction.followup.send(
                embed=YellowEmbed(
                    title="Not Configured",
                    description="League ID has not been configured for this guild.",
                )
            )
        except RscException as exc:
            return await interaction.followup.send(embed=ApiExceptionErrorEmbed(exc))

        if not intents:
            return await interaction.edit_original_response(
                embed=GreenEmbed(
                    title="Intent Role Sync",
                    description="There are current no missing intent to play responses.",
                )
            )

        # Clear out original users in role so we don't ping them again
        for rmember in intent_role.members:
            await rmember.remove_roles(intent_role)

        # Loop through intents and add roles
        count = 0
        for i in intents:
            if not (i.player and i.player.player):
                continue

            pid = i.player.player.discord_id
            if not pid:
                continue

            m = guild.get_member(pid)
            if not m:
                continue

            await m.add_roles(intent_role)
            count += 1

        await interaction.edit_original_response(
            embed=BlueEmbed(
                title="Intent Role Sync",
                description=f"Added {intent_role.mention} to {count}/{len(intents)} players",
            )
        )

    @_intents.command(name="ping", description="Send a ping to all players with missing intents")  # type: ignore
    async def _intents_missing_ping_cmd(self, interaction: discord.Interaction):
        guild = interaction.guild
        if not guild:
            return

        intent_msg = await self._get_intent_missing_message(guild)
        if not intent_msg:
            return await interaction.response.send_message(
                embed=ErrorEmbed(
                    description="Intent missing message has not been configured."
                )
            )

        intent_role = await self._get_intent_missing_role(guild)
        if not intent_role:
            return await interaction.response.send_message(
                embed=ErrorEmbed(
                    description="Intent missing role has not been configured."
                )
            )

        intent_channel = await self._get_intent_channel(guild)
        if not intent_channel:
            return await interaction.response.send_message(
                embed=ErrorEmbed(
                    description="Intent missing channel has not been configured."
                )
            )

        await intent_channel.send(
            content=f"{intent_role.mention} {intent_msg}",
            allowed_mentions=discord.AllowedMentions(roles=True, users=True),
        )
