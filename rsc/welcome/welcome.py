import logging

import discord
from redbot.core import app_commands, commands

from rsc.abc import RSCMixIn
from rsc.embeds import BlueEmbed, SuccessEmbed
from rsc.types import WelcomeSettings

log = logging.getLogger("red.rsc.welcome")

defaults_guild = WelcomeSettings(WelcomeChannel=None, WelcomeMsg=None, WelcomeRoles=[], WelcomeStatus=False)


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
            await wchan.send(
                content=wmsg.format(member=member),
                allowed_mentions=discord.AllowedMentions(users=True),
            )

    # Group

    _rsc_welcome = app_commands.Group(
        name="welcome",
        description="Welcome settings for new members",
        guild_only=True,
        default_permissions=discord.Permissions(manage_roles=True),
    )

    @_rsc_welcome.command(  # type: ignore[type-var]
        name="settings", description="Display the current RSC welcome settings."
    )
    async def _rsc_welcome_settings(self, interaction: discord.Interaction):
        guild = interaction.guild
        if not guild:
            return

        welcome_channel = await self._get_welcome_channel(guild)
        welcome_msg = await self._get_welcome_msg(guild)
        welcome_roles = await self._get_welcome_roles(guild)
        welcome_active = await self._get_welcome_status(guild)

        settings_embed = BlueEmbed(
            title="RSC Welcome Settings",
            description="RSC member welcome channel and roles configuration.",
        )
        settings_embed.add_field(name="Enabled", value=str(welcome_active), inline=False)
        settings_embed.add_field(
            name="Welcome Channel",
            value=welcome_channel.mention if welcome_channel else welcome_channel,
            inline=False,
        )
        settings_embed.add_field(
            name="Welcome Roles",
            value="\n".join([x.mention for x in welcome_roles]),
            inline=False,
        )
        settings_embed.add_field(name="Welcome Message", value=welcome_msg, inline=False)
        await interaction.response.send_message(embed=settings_embed, ephemeral=True)

    @_rsc_welcome.command(  # type: ignore[type-var]
        name="toggle", description="Toggle the welcome message on or off"
    )
    async def _rsc_welcome_toggle(self, interaction: discord.Interaction):
        if not interaction.guild:
            return

        status = await self._get_welcome_status(interaction.guild)
        status ^= True  # Flip boolean with xor
        log.debug(f"Welcome Status: {status}")
        await self._set_welcome_status(interaction.guild, status)
        result = "**enabled**" if status else "**disabled**"
        await interaction.response.send_message(
            embed=discord.Embed(
                title="Success",
                description=f"Welcome message has been {result}.",
                color=discord.Color.green(),
            ),
            ephemeral=True,
        )

    @_rsc_welcome.command(name="channel", description="Modify the welcome channel")  # type: ignore[type-var]
    @app_commands.describe(channel="Channel to send welcome message in. (Must be text channel)")
    async def _rsc_welcome_channel(self, interaction: discord.Interaction, channel: discord.TextChannel):
        if not interaction.guild:
            return

        await self._set_welcome_channel(interaction.guild, channel)
        await interaction.response.send_message(
            embed=SuccessEmbed(description=f"Welcome channel has been set to {channel.mention}"),
            ephemeral=True,
        )

    @_rsc_welcome.command(  # type: ignore[type-var]
        name="message",
        description="Modify the welcome message when a user joins the server (Max 512 characters)",
    )
    @app_commands.describe(msg="Welcome message string to send (Accepts `{member.mention}`)")
    async def _rsc_welcome_msg(self, interaction: discord.Interaction, msg: app_commands.Range[str, 1, 512]):
        if not interaction.guild:
            return

        await self._set_welcome_msg(interaction.guild, msg)

        embed = SuccessEmbed(title="Welcome Message Configured", description=msg)
        await interaction.response.send_message(embed=embed, ephemeral=True)

    @_rsc_welcome.command(  # type: ignore[type-var]
        name="roles",
        description="Modify the roles a user receives when joining the server",
    )
    async def _rsc_welcome_roles(
        self,
        interaction: discord.Interaction,
        role1: discord.Role,
        role2: discord.Role | None = None,
        role3: discord.Role | None = None,
        role4: discord.Role | None = None,
    ):
        if not interaction.guild:
            return

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

    async def _get_welcome_channel(self, guild: discord.Guild) -> discord.TextChannel | None:
        cid = await self.config.custom("Welcome", str(guild.id)).WelcomeChannel()
        channel = guild.get_channel(cid)
        if not channel or not isinstance(channel, discord.TextChannel):
            return None
        return channel

    async def _set_welcome_channel(self, guild: discord.Guild, channel: discord.TextChannel):
        await self.config.custom("Welcome", str(guild.id)).WelcomeChannel.set(channel.id)

    async def _get_welcome_roles(self, guild: discord.Guild) -> list[discord.Role]:
        roles = []
        notFound = False
        r_ids = await self.config.custom("Welcome", str(guild.id)).WelcomeRoles()
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

    async def _set_welcome_roles(self, guild: discord.Guild, roles: list[discord.Role]):
        await self.config.custom("Welcome", str(guild.id)).WelcomeRoles.set([x.id for x in roles])

    async def _get_welcome_msg(self, guild: discord.Guild) -> str | None:
        return await self.config.custom("Welcome", str(guild.id)).WelcomeMsg()

    async def _set_welcome_msg(self, guild: discord.Guild, msg: str):
        await self.config.custom("Welcome", str(guild.id)).WelcomeMsg.set(msg)

    async def _get_welcome_status(self, guild: discord.Guild) -> bool:
        return await self.config.custom("Welcome", str(guild.id)).WelcomeStatus()

    async def _set_welcome_status(self, guild: discord.Guild, status: bool):
        await self.config.custom("Welcome", str(guild.id)).WelcomeStatus.set(status)
