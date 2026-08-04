import discord
from redbot.core import app_commands

from rsc.abc import RSCMixIn


class RSCSettingsMixIn(RSCMixIn):
    """Holder for the top level `/rsc` command group.

    The group lives here rather than on `RSC` in `rsc.core` so that feature
    mixins can nest sub groups under it via `parent=RSCSettingsMixIn.rsc_settings`
    without importing `rsc.core` (which imports every mixin, so that would be
    circular). Same arrangement as `AdminMixIn._admin` and `AdminSyncMixIn._sync`.

    The command bodies still live on `RSC` in `rsc.core`. `CogMeta` walks the
    full MRO, so children declared on a subclass still attach to a group declared
    on a base.
    """

    rsc_settings: app_commands.Group = app_commands.Group(
        name="rsc",
        description="RSC API Configuration",
        guild_only=True,
        default_permissions=discord.Permissions(manage_guild=True),
    )
