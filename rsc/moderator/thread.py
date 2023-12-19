import discord
import logging
import tempfile

from pydantic import parse_obj_as
from os import PathLike
from redbot.core import app_commands, checks
from urllib.parse import urljoin

from rscapi import ApiClient, FranchisesApi, TeamsApi
from rscapi.exceptions import ApiException
from rscapi.models.franchise import Franchise
from rscapi.models.franchise_gm import FranchiseGM
from rscapi.models.franchise_list import FranchiseList
from rscapi.models.rebrand_a_franchise import RebrandAFranchise
from rscapi.models.franchise_logo import FranchiseLogo
from rscapi.models.transfer_franchise import TransferFranchise
from rscapi.models.league import League
from rscapi.models.team_list import TeamList

from rsc.abc import RSCMixIn
from rsc.const import FREE_AGENT_ROLE, GM_ROLE
from rsc.embeds import ErrorEmbed, SuccessEmbed, BlueEmbed, ApiExceptionErrorEmbed
from rsc.exceptions import RscException
from rsc.enums import Status
from rsc.types import ThreadGroup
from rsc.utils import utils

from typing import List, Dict, Optional

log = logging.getLogger("red.rsc.moderator")

defaults_guild = {
    "PrimaryCategory": None,
    "ManagementRole": None,
    "Groups": {},
}


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

    @_thread.command(
        name="settings", description="Current configuration for ModMail thread handling"
    )
    async def _thread_settings(self, interaction: discord.Interaction):
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

    @_thread_groups.command(
        name="list", description="List of current configured ModMail groups"
    )
    async def _thread_groups_list(self, interaction: discord.Interaction):
        groups = await self._get_groups(interaction.guild)

        name_fmt = "\n".join(groups.keys())
        role_fmt: list[str] = []
        category_fmt: list[str] = []
        for g in groups.values():
            r = interaction.guild.get_role(g["role"])
            c = interaction.guild.get_channel(g["category"])
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

    @_thread_groups.command(
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
        await self._set_group(
            interaction.guild, name=name, category=category, role=role
        )

        embed = SuccessEmbed(
            title="ModMail Group Added",
            description=f"Created new assignable modmail group.",
        )
        embed.add_field(name="Name", value=name, inline=True)
        embed.add_field(name="Role", value=role.mention, inline=True)
        embed.add_field(name="Category", value=category.mention, inline=True)

        await interaction.response.send_message(embed=embed, ephemeral=True)

    @_thread_groups.command(
        name="rm", description="Delete an assignable group for modmail threads"
    )
    @app_commands.describe(group="Assignable ModMail group name")
    @app_commands.autocomplete(group=thread_autocomplete)
    async def _thread_groups_rm(self, interaction: discord.Interaction, group: str):
        groups = await self._get_groups(interaction.guild)
        if group not in groups.keys():
            await interaction.response.send_message(embed=ErrorEmbed(description=f"**{group}** is not a valid assignable ModMail group."), ephemeral=True)
            return
        await self._unset_group(interaction.guild, group)

        embed = SuccessEmbed(
            title="ModMail Group Removed",
            description=f"Removed **{group}** from assignable modmail groups.",
        )
        await interaction.response.send_message(embed=embed, ephemeral=True)

    @_thread.command(
        name="category", description="Primary category for incoming modmails"
    )
    @app_commands.describe(category="Primary ModMail category")
    async def _thread_category(
        self, interaction: discord.Interaction, category: discord.CategoryChannel
    ):
        await self._set_primary_category(interaction.guild, category)
        await interaction.response.send_message(
            embed=SuccessEmbed(
                description=f"ModMail primary category has been set to **{category.jump_url}**"
            ),
            ephemeral=True,
        )

    @_thread.command(name="role", description="Management role for ModMail threads")
    @app_commands.describe(role="Management role for assigning ModMail threads")
    async def _thread_category(
        self, interaction: discord.Interaction, role: discord.Role
    ):
        await self._set_management_role(interaction.guild, role)
        await interaction.response.send_message(
            embed=SuccessEmbed(
                description=f"Mangement role for ModMail threads has been set to {role.mention}"
            ),
            ephemeral=True,
        )

    # Non-Group Commands

    @app_commands.command(
        name="assign", description="Assign the current modmail to a specific group"
    )
    @app_commands.describe(group="Assignable ModMail group name")
    @app_commands.autocomplete(group=thread_autocomplete)
    @app_commands.guild_only
    async def _thread_assign(self, interaction: discord.Interaction, group: str):
        # Validate group exists
        tgroup = await self.get_thread_group(interaction.guild, group)
        if not tgroup:
            await interaction.response.send_message(
                f"**{group}** is not an assignable modmail group.",
                ephemeral=True
            )
            return

        category = interaction.guild.get_channel(tgroup["category"])
        if not category:
            await interaction.response.send_message(
                f"Category does not exist: **{tgroup['category']}**",
                ephemeral=True
            )
            return

        role = interaction.guild.get_role(tgroup["role"])
        role_fmt = role.mention if role else tgroup["role"]

        await interaction.channel.move(
            end=True, category=category, sync_permissions=True
        )
        await interaction.channel.send(f"This ticket has been assigned to {role_fmt}", allowed_mentions=discord.AllowedMentions(roles=True))
        await interaction.response.send_message(embed=SuccessEmbed(description=f"Moved modmail thread to {category.jump_url}"), ephemeral=True)

    @app_commands.command(
        name="unassign", description="Move thread back to the primary ModMail category"
    )
    @app_commands.guild_only
    async def _thread_unassign(self, interaction: discord.Interaction):
        if not await self.is_modmail_thread(interaction.channel):
            await interaction.response.send_message("Only allowed in a modmail thread.", ephemeral=True)
            return

        category = await self._get_primary_category(interaction.guild)
        if not category:
            await interaction.response.send_message("Primary modmail category is not configured or does not exist anymore.", ephemeral=True)
            return

        role = await self._get_management_role(interaction.guild)
        if not category:
            await interaction.response.send_message("ModMail management role is not configured or does not exist anymore.", ephemeral=True)
            return

        await interaction.channel.move(end=True, category=category, sync_permissions=True)
        await interaction.channel.send(f"This ticket has been given back to {role.mention}", allowed_mentions=discord.AllowedMentions(roles=True))
        await interaction.response.send_message(embed=SuccessEmbed(description=f"Moved modmail thread to {category.jump_url}"), ephemeral=True)


    @app_commands.command(
        name="resolve", description="Send resolved message to a modmail thread"
    )
    @app_commands.guild_only
    async def _thread_resolve(self, interaction: discord.Interaction):
        if not interaction.channel or isinstance(
            interaction.channel, (discord.DMChannel, discord.GroupChannel)
        ):
            await interaction.response.send_message(
                "Must be used in a modmail thread.", ephemeral=True
            )
            return
        if not interaction.channel.category:
            await interaction.response.send_message(
                "Must be used in a modmail thread.", ephemeral=True
            )
            return

        category = interaction.channel.category
        groups = await self._get_groups(interaction.guild)
        for g in groups.values():
            if category.id == g["category"]:
                await interaction.response.send_message("```\nresolved\n```")
                return
        await interaction.response.send_message(
            "Must be used in a modmail thread.", ephemeral=True
        )

    @app_commands.command(name="feet", description="Moar feet pics!!!")
    @app_commands.checks.has_permissions(manage_guild=True)
    async def _this_is_a_secret(self, interaction: discord.Interaction):
        """This is a secret. Nobody say anything... :shh:"""
        await interaction.response.send_message(
            "@everyone send <@249326300148269058> some feet pics!",
            allowed_mentions=discord.AllowedMentions.none(),
        )

    # Helpers

    async def get_thread_group(
        self, guild: discord.Guild, group: str
    ) -> Optional[ThreadGroup]:
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
        await self.config.custom("Thread", guild.id).Groups.set(groups)

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
        await self.config.custom("Thread", guild.id).Groups.set(groups)

    async def _get_primary_category(
        self, guild: discord.Guild
    ) -> Optional[discord.CategoryChannel]:
        return discord.utils.get(
            guild.categories,
            id=await self.config.custom("Thread", guild.id).PrimaryCategory(),
        )

    async def _get_management_role(
        self, guild: discord.Guild
    ) -> discord.Role | None:
        return guild.get_role(
            await self.config.custom("Thread", guild.id).ManagementRole()
        )

    async def _set_primary_category(
        self, guild: discord.Guild, category: discord.CategoryChannel
    ):
        await self.config.custom("Thread", guild.id).PrimaryCategory.set(category.id)

    async def _set_management_role(self, guild: discord.Guild, role: discord.Role):
        await self.config.custom("Thread", guild.id).ManagementRole.set(role.id)

    async def _get_groups(self, guild: discord.Guild) -> dict[str, ThreadGroup]:
        return await self.config.custom("Thread", guild.id).Groups()


# endregion jsondb
