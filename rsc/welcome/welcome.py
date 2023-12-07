import logging
import discord

from redbot.core import Config, app_commands, commands, checks

from rsc.abc import RSCMixIn
from rsc.embeds import SuccessEmbed, BlueEmbed

from typing import List, Optional

log = logging.getLogger("red.rsc.welcome")

defaults_guild = {
    "WelcomeChannel": None,
    "WelcomeMsg": None,
    "WelcomeRoles": [],
}

class WelcomeMixIn(RSCMixIn):
    def __init__(self):
        log.debug("Initializing WelcomeMixIn")
        # Prepare configuration group
        self.config.init_custom("Welcome", 1)
        self.config.register_custom("Welcome", **defaults_guild)
        super().__init__()

    # Listeners

    @commands.Cog.listener("on_member_join")
    async def on_join_welcome(self, member: discord.Member):
        # Assign role(s) to user
        wroles = await self._get_welcome_roles(member.guild)
        if wroles:
            await member.add_roles(*wroles)

        # Check if welcome channel is set
        wchan = await self._get_welcome_channel(member.guild)
        if not wchan:
            return

        # Check if welcome msg is set, and send it to channel
        wmsg = await self._get_welcome_msg(member.guild)
        if wmsg:
            await wchan.send(content=wmsg, allowed_mentions=discord.AllowedMentions(users=True))

    # Group

    _rsc_welcome = app_commands.Group(
        name="welcome",
        description="Welcome settings for new members",
        guild_only=True,
        default_permissions=discord.Permissions(manage_roles=True),
    )

    @_rsc_welcome.command(
        name="settings", description="Display the current RSC welcome settings."
    )
    async def _rsc_settings(self, interaction: discord.Interaction):
        welcome_channel = await self._get_welcome_channel(interaction.guild)
        welcome_msg = await self._get_welcome_msg(interaction.guild)
        welcome_roles = await self._get_welcome_roles(interaction.guild)

        settings_embed = BlueEmbed(
            title="RSC Welcome Settings",
            description="RSC member welcome channel and roles configuration.",
        )
        settings_embed.add_field(name="Welcome Channel", value=welcome_channel.mention if welcome_channel else welcome_channel, inline=False)
        settings_embed.add_field(name="Welcome Roles", value="\n".join([x.mention for x in welcome_roles]), inline=False)
        settings_embed.add_field(name="Welcome Message", value=welcome_msg, inline=False)
        await interaction.response.send_message(embed=settings_embed, ephemeral=True)

    @_rsc_welcome.command(
        name="channel",
        description="Modify the welcome channel",
    )
    async def _rsc_welcome_channel(
        self, interaction: discord.Interaction, channel: discord.TextChannel
    ):
        await self._set_welcome_channel(interaction.guild, channel)
        await interaction.response.send_message(
            embed=SuccessEmbed(
                description=f"Welcome channel has been set to {channel.mention}"
            ),
            ephemeral=True
        )

    @_rsc_welcome.command(
        name="message",
        description="Modify the welcome message when a user joins the server (Max 512 characters)",
    )
    async def _rsc_welcome_msg(
        self,
        interaction: discord.Interaction,
        msg: app_commands.Range[str, 1, 512]
    ):
        await self._set_welcome_msg(interaction.guild, msg)

        embed = SuccessEmbed(title="Welcome Message Configured", description=msg)
        await interaction.response.send_message(embed=embed, ephemeral=True)

    @_rsc_welcome.command(
        name="roles",
        description="Modify the roles a user receives when joining the server",
    )
    async def _rsc_welcome_roles(
        self,
        interaction: discord.Interaction,
        role1: discord.Role,
        role2: Optional[discord.Role]=None,
        role3: Optional[discord.Role]=None,
        role4: Optional[discord.Role]=None,
    ):
        roles = [role1]
        if role2:
            roles.append(role2)
        if role3:
            roles.append(role3)
        if role4:
            roles.append(role4)
        
        await self._set_welcome_roles(interaction.guild, roles)

        embed = SuccessEmbed(description="Welcome roles have been configured.")
        embed.add_field(name="Roles", value="\n".join([r.mention for r in roles]), inline=False)
        await interaction.response.send_message(embed=embed, ephemeral=True)


    # Settings

    async def _get_welcome_channel(
        self, guild: discord.Guild
    ) -> Optional[discord.TextChannel]:
        c = await self.config.custom("Welcome", guild.id).WelcomeChannel()
        return guild.get_channel(c)

    async def _set_welcome_channel(
        self, guild: discord.Guild, channel: discord.TextChannel
    ):
        await self.config.custom("Welcome", guild.id).WelcomeChannel.set(channel.id)

    async def _get_welcome_roles(self, guild: discord.Guild) -> List[discord.Role]:
        roles = []
        notFound = False
        r_ids = await self.config.custom("Welcome", guild.id).WelcomeRoles()
        for id in r_ids:
            r = guild.get_role(id) 
            if not r:
                notFound = True
                continue
            roles.append(r)
        # Update saved roles if one or more don't exist
        if notFound:
            await self._set_welcome_roles(guild, roles)
        return roles

    async def _set_welcome_roles(self, guild: discord.Guild, roles: List[discord.Role]):
        await self.config.custom("Welcome", guild.id).WelcomeRoles.set([x.id for x in roles])

    async def _get_welcome_msg(self, guild: discord.Guild) -> Optional[str]:
        return await self.config.custom("Welcome", guild.id).WelcomeMsg()

    async def _set_welcome_msg(self, guild: discord.Guild, msg: str):
        await self.config.custom("Welcome", guild.id).WelcomeMsg.set(msg)