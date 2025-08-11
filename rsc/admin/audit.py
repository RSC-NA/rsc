import logging
from enum import Enum, EnumMeta
from itertools import islice

import discord
from redbot.core import app_commands

from rsc.admin import AdminMixIn
from rsc.embeds import ErrorEmbed
from rsc.logs import GuildLogAdapter
from rsc.transformers import DateTransformer

logger = logging.getLogger("red.rsc.admin.audit")
log = GuildLogAdapter(logger)


class IndexableEnumMeta(EnumMeta):
    def __getitem__(cls, index: int | str):
        if isinstance(index, slice):
            return [cls._member_map_[i] for i in islice(cls._member_map_, index.start, index.stop, index.step)]
        if isinstance(index, int):
            return cls._member_map_[next(islice(cls._member_map_, index, index + 1))]
        return cls._member_map_[index]


class RSCAuditLogAction(Enum, metaclass=IndexableEnumMeta):
    # fmt: off
    guild_update                                      = 1
    channel_create                                    = 10
    channel_update                                    = 11
    channel_delete                                    = 12
    overwrite_create                                  = 13
    overwrite_update                                  = 14
    overwrite_delete                                  = 15
    kick                                              = 20
    member_prune                                      = 21
    ban                                               = 22
    unban                                             = 23
    member_update                                     = 24
    member_role_update                                = 25
    member_move                                       = 26
    member_disconnect                                 = 27
    bot_add                                           = 28
    role_create                                       = 30
    role_update                                       = 31
    role_delete                                       = 32
    invite_create                                     = 40
    invite_update                                     = 41
    invite_delete                                     = 42
    webhook_create                                    = 50
    webhook_update                                    = 51
    webhook_delete                                    = 52
    emoji_create                                      = 60
    emoji_update                                      = 61
    emoji_delete                                      = 62
    message_delete                                    = 72
    message_bulk_delete                               = 73
    message_pin                                       = 74
    message_unpin                                     = 75
    integration_create                                = 80
    integration_update                                = 81
    integration_delete                                = 82
    stage_instance_create                             = 83
    stage_instance_update                             = 84
    stage_instance_delete                             = 85
    sticker_create                                    = 90
    sticker_update                                    = 91
    sticker_delete                                    = 92
    scheduled_event_create                            = 100
    scheduled_event_update                            = 101
    scheduled_event_delete                            = 102
    thread_create                                     = 110
    thread_update                                     = 111
    thread_delete                                     = 112
    app_command_permission_update                     = 121
    soundboard_sound_create                           = 130
    soundboard_sound_update                           = 131
    soundboard_sound_delete                           = 132
    automod_rule_create                               = 140
    automod_rule_update                               = 141
    automod_rule_delete                               = 142
    automod_block_message                             = 143
    automod_flag_message                              = 144
    automod_timeout_member                            = 145
    automod_quarantine_user                           = 146
    creator_monetization_request_created              = 150
    creator_monetization_terms_accepted               = 151


# def __iter__(cls):
#     return iter(list(RSCAuditLogAction))


class AdminAuditMixIn(AdminMixIn):
    def __init__(self):
        log.debug("Initializing AdminMixIn:Audit")

        super().__init__()

    _stats = app_commands.Group(
        name="audit",
        description="RSC Audit Log Data",
        parent=AdminMixIn._admin,
        guild_only=True,
        default_permissions=discord.Permissions(manage_guild=True),
    )

    async def audit_action_autocomplete(self, interaction: discord.Interaction, current: str) -> list[app_commands.Choice[str]]:
        if not current:
            return [app_commands.Choice(name=action.name, value=action.value) for action in RSCAuditLogAction[:25]]

        return [
            app_commands.Choice(name=action.name, value=action.value)
            for action in RSCAuditLogAction
            if current.lower() in action.name.lower()
        ]

    @_stats.command(name="search", description="Search server audit log for an action")  # type: ignore[type-var]
    @app_commands.autocomplete(action=audit_action_autocomplete)  # type: ignore[type-var]
    async def _admin_audit_search_cmd(
        self,
        interaction: discord.Interaction,
        action: int | None = None,
        before: DateTransformer | None = None,
        after: DateTransformer | None = None,
        user: discord.Member | None = None,
        limit: int = 20,
    ):
        guild = interaction.guild
        if not guild:
            return

        if action:
            try:
                action = discord.AuditLogAction(int(action))
            except ValueError:
                return await interaction.response.send_message(
                    embed=ErrorEmbed(title="Invalid Action", description="The specified action is not valid."), ephemeral=True
                )

        if user:
            async for entry in guild.audit_logs(action=action, limit=limit, before=before, after=after, user=user):
                log.debug(f"Entry: {entry}")
        else:
            async for entry in guild.audit_logs(action=action, limit=limit, before=before, after=after):
                log.debug(f"Entry: {entry}")
