import logging

import discord
from redbot.core import app_commands

from rsc.abc import RSCMixIn
from rsc.embeds import BlueEmbed, ErrorEmbed, SuccessEmbed
from rsc.types import ModThreadSettings, ThreadGroup

log = logging.getLogger("red.rsc.moderator")


defaults_guild = ModThreadSettings(PrimaryCategory=None, ManagementRole=None, Groups={})


class ThreadMixIn(RSCMixIn):
    def __init__(self):
        log.debug("Initializing ThreadMixIn")

        # Prepare configuration group
        self.config.init_custom("Thread", 1)
        self.config.register_custom("Thread", **defaults_guild)
        super().__init__()

    # Autocomplete

    async def thread_autocomplete(
        self, interaction: discord.Interaction, current: str
    ) -> list[app_commands.Choice[str]]:
        if not interaction.guild:
            return []

        group_list = await self._get_groups(interaction.guild)
        groups = list(group_list.keys())

        log.debug(f"Autocomplete Groups: {groups}")
        # Return nothing if no groups exist
        if not groups:
            return []

        if not current:
            return [app_commands.Choice(name=f, value=f) for f in groups[:25]]

        choices = []
        for g in groups:
            if current.lower() in g.lower():
                choices.append(app_commands.Choice(name=g, value=g))
            if len(choices) == 25:
                return choices
        return choices

    # Top Level Group

    _thread = app_commands.Group(
        name="thread",
        description="View and configure mod thread settings",
        guild_only=True,
        default_permissions=discord.Permissions(manage_guild=True),
    )
    _thread_groups = app_commands.Group(
        name="groups",
        description="Display list of configured ModMail groups",
        guild_only=True,
        parent=_thread,
    )

    # Thread Group Commands

    @_thread.command(  # type: ignore
        name="settings", description="Current configuration for ModMail thread handling"
    )
    async def _thread_settings(self, interaction: discord.Interaction):
        if not interaction.guild:
            return

        category = await self._get_primary_category(interaction.guild)
        role = await self._get_management_role(interaction.guild)

        embed = BlueEmbed(
            title="ModThread Settings",
            description="Current configuration for ModMail thread handling.",
        )

        embed.add_field(
            name="Primary Category",
            value=category.mention if category else "None",
            inline=False,
        )
        embed.add_field(
            name="Management Role", value=role.mention if role else "None", inline=False
        )
        await interaction.response.send_message(embed=embed, ephemeral=True)

    @_thread_groups.command(  # type: ignore
        name="list", description="List of current configured ModMail groups"
    )
    async def _thread_groups_list(self, interaction: discord.Interaction):
        guild = interaction.guild
        if not guild:
            return
        groups = await self._get_groups(guild)

        name_fmt = "\n".join(groups.keys())
        role_fmt: list[str] = []
        category_fmt: list[str] = []
        for g in groups.values():
            r = guild.get_role(g["role"])
            c = guild.get_channel(g["category"])
            role_fmt.append(r.mention if r else str(g["role"]))
            category_fmt.append(c.mention if c else str(g["category"]))

        embed = BlueEmbed(
            title="ModMail Thread Groups",
            description="Groups designed for assignable tickets.",
        )
        embed.add_field(name="Name", value=name_fmt, inline=True)
        embed.add_field(name="Role", value="\n".join(role_fmt), inline=True)
        embed.add_field(name="Category", value="\n".join(category_fmt), inline=True)

        await interaction.response.send_message(embed=embed, ephemeral=True)

    @_thread_groups.command(  # type: ignore
        name="add", description="Add an assignable group for modmail threads"
    )
    @app_commands.describe(
        name="Assignable ModMail group name",
        category="ModMail group discord category",
        role="ModMail group discord role",
    )
    async def _thread_groups_add(
        self,
        interaction: discord.Interaction,
        name: str,
        category: discord.CategoryChannel,
        role: discord.Role,
    ):
        if not interaction.guild:
            return
        await self._set_group(
            interaction.guild, name=name, category=category, role=role
        )

        embed = SuccessEmbed(
            title="ModMail Group Added",
            description="Created new assignable modmail group.",
        )
        embed.add_field(name="Name", value=name, inline=True)
        embed.add_field(name="Role", value=role.mention, inline=True)
        embed.add_field(name="Category", value=category.mention, inline=True)

        await interaction.response.send_message(embed=embed, ephemeral=True)

    @_thread_groups.command(  # type: ignore
        name="rm", description="Delete an assignable group for modmail threads"
    )
    @app_commands.describe(group="Assignable ModMail group name")
    @app_commands.autocomplete(group=thread_autocomplete)  # type: ignore
    async def _thread_groups_rm(self, interaction: discord.Interaction, group: str):
        if not interaction.guild:
            return
        groups = await self._get_groups(interaction.guild)
        if group not in groups.keys():
            await interaction.response.send_message(
                embed=ErrorEmbed(
                    description=f"**{group}** is not a valid assignable ModMail group."
                ),
                ephemeral=True,
            )
            return
        await self._unset_group(interaction.guild, group)

        embed = SuccessEmbed(
            title="ModMail Group Removed",
            description=f"Removed **{group}** from assignable modmail groups.",
        )
        await interaction.response.send_message(embed=embed, ephemeral=True)

    @_thread.command(  # type: ignore
        name="category", description="Primary category for incoming modmails"
    )
    @app_commands.describe(category="Primary ModMail category")
    async def _thread_category(
        self, interaction: discord.Interaction, category: discord.CategoryChannel
    ):
        if not interaction.guild:
            return
        await self._set_primary_category(interaction.guild, category)
        await interaction.response.send_message(
            embed=SuccessEmbed(
                description=f"ModMail primary category has been set to **{category.jump_url}**"
            ),
            ephemeral=True,
        )

    @_thread.command(name="role", description="Management role for ModMail threads")  # type: ignore
    @app_commands.describe(role="Management role for assigning ModMail threads")
    async def _thread_management_role(
        self, interaction: discord.Interaction, role: discord.Role
    ):
        if not interaction.guild:
            return
        await self._set_management_role(interaction.guild, role)
        await interaction.response.send_message(
            embed=SuccessEmbed(
                description=f"Mangement role for ModMail threads has been set to {role.mention}"
            ),
            ephemeral=True,
        )

    # Non-Group Commands

    @app_commands.command(  # type: ignore
        name="assign", description="Assign the current modmail to a specific group"
    )
    @app_commands.describe(group="Assignable ModMail group name")
    @app_commands.autocomplete(group=thread_autocomplete)  # type: ignore
    @app_commands.guild_only
    async def _thread_assign(self, interaction: discord.Interaction, group: str):
        channel = interaction.channel
        guild = interaction.guild
        if not (guild and channel):
            return

        if not isinstance(channel, discord.TextChannel):
            return

        # Validate group exists
        tgroup = await self.get_thread_group(guild, group)
        if not tgroup:
            await interaction.response.send_message(
                f"**{group}** is not an assignable modmail group.", ephemeral=True
            )
            return

        category = guild.get_channel(tgroup["category"])
        if not category:
            await interaction.response.send_message(
                f"Category does not exist: **{tgroup['category']}**", ephemeral=True
            )
            return

        role = guild.get_role(tgroup["role"])
        role_fmt = role.mention if role else tgroup["role"]

        await channel.move(end=True, category=category, sync_permissions=True)
        await channel.send(
            f"This ticket has been assigned to {role_fmt}",
            allowed_mentions=discord.AllowedMentions(roles=True),
        )
        await interaction.response.send_message(
            embed=SuccessEmbed(
                description=f"Moved modmail thread to {category.jump_url}"
            ),
            ephemeral=True,
        )

    @app_commands.command(  # type: ignore
        name="unassign", description="Move thread back to the primary ModMail category"
    )
    @app_commands.guild_only
    async def _thread_unassign(self, interaction: discord.Interaction):
        channel = interaction.channel
        guild = interaction.guild
        if not (guild and channel):
            return

        if not isinstance(channel, discord.TextChannel):
            return

        if not await self.is_modmail_thread(channel):
            await interaction.response.send_message(
                "Only allowed in a modmail thread.", ephemeral=True
            )
            return

        category = await self._get_primary_category(guild)
        if not category:
            await interaction.response.send_message(
                "Primary modmail category is not configured or does not exist anymore.",
                ephemeral=True,
            )
            return

        role = await self._get_management_role(guild)
        if not role:
            await interaction.response.send_message(
                "ModMail management role is not configured or does not exist anymore.",
                ephemeral=True,
            )
            return

        await channel.move(end=True, category=category, sync_permissions=True)
        await channel.send(
            f"This ticket has been given back to {role.mention}",
            allowed_mentions=discord.AllowedMentions(roles=True),
        )
        await interaction.response.send_message(
            embed=SuccessEmbed(
                description=f"Moved modmail thread to {category.jump_url}"
            ),
            ephemeral=True,
        )

    @app_commands.command(  # type: ignore
        name="resolve", description="Send resolved message to a modmail thread"
    )
    @app_commands.guild_only
    async def _thread_resolve(self, interaction: discord.Interaction):
        guild = interaction.guild
        channel = interaction.channel
        if not (guild and channel):
            return
        if isinstance(channel, (discord.DMChannel, discord.GroupChannel)):
            await interaction.response.send_message(
                "Must be used in a modmail thread.", ephemeral=True
            )
            return
        if not channel.category:
            await interaction.response.send_message(
                "Must be used in a modmail thread.", ephemeral=True
            )
            return

        category = channel.category
        groups = await self._get_groups(guild)
        for g in groups.values():
            if category.id == g["category"]:
                await interaction.response.send_message("```\nresolved\n```")
                return
        await interaction.response.send_message(
            "Must be used in a modmail thread.", ephemeral=True
        )

    @app_commands.command(name="feet", description="Moar feet pics!!!")  # type: ignore
    @app_commands.checks.has_permissions(manage_guild=True)
    async def _this_is_a_secret(self, interaction: discord.Interaction):
        """This is a secret. Nobody say anything... :shh:"""
        await interaction.response.send_message(
            "@everyone send <@!249326300148269058> some feet pics!",
            allowed_mentions=discord.AllowedMentions.none(),
        )

    # Helpers

    async def get_thread_group(
        self, guild: discord.Guild, group: str
    ) -> ThreadGroup | None:
        groups = await self._get_groups(guild)
        for k, v in groups.items():
            if k == group:
                log.debug(f"Found thread group: {k}")
                return v
        return None

    async def is_modmail_thread(self, channel: discord.TextChannel) -> bool:
        if not channel.category_id:
            return False

        groups = await self._get_groups(channel.guild)
        for v in groups.values():
            if v["category"] == channel.category_id:
                log.debug(f"Valid modmail thread: {channel}")
                return True
        return False

    # region jsondb
    async def _unset_group(
        self,
        guild: discord.Guild,
        group_name: str,
    ):
        groups = await self._get_groups(guild)
        groups.pop(group_name)
        await self.config.custom("Thread", str(guild.id)).Groups.set(groups)

    async def _set_group(
        self,
        guild: discord.Guild,
        name: str,
        category: discord.CategoryChannel,
        role: discord.Role,
    ):
        groups = await self._get_groups(guild)
        group = ThreadGroup(category=category.id, role=role.id)
        groups[name] = group
        await self.config.custom("Thread", str(guild.id)).Groups.set(groups)

    async def _get_primary_category(
        self, guild: discord.Guild
    ) -> discord.CategoryChannel | None:
        return discord.utils.get(
            guild.categories,
            id=await self.config.custom("Thread", str(guild.id)).PrimaryCategory(),
        )

    async def _get_management_role(self, guild: discord.Guild) -> discord.Role | None:
        return guild.get_role(
            await self.config.custom("Thread", str(guild.id)).ManagementRole()
        )

    async def _set_primary_category(
        self, guild: discord.Guild, category: discord.CategoryChannel
    ):
        await self.config.custom("Thread", str(guild.id)).PrimaryCategory.set(
            category.id
        )

    async def _set_management_role(self, guild: discord.Guild, role: discord.Role):
        await self.config.custom("Thread", str(guild.id)).ManagementRole.set(role.id)

    async def _get_groups(self, guild: discord.Guild) -> dict[str, ThreadGroup]:
        return await self.config.custom("Thread", str(guild.id)).Groups()


# endregion jsondb
