import io
import logging
import re
from pathlib import Path
from typing import Optional

import discord
from discord.app_commands import Transform
from PIL import Image
from redbot.core import app_commands
from rscapi.models.league_player import LeaguePlayer

from rsc import const
from rsc.abc import RSCMixIn
from rsc.embeds import (
    ErrorEmbed,
    ExceptionErrorEmbed,
    NotImplementedEmbed,
    OrangeEmbed,
    SuccessEmbed,
)
from rsc.enums import BulkRoleAction, TransactionType
from rsc.transformers import GreedyMemberTransformer
from rsc.types import Accolades
from rsc.utils import filters
from rsc.utils.pagify import Pagify
from rsc.utils.views import BulkRoleConfirmView

log = logging.getLogger("red.rsc.utils")

FRANCHISE_ROLE_REGEX = re.compile(r"^\w[\w\s\x27]+?\s\(.+?\)$")
EMOJI_REGEX = re.compile(
    "["
    "\U0001f600-\U0001f64f"  # emoticons
    "\U0001f300-\U0001f5ff"  # symbols & pictographs
    "\U0001f680-\U0001f6ff"  # transport & map symbols
    "\U0001f1e0-\U0001f1ff"  # flags (iOS)
    "\U00002500-\U00002bef"  # chinese char
    "\U00002702-\U000027b0"
    "\U000024c2-\U0001f251"
    "\U0001f926-\U0001f937"
    "\U00010000-\U0010ffff"
    "\u2640-\u2642"
    "\u2600-\u2b55"
    "\u200d"
    "\u23cf"
    "\u23e9"
    "\u231a"
    "\ufe0f"  # dingbats
    "\u3030"
    "]+",
    re.UNICODE,
)


async def valid_emoji_name(name: str) -> bool:
    if not re.match(r"[0-9A-Za-z_]+", name):
        return False
    return True


async def resize_image(img_data: bytes, height: int, width: int, imgtype: str):
    img = Image.open(io.BytesIO(img_data))
    img.resize((height, width))

    log.debug(f"Image Mode: {img.mode}")
    if img.mode == "RGBA" and imgtype == "JPEG":
        log.debug("Converting RGBA to RGB for JPEG.")
        img = img.convert("RGB")

    with io.BytesIO() as buf:
        img.save(buf, format=imgtype)
        return buf.getvalue()


async def img_to_thumbnail(img_data: bytes, height: int, width: int, imgtype: str):
    img = Image.open(io.BytesIO(img_data))
    img.thumbnail(size=(128, 128))
    with io.BytesIO() as buf:
        img.save(buf, format=imgtype)
        return buf.getvalue()


def escape(text: str, *, mass_mentions: bool = False, formatting: bool = False) -> str:
    """Get text with all mass mentions or markdown escaped.

    Parameters
    ----------
    text : str
        The text to be escaped.
    mass_mentions : `bool`, optional
        Set to :code:`True` to escape mass mentions in the text.
    formatting : `bool`, optional
        Set to :code:`True` to escape any markdown formatting in the text.

    Returns
    -------
    str
        The escaped text.

    """
    if mass_mentions:
        text = text.replace("@everyone", "@\u200beveryone")
        text = text.replace("@here", "@\u200bhere")
    if formatting:
        text = discord.utils.escape_markdown(text)
    return text


async def get_audit_log_reason(
    guild: discord.Guild,
    target: discord.abc.GuildChannel | discord.Member | discord.Role | int,
    action: discord.AuditLogAction,
) -> tuple[discord.abc.User | None, str | None]:
    """Retrieve audit log reason for `discord.AuditLogAction`"""
    perp = None
    reason = None
    if not isinstance(target, int):
        target_id = target.id
    else:
        target_id = target
    if guild.me.guild_permissions.view_audit_log:
        async for log in guild.audit_logs(limit=5, action=action):
            if not log.target:
                continue
            if log.target.id == target_id:
                perp = log.user
                if log.reason:
                    reason = log.reason
                break
    return perp, reason


async def not_implemented(interaction: discord.Interaction, followup=False):
    if followup:
        await interaction.followup.send(embed=NotImplementedEmbed(), ephemeral=True)
    else:
        await interaction.response.send_message(
            embed=NotImplementedEmbed(), ephemeral=True
        )


async def get_draft_eligible_role(guild: discord.Guild) -> discord.Role:
    r = discord.utils.get(guild.roles, name=const.DRAFT_ELIGIBLE)
    if not r:
        log.error(
            f"[{guild.name}] Expected role does not exist: {const.DRAFT_ELIGIBLE}"
        )
        raise ValueError(
            f"[{guild.name}] Expected role does not exist: {const.DRAFT_ELIGIBLE}"
        )
    return r


async def get_ir_role(guild: discord.Guild) -> discord.Role:
    r = discord.utils.get(guild.roles, name=const.IR_ROLE)
    if not r:
        log.error(f"[{guild.name}] Expected role does not exist: {const.IR_ROLE}")
        raise ValueError(
            f"[{guild.name}] Expected role does not exist: {const.IR_ROLE}"
        )
    return r


async def get_muted_role(guild: discord.Guild) -> discord.Role:
    r = discord.utils.get(guild.roles, name=const.MUTED_ROLE)
    if not r:
        log.error(f"[{guild.name}] Expected role does not exist: {const.MUTED_ROLE}")
        raise ValueError(
            f"[{guild.name}] Expected role does not exist: {const.MUTED_ROLE}"
        )
    return r


async def get_captain_role(guild: discord.Guild) -> discord.Role:
    r = discord.utils.get(guild.roles, name=const.CAPTAIN_ROLE)
    if not r:
        log.error(f"[{guild.name}] Expected role does not exist: {const.CAPTAIN_ROLE}")
        raise ValueError(
            f"[{guild.name}] Expected role does not exist: {const.CAPTAIN_ROLE}"
        )
    return r


async def get_former_player_role(guild: discord.Guild) -> discord.Role:
    r = discord.utils.get(guild.roles, name=const.FORMER_PLAYER_ROLE)
    if not r:
        log.error(
            f"[{guild.name}] Expected role does not exist: {const.FORMER_PLAYER_ROLE}"
        )
        raise ValueError(
            f"[{guild.name}] Expected role does not exist: {const.FORMER_PLAYER_ROLE}"
        )
    return r


async def get_spectator_role(guild: discord.Guild) -> discord.Role:
    r = discord.utils.get(guild.roles, name=const.SPECTATOR_ROLE)
    if not r:
        log.error(
            f"[{guild.name}] Expected role does not exist: {const.SPECTATOR_ROLE}"
        )
        raise ValueError(
            f"[{guild.name}] Expected role does not exist: {const.SPECTATOR_ROLE}"
        )
    return r


async def get_league_role(guild: discord.Guild) -> discord.Role:
    r = discord.utils.get(guild.roles, name=const.LEAGUE_ROLE)
    if not r:
        log.error(f"[{guild.name}] Expected role does not exist: {const.LEAGUE_ROLE}")
        raise ValueError(
            f"[{guild.name}] Expected role does not exist: {const.LEAGUE_ROLE}"
        )
    return r


async def get_free_agent_role(guild: discord.Guild) -> discord.Role:
    r = discord.utils.get(guild.roles, name=const.FREE_AGENT_ROLE)
    if not r:
        log.error(
            f"[{guild.name}] Expected role does not exist: {const.FREE_AGENT_ROLE}"
        )
        raise ValueError(
            f"[{guild.name}] Expected role does not exist: {const.FREE_AGENT_ROLE}"
        )
    return r


async def get_permfa_role(guild: discord.Guild) -> discord.Role:
    r = discord.utils.get(guild.roles, name=const.PERM_FA_ROLE)
    if not r:
        log.error(f"[{guild.name}] Expected role does not exist: {const.PERM_FA_ROLE}")
        raise ValueError(
            f"[{guild.name}] Expected role does not exist: {const.PERM_FA_ROLE}"
        )
    return r


async def get_gm_role(guild: discord.Guild) -> discord.Role:
    r = discord.utils.get(guild.roles, name=const.GM_ROLE)
    if not r:
        log.error(f"[{guild.name}] Expected role does not exist: {const.GM_ROLE}")
        raise ValueError(
            f"[{guild.name}] Expected role does not exist: {const.GM_ROLE}"
        )
    return r


async def get_agm_role(guild: discord.Guild) -> discord.Role:
    r = discord.utils.get(guild.roles, name=const.AGM_ROLE)
    if not r:
        log.error(f"[{guild.name}] Expected role does not exist: {const.AGM_ROLE}")
        raise ValueError(
            f"[{guild.name}] Expected role does not exist: {const.AGM_ROLE}"
        )
    return r


async def get_subbed_out_role(guild: discord.Guild) -> discord.Role:
    r = discord.utils.get(guild.roles, name=const.SUBBED_OUT_ROLE)
    if not r:
        log.error(
            f"[{guild.name}] Expected role does not exist: {const.SUBBED_OUT_ROLE}"
        )
        raise ValueError(
            f"[{guild.name}] Expected role does not exist: {const.SUBBED_OUT_ROLE}"
        )
    return r


async def get_former_gm_role(guild: discord.Guild) -> discord.Role:
    r = discord.utils.get(guild.roles, name=const.FORMER_GM_ROLE)
    if not r:
        log.error(
            f"[{guild.name}] Expected role does not exist: {const.FORMER_GM_ROLE}"
        )
        raise ValueError(
            f"[{guild.name}] Expected role does not exist: {const.FORMER_GM_ROLE}"
        )
    return r


async def remove_prefix(member: discord.Member) -> str:
    """Remove team prefix from guild members display name"""
    result = member.display_name.split(" | ", maxsplit=1)
    if not result:
        raise ValueError(f"Unable to remove prefix from {member.display_name}")
    elif len(result) == 1:
        return result[0].strip()  # No prefix found
    else:
        return result[1].strip()


async def get_prefix(member: discord.Member) -> str | None:
    """Get team prefix from guild members display name"""
    result = member.display_name.split(" | ", maxsplit=1)
    if not result:
        raise ValueError(f"Error parsing prefix from {member.display_name}")
    elif len(result) == 1:
        return None  # No prefix found
    else:
        return result[0].strip()


async def give_fa_prefix(member: discord.Member):
    new_nick = f"FA | {await remove_prefix(member)}"
    await member.edit(nick=new_nick)


async def has_gm_role(member: discord.Member) -> bool:
    """Check if user has General Manager role in guild"""
    return any(role.name == const.GM_ROLE for role in member.roles)


async def member_from_rsc_name(
    guild: discord.Guild, name: str
) -> Optional[discord.Member]:
    """Get guild member by rsc name ("nickm"). Not recommended."""
    for m in guild.members:
        try:
            n = await remove_prefix(m)
            if n.startswith(name):
                return m
        except ValueError:
            """Handle former player or spectator"""
            if n.startswith(name):
                return m
            continue
    return None


async def get_gm_by_role(franchise_role: discord.Role) -> Optional[discord.Member]:
    """Get GM from guild franchise role"""
    for member in franchise_role.members:
        if has_gm_role(member):
            return member
    return None


async def role_by_name(guild: discord.Guild, name: str) -> discord.Role | None:
    """Get a guild discord role by name"""
    return discord.utils.get(guild.roles, name=name)


async def franchise_role_from_name(
    guild: discord.Guild, franchise_name: str
) -> discord.Role | None:
    """Get guild franchise role from franchise name (Ex: "The Garden")"""
    for role in guild.roles:
        if role.name.lower().startswith(franchise_name.lower()):
            return role
    return None


async def fa_img_from_tier(tier: str, tiny: bool = False) -> Optional[discord.File]:
    root = Path(__file__).parent.parent
    if tiny:
        img_path = root / f"resources/FA/64x64/{tier}FA_64x64.png"
    else:
        img_path = root / f"resources/FA/{tier}FA.png"

    if img_path.is_file():
        return discord.File(img_path)

    return None


async def fa_img_path_from_tier(tier: str, tiny: bool = False) -> Optional[Path]:
    root = Path(__file__).parent.parent
    if tiny:
        img_path = root / f"resources/FA/64x64/{tier}FA_64x64.png"
    else:
        img_path = root / f"resources/FA/{tier}FA.png"

    if img_path.is_file():
        return img_path

    return None


async def transaction_image_from_type(action: TransactionType) -> discord.File:
    root = Path(__file__).parent.parent
    match action:
        case TransactionType.CUT:
            return discord.File(root / "resources/transactions/Released.png")
        case TransactionType.PICKUP:
            return discord.File(root / "resources/transactions/Signed.png")
        case TransactionType.RESIGN:
            return discord.File(root / "resources/transactions/Resigned.png")
        case TransactionType.SUBSTITUTION:
            return discord.File(root / "resources/transactions/Subbed.png")
        case TransactionType.TEMP_FA:
            return discord.File(root / "resources/transactions/Subbed.png")
        case TransactionType.TRADE:
            return discord.File(root / "resources/transactions/Traded.png")
        case TransactionType.RETIRE:
            return discord.File(root / "resources/transactions/Retired.png")
        case TransactionType.INACTIVE_RESERVE:
            return discord.File(root / "resources/transactions/InactiveReserve.png")
        case TransactionType.IR_RETURN:
            return discord.File(root / "resources/transactions/InactiveReserve.png")
        case _:
            raise NotImplementedError


async def franchise_role_from_league_player(
    guild: discord.Guild, player: LeaguePlayer
) -> discord.Role:
    """Return a franchise discord.Role from `LeaguePlayer` object"""
    if not (player.team and player.team.franchise):
        raise AttributeError(
            f"{player.player.name} LeaguePlayer object has no team or franchise data."
        )

    rname = f"{player.team.franchise.name} ({player.team.franchise.gm.rsc_name})"
    r = discord.utils.get(guild.roles, name=rname)
    if not r:
        log.error(f"[{guild.name}] Expected franchise role does not exist: {rname}")
        raise ValueError(
            f"[{guild.name}] Expected franchise role does not exist: {rname}"
        )
    return r


async def tier_color_by_name(guild: discord.Guild, name: str) -> discord.Color:
    """Return tier color from role (Defaults to blue if not found)"""
    tier_role = discord.utils.get(guild.roles, name=name)
    if tier_role:
        return tier_role.color
    return discord.Color.blue()


async def is_guild_interaction(interaction: discord.Interaction) -> bool:
    """Check if interaction was sent from guild. Mostly for type issues since guild_only exists"""
    if interaction.guild:
        return True
    return False


async def get_tier_role(guild: discord.Guild, name: str) -> discord.Role:
    """Return discord.Role for a tier"""
    r = discord.utils.get(guild.roles, name=name)
    if not r:
        log.error(f"[{guild.name}] Expected tier role does not exist: {name}")
        raise ValueError(f"[{guild.name}] Expected tier role does not exist: {name}")
    return r


async def get_tier_fa_role(guild: discord.Guild, name: str) -> discord.Role:
    """Return FA discord.Role for a tier"""
    r = discord.utils.get(guild.roles, name=f"{name}FA")
    if not r:
        log.error(f"[{guild.name}] Expected tier FA role does not exist: {name}FA")
        raise ValueError(
            f"[{guild.name}] Expected tier FA role does not exist: {name}FA"
        )
    return r


async def franchise_role_from_disord_member(
    member: discord.Member,
) -> discord.Role | None:
    for r in member.roles:
        if FRANCHISE_ROLE_REGEX.match(r.name):
            return r
    return None


async def franchise_role_list_from_disord_member(
    member: discord.Member,
) -> list[discord.Role]:
    result = []
    for r in member.roles:
        if FRANCHISE_ROLE_REGEX.match(r.name):
            result.append(r)
    return result


async def emoji_from_prefix(
    guild: discord.Guild, prefix: str
) -> Optional[discord.Emoji]:
    return discord.utils.get(guild.emojis, name=prefix)


async def trophy_count(member: discord.Member) -> int:
    return member.display_name.count(const.TROPHY_EMOJI)


async def star_count(member: discord.Member) -> int:
    return member.display_name.count(const.STAR_EMOJI)


async def devleague_count(member: discord.Member) -> int:
    return member.display_name.count(const.DEV_LEAGUE_EMOJI)


async def format_discord_prefix(member: discord.Member, prefix: str) -> str:
    accolades = await member_accolades(member)
    no_pfx = await remove_prefix(member)
    name = await strip_discord_accolades(no_pfx)
    if prefix:
        new_nick = f"{prefix} | {name} {accolades}".strip()
    else:
        new_nick = f"{name} {accolades}".strip()
    return new_nick


async def strip_discord_accolades(value: str) -> str:
    final = value.replace(const.TROPHY_EMOJI, "")
    final = final.replace(const.STAR_EMOJI, "")
    final = final.replace(const.DEV_LEAGUE_EMOJI, "")
    return final.strip()


async def member_accolades(member: discord.Member) -> Accolades:
    return Accolades(
        trophy=await trophy_count(member),
        star=await star_count(member),
        devleague=await devleague_count(member),
    )


async def remove_emoji(member: discord.Member | str) -> str:
    if isinstance(member, discord.Member):
        m_str = member.display_name
    else:
        m_str = member
    return re.sub(EMOJI_REGEX, "", m_str)


async def fix_tracker_url(url: str) -> str:
    if "tracker.network/profile" in url:
        url = url.replace(
            "tracker.network/profile", "tracker.network/rocket-league/profile"
        )
        url = url.replace("profile/ps/", "profile/psn/")
        url = url.replace("profile/xbox/", "profile/xbl/")
    return url


async def async_iter_gather(result):
    """Gather async iterator into list and return"""
    final = []
    async for r in result:
        final.append(r)
    return final


class UtilsMixIn(RSCMixIn):
    def __init__(self):
        log.debug("Initializing UtilsMixIn")
        super().__init__()

    @app_commands.command(  # type: ignore
        name="getmassid",
        description="Mass lookup version of /getid.",
    )
    @app_commands.describe(
        members="Space delimited list of any string or ID that could identify a user."
    )
    @app_commands.guild_only
    async def _getmassid(
        self,
        interaction: discord.Interaction,
        members: Transform[list[discord.Member], GreedyMemberTransformer],
    ):
        """Get the discord ID of a user"""
        desc = "```\n"
        for m in members:
            desc += f"{m.display_name}:{m.name}:{m.id}\n"
        desc += "```"

        await interaction.response.send_message(content=desc, ephemeral=True)

    @app_commands.command(  # type: ignore
        name="getid",
        description="Lookup discord member account identifiers",
    )
    @app_commands.describe(member="RSC Discord Member")
    @app_commands.guild_only
    async def _getid(self, interaction: discord.Interaction, member: discord.Member):
        """Get the discord ID of a user"""
        await interaction.response.send_message(
            content=f"`{member.display_name}:{member.name}:{member.id}`",
            ephemeral=True,
        )

    @app_commands.command(  # type: ignore
        name="userinfo",
        description="Display discord user information for a user",
    )
    @app_commands.describe(member="RSC Discord Member (Optional)")
    @app_commands.guild_only
    async def _userinfo(
        self, interaction: discord.Interaction, member: discord.Member | None = None
    ):
        """Show information about a member.

        This includes fields for status, discord join date, server
        join date, voice state and previous usernames/global display names/nicknames.

        If the member has no roles, previous usernames, global display names, or server nicknames,
        these fields will be omitted.
        """
        guild = interaction.guild
        if not guild:
            return

        if not member:
            if not isinstance(interaction.user, discord.Member):
                return
            member = interaction.user

        roles = member.roles[-1:0:-1]

        joined_at = member.joined_at
        voice_state = member.voice
        member_number = (
            sorted(
                guild.members, key=lambda m: m.joined_at or interaction.created_at
            ).index(member)
            + 1
        )

        created_on = (
            f"{discord.utils.format_dt(member.created_at)}\n"
            f"{discord.utils.format_dt(member.created_at, 'R')}"
        )
        if joined_at is not None:
            joined_on = (
                f"{discord.utils.format_dt(joined_at)}\n"
                f"{discord.utils.format_dt(joined_at, 'R')}"
            )
        else:
            joined_on = "Unknown"

        if any(a.type is discord.ActivityType.streaming for a in member.activities):
            statusemoji = "\N{LARGE PURPLE CIRCLE}"
        elif member.status.name == "online":
            statusemoji = "\N{LARGE GREEN CIRCLE}"
        elif member.status.name == "offline":
            statusemoji = "\N{MEDIUM WHITE CIRCLE}\N{VARIATION SELECTOR-16}"
        elif member.status.name == "dnd":
            statusemoji = "\N{LARGE RED CIRCLE}"
        elif member.status.name == "idle":
            statusemoji = "\N{LARGE ORANGE CIRCLE}"
        activity = f"Chilling in {member.status} status"
        status_string = self.get_status_string(member)

        if roles:
            role_str = ", ".join([x.mention for x in roles])
            # 400 BAD REQUEST (error code: 50035): Invalid Form Body
            # In embed.fields.2.value: Must be 1024 or fewer in length.
            if len(role_str) > 1024:
                # Alternative string building time.
                # This is not the most optimal, but if you're hitting this, you are losing more time
                # to every single check running on users than the occasional user info invoke
                # We don't start by building this way, since the number of times we hit this should be
                # infinitesimally small compared to when we don't across all uses of Red.
                continuation_string = (
                    "and {numeric_number} more roles not displayed due to embed limits."
                )
                available_length = 1024 - len(
                    continuation_string
                )  # do not attempt to tweak, i18n

                role_chunks = []
                remaining_roles = 0

                for r in roles:
                    chunk = f"{r.mention}, "
                    chunk_size = len(chunk)

                    if chunk_size < available_length:
                        available_length -= chunk_size
                        role_chunks.append(chunk)
                    else:
                        remaining_roles += 1

                role_chunks.append(
                    continuation_string.format(numeric_number=remaining_roles)
                )

                role_str = "".join(role_chunks)

        else:
            role_str = None

        data = discord.Embed(
            description=status_string or activity, colour=member.colour
        )

        data.add_field(name="Joined Discord on", value=created_on)
        data.add_field(name="Joined this server on", value=joined_on)
        if role_str is not None:
            data.add_field(
                name="Roles" if len(roles) > 1 else "Role", value=role_str, inline=False
            )

        if voice_state and voice_state.channel:
            data.add_field(
                name="Current voice channel",
                value="{0.mention} ID: {0.id}".format(voice_state.channel),
                inline=False,
            )
        data.set_footer(
            text="Member #{} | User ID: {}".format(member_number, member.id)
        )

        name = str(member)
        name = " ~ ".join((name, member.nick)) if member.nick else name
        name = filters.filter_invites(name)

        avatar = member.display_avatar.replace(static_format="png")
        data.set_author(name=f"{statusemoji} {name}", url=avatar)
        data.set_thumbnail(url=avatar)

        await interaction.response.send_message(embed=data)

    @app_commands.command(  # type: ignore
        name="serverinfo",
        description="Display information about the discord server",
    )
    @app_commands.describe(details="Increase verbosity")
    @app_commands.guild_only
    async def _serverinfo(
        self, interaction: discord.Interaction, details: bool = False
    ):
        """
        Show server information.

        `details`: Shows more information when set to `True`.
        Default to False.
        """
        if not interaction.guild:
            return

        guild = interaction.guild
        created_at = "Created on {date_and_time}. That's {relative_time}!".format(
            date_and_time=discord.utils.format_dt(guild.created_at),
            relative_time=discord.utils.format_dt(guild.created_at, "R"),
        )
        online = str(
            len([m.status for m in guild.members if m.status != discord.Status.offline])
        )
        total_users = guild.member_count and str(guild.member_count)
        text_channels = str(len(guild.text_channels))
        voice_channels = str(len(guild.voice_channels))
        stage_channels = str(len(guild.stage_channels))
        if not details:
            data = OrangeEmbed(description=created_at)
            data.add_field(
                name="Users online",
                value=f"{online}/{total_users}" if total_users else "Not available",
            )
            data.add_field(name="Text Channels", value=text_channels)
            data.add_field(name="Voice Channels", value=voice_channels)
            data.add_field(name="Roles", value=str(len(guild.roles)))
            data.add_field(name="Owner", value=str(guild.owner))
            if interaction.command:
                data.set_footer(
                    text=f"Server ID: {str(guild.id)}"
                    + f"  •  Use /{interaction.command.name} details for more info on the server."
                )
            else:
                data.set_footer(text=f"Server ID: {str(guild.id)}")

            if guild.icon:
                data.set_author(name=guild.name, url=guild.icon)
                data.set_thumbnail(url=guild.icon)
            else:
                data.set_author(name=guild.name)
        else:

            def _size(num: float):
                for unit in ["B", "KB", "MB", "GB", "TB", "PB", "EB", "ZB"]:
                    if abs(num) < 1024.0:
                        return "{0:.1f}{1}".format(num, unit)
                    num /= 1024.0
                return "{0:.1f}{1}".format(num, "YB")

            def _bitsize(num: float):
                for unit in ["B", "KB", "MB", "GB", "TB", "PB", "EB", "ZB"]:
                    if abs(num) < 1000.0:
                        return "{0:.1f}{1}".format(num, unit)
                    num /= 1000.0
                return "{0:.1f}{1}".format(num, "YB")

            shard_info = (
                "\nShard ID: **{shard_id}/{shard_count}**".format(
                    shard_id=str(guild.shard_id + 1),
                    shard_count=str(self.bot.shard_count),
                )
                if self.bot.shard_count > 1
                else ""
            )
            # Logic from: https://github.com/TrustyJAID/Trusty-cogs/blob/master/serverstats/serverstats.py#L159
            online_stats = {
                "Humans: ": lambda x: not x.bot,
                " • Bots: ": lambda x: x.bot,
                "\N{LARGE GREEN CIRCLE}": lambda x: x.status is discord.Status.online,
                "\N{LARGE ORANGE CIRCLE}": lambda x: x.status is discord.Status.idle,
                "\N{LARGE RED CIRCLE}": lambda x: x.status
                is discord.Status.do_not_disturb,
                "\N{MEDIUM WHITE CIRCLE}\N{VARIATION SELECTOR-16}": lambda x: (
                    x.status is discord.Status.offline
                ),
                "\N{LARGE PURPLE CIRCLE}": lambda x: any(
                    a.type is discord.ActivityType.streaming for a in x.activities
                ),
                "\N{MOBILE PHONE}": lambda x: x.is_on_mobile(),
            }
            member_msg = f"Users online: **{online}/{total_users}**\n"
            count = 1
            for emoji, value in online_stats.items():
                try:
                    num = len([m for m in guild.members if value(m)])
                except Exception as error:
                    print(error)
                    continue
                else:
                    member_msg += f"{emoji} **{num}** " + (
                        "\n" if count % 2 == 0 else ""
                    )
                count += 1

            verif = {
                "none": "0 - None",
                "low": "1 - Low",
                "medium": "2 - Medium",
                "high": "3 - High",
                "highest": "4 - Highest",
            }

            joined_on = None
            if guild.me.joined_at and interaction.created_at:
                joined_on = "{bot_name} joined this server on {bot_join}. That's over {since_join} days ago!".format(
                    bot_name=guild.me.display_name,
                    bot_join=guild.me.joined_at.strftime("%d %b %Y %H:%M:%S"),
                    since_join=str((interaction.created_at - guild.me.joined_at).days),
                )

            data = OrangeEmbed(
                description=(f"{guild.description}\n\n" if guild.description else "")
                + created_at,
            )
            data.set_author(
                name=guild.name,
                icon_url=(
                    "https://cdn.discordapp.com/emojis/457879292152381443.png"
                    if "VERIFIED" in guild.features
                    else (
                        "https://cdn.discordapp.com/emojis/508929941610430464.png"
                        if "PARTNERED" in guild.features
                        else None
                    )
                ),
            )
            if guild.icon:
                data.set_thumbnail(url=guild.icon)
            data.add_field(name="Members:", value=member_msg)
            data.add_field(
                name="Channels:",
                value=(
                    "\N{SPEECH BALLOON} Text: {text}\n"
                    "\N{SPEAKER WITH THREE SOUND WAVES} Voice: {voice}\n"
                    "\N{STUDIO MICROPHONE} Stage: {stage}\n"
                    ":cat2: Categories: {categories}\n"
                    ":heavy_equals_sign: Total: {total}"
                ).format(
                    text=f"**{text_channels}**",
                    voice=f"**{voice_channels}**",
                    stage=f"**{stage_channels}**",
                    categories=f"**{len(guild.categories)}**",
                    total=f"**{len(guild.channels)}**",
                ),
            )
            data.add_field(
                name="Utility:",
                value=(
                    "Owner: {owner}\nVerif. level: {verif}\nServer ID: {id}{shard_info}"
                ).format(
                    owner=f"**{guild.owner}**",
                    verif=f"**{verif[str(guild.verification_level)]}**",
                    id=f"**{guild.id}**",
                    shard_info=shard_info,
                ),
                inline=False,
            )
            data.add_field(
                name="Misc:",
                value=(
                    "AFK channel: {afk_chan}\n"
                    "AFK timeout: **{afk_timeout}**\n"
                    "Custom emojis: **{emoji_count}**\n"
                    "Roles: **{role_count}**"
                ).format(
                    afk_chan=guild.afk_channel if guild.afk_channel else "**Not set**",
                    afk_timeout=guild.afk_timeout,
                    emoji_count=len(guild.emojis),
                    role_count=len(guild.roles),
                ),
                inline=False,
            )

            excluded_features = {
                # available to everyone since forum channels private beta
                "THREE_DAY_THREAD_ARCHIVE",
                "SEVEN_DAY_THREAD_ARCHIVE",
                # rolled out to everyone already
                "NEW_THREAD_PERMISSIONS",
                "TEXT_IN_VOICE_ENABLED",
                "THREADS_ENABLED",
                # available to everyone sometime after forum channel release
                "PRIVATE_THREADS",
            }
            custom_feature_names = {
                "VANITY_URL": "Vanity URL",
                "VIP_REGIONS": "VIP regions",
            }
            features = sorted(guild.features)
            if "COMMUNITY" in features:
                features.remove("NEWS")
            feature_names = [
                custom_feature_names.get(
                    feature, " ".join(feature.split("_")).capitalize()
                )
                for feature in features
                if feature not in excluded_features
            ]
            if guild.features:
                data.add_field(
                    name="Server features:",
                    value="\n".join(
                        f"\N{WHITE HEAVY CHECK MARK} {feature}"
                        for feature in feature_names
                    ),
                )

            if guild.premium_tier != 0:
                nitro_boost = (
                    "Tier {boostlevel} with {nitroboosters} boosts\n"
                    "File size limit: **{filelimit}**\n"
                    "Emoji limit: **{emojis_limit}**\n"
                    "VCs max bitrate: **{bitrate}**"
                ).format(
                    boostlevel=guild.premium_tier,
                    nitroboosters=guild.premium_subscription_count,
                    filelimit=_size(guild.filesize_limit),
                    emojis_limit=guild.emoji_limit,
                    bitrate=_bitsize(guild.bitrate_limit),
                )
                data.add_field(name="Nitro Boost:", value=nitro_boost)
            if guild.splash:
                data.set_image(url=guild.splash.replace(format="png"))
            data.set_footer(text=joined_on)

        await interaction.response.send_message(embed=data)

    @app_commands.command(  # type: ignore
        name="getallwithrole",
        description="Get all users with the specified role(s). (Max 4 roles)",
    )
    @app_commands.guild_only
    async def _getallwithrole(
        self,
        interaction: discord.Interaction,
        role: discord.Role,
        role2: discord.Role | None = None,
        role3: discord.Role | None = None,
        role4: discord.Role | None = None,
    ):
        await interaction.response.defer(ephemeral=True)
        desc = f"Role(s): {role.mention}"
        if not (role2 or role3):
            results = role.members
        else:
            members = set(role.members)
            if role2:
                members = members.intersection(role2.members)
                desc += f", {role2.mention}"
            if role3:
                members = members.intersection(role3.members)
                desc += f", {role3.mention}"
            if role4:
                members = members.intersection(role4.members)
                desc += f", {role4.mention}"
            results = sorted(members, key=lambda x: x.display_name)

        # Check for character max being exceeded (6000 total in embed or 1024 per field)
        nicks = "\n".join([r.display_name for r in results])
        usernames = ("\n".join([r.name for r in results]),)
        ids = "\n".join(str(r.id) for r in results)

        if len(nicks) > 1024 or len(usernames) > 1024 or len(ids) > 1024:
            msg = "\n".join([f"{p.display_name}:{p.name}:{p.id}" for p in results])
            if len(msg) > 2000:
                paged_msg = Pagify(text=msg)
                log.debug(f"Paged Msg: {paged_msg}")
                for page in paged_msg:
                    await interaction.followup.send(
                        content=f"```\n{page}\n```",
                        ephemeral=True,
                    )
            else:
                await interaction.followup.send(f"```\n{msg}\n```", ephemeral=True)
        else:
            embed = discord.Embed(
                title="Matching Members",
                description=desc,
                color=discord.Color.blue(),
            )
            embed.add_field(
                name="Player", value="\n".join(r.mention for r in results), inline=True
            )
            embed.add_field(
                name="Username", value="\n".join(r.name for r in results), inline=True
            )
            embed.add_field(
                name="Discord ID",
                value="\n".join(str(r.id) for r in results),
                inline=True,
            )

            embed.set_footer(text=f"Found {len(results)} matching player(s).")
            await interaction.followup.send(embed=embed, ephemeral=True)

    @app_commands.command(  # type: ignore
        name="addrole", description="Add a role to the specified user"
    )
    @app_commands.describe(role="Discord role to add", member="Player discord name")
    @app_commands.checks.has_permissions(manage_roles=True)
    @app_commands.checks.bot_has_permissions(manage_roles=True)
    @app_commands.guild_only
    async def _addrole(
        self,
        interaction: discord.Interaction,
        role: discord.Role,
        member: discord.Member,
    ):
        try:
            await member.add_roles(role)
            await interaction.response.send_message(
                embed=SuccessEmbed(
                    description=f"Added {role.mention} role to {member.mention}"
                ),
                ephemeral=True,
            )
        except discord.Forbidden as exc:
            await interaction.response.send_message(
                embed=ExceptionErrorEmbed(
                    description=f"Unable to add {role.mention} role to {member.mention}",
                    exc_message=exc.text,
                ),
                ephemeral=True,
            )

    @app_commands.command(  # type: ignore
        name="bulkaddrole", description="Add a role a list of user(s) or another role"
    )
    @app_commands.describe(
        role="Discord role to add",
        members='Space delimited discord IDs to apply role. (Example: "138778232802508801 352600418062303244") (Optional)',
        to_role="Add the role to everyone in this role. (Optional)",
    )
    @app_commands.guild_only
    @app_commands.checks.bot_has_permissions(manage_roles=True)
    @app_commands.checks.has_permissions(manage_roles=True)
    async def _bulkaddrole_cmd(
        self,
        interaction: discord.Interaction,
        role: discord.Role,
        members: Transform[list[discord.Member], GreedyMemberTransformer] | None = None,
        to_role: discord.Role | None = None,
    ):
        if members:
            mlist = members
        elif to_role:
            mlist = to_role.members
        else:
            await interaction.response.send_message(
                embed=ErrorEmbed(
                    description="You must specify a list of members or a destination role."
                ),
                ephemeral=True,
            )
            return

        count = len(mlist)
        bulk_view = BulkRoleConfirmView(
            interaction, action=BulkRoleAction.ADD, role=role, count=count
        )
        await bulk_view.prompt()
        await bulk_view.wait()

        if not bulk_view.result:
            return

        failed = []
        for m in mlist:
            try:
                await m.add_roles(role)
            except discord.Forbidden:
                failed.append(m)

        embed = SuccessEmbed(
            description=f"Applied {role.mention} to **{count-len(failed)}/{count}** users(s)."
        )
        if failed:
            embed.add_field(
                name="Failed",
                value="\n".join([f.mention for f in failed]),
                inline=False,
            )
        await interaction.edit_original_response(embed=embed, view=None)

    @app_commands.command(  # type: ignore
        name="removerole", description="Remove a role to the specified user"
    )
    @app_commands.describe(role="Discord role to remove", member="Player discord name")
    @app_commands.checks.has_permissions(manage_roles=True)
    @app_commands.checks.bot_has_permissions(manage_roles=True)
    @app_commands.guild_only
    async def _removerole(
        self,
        interaction: discord.Interaction,
        role: discord.Role,
        member: discord.Member,
    ):
        try:
            await member.remove_roles(role)
            await interaction.response.send_message(
                embed=SuccessEmbed(
                    description=f"Removed {role.mention} role to {member.mention}"
                ),
                ephemeral=True,
            )
        except discord.Forbidden as exc:
            await interaction.response.send_message(
                embed=ExceptionErrorEmbed(
                    description=f"Unable to remove {role.mention} role to {member.mention}",
                    exc_message=exc.text,
                ),
                ephemeral=True,
            )

    @app_commands.command(  # type: ignore
        name="bulkremoverole", description="Remove a role a list of user(s)"
    )
    @app_commands.describe(
        role="Discord role to remove",
        members='Space delimited discord IDs to remove role. (Example: "138778232802508801 352600418062303244")',
    )
    @app_commands.checks.has_permissions(manage_roles=True)
    @app_commands.checks.bot_has_permissions(manage_roles=True)
    @app_commands.guild_only
    async def _bulkremoverole(
        self,
        interaction: discord.Interaction,
        role: discord.Role,
        members: Optional[Transform[list[discord.Member], GreedyMemberTransformer]],
    ):
        count = len(members) if members else len(role.members)

        bulk_view = BulkRoleConfirmView(
            interaction, action=BulkRoleAction.REMOVE, role=role, count=count
        )
        await bulk_view.prompt()
        await bulk_view.wait()

        if not bulk_view.result:
            return

        mlist = members if members else role.members

        failed = []
        for m in mlist:
            try:
                await m.remove_roles(role)
            except discord.Forbidden:
                failed.append(m)

        embed = SuccessEmbed(
            description=f"Removed {role.mention} from **{count-len(failed)}/{count}** users(s)."
        )
        if failed:
            embed.add_field(
                name="Failed",
                value="\n".join([f.mention for f in failed]),
                inline=False,
            )
        await interaction.edit_original_response(embed=embed, view=None)

    def handle_custom(self, user):
        a = [c for c in user.activities if c.type == discord.ActivityType.custom]
        if not a:
            return None, discord.ActivityType.custom
        activity: discord.CustomActivity = a[0]
        c_status = None
        if not activity.name and not activity.emoji:
            return None, discord.ActivityType.custom
        elif activity.name and activity.emoji:
            c_status = f"Custom: {activity.emoji} {activity.name}"
        elif activity.emoji:
            c_status = f"Custom: {activity.emoji}"
        elif activity.name:
            c_status = f"Custom: {activity.name}"
        return c_status, discord.ActivityType.custom

    def handle_playing(self, user):
        p_acts = [c for c in user.activities if c.type == discord.ActivityType.playing]
        if not p_acts:
            return None, discord.ActivityType.playing
        p_act = p_acts[0]
        act = f"Playing: {p_act.name}"
        return act, discord.ActivityType.playing

    def handle_streaming(self, user):
        s_acts = [
            c for c in user.activities if c.type == discord.ActivityType.streaming
        ]
        if not s_acts:
            return None, discord.ActivityType.streaming
        s_act = s_acts[0]
        if isinstance(s_act, discord.Streaming) and s_act.name:
            act = "Streaming: [{name}{sep}{game}]({url})".format(
                name=discord.utils.escape_markdown(s_act.name),
                sep=" | " if s_act.game else "",
                game=discord.utils.escape_markdown(s_act.game) if s_act.game else "",
                url=s_act.url,
            )
        else:
            act = f"Streaming: {s_act.name}"
        return act, discord.ActivityType.streaming

    def handle_listening(self, user):
        l_acts = [
            c for c in user.activities if c.type == discord.ActivityType.listening
        ]
        if not l_acts:
            return None, discord.ActivityType.listening
        l_act = l_acts[0]
        if isinstance(l_act, discord.Spotify):
            act = "Listening: [{title}{sep}{artist}]({url})".format(
                title=discord.utils.escape_markdown(l_act.title),
                sep=" | " if l_act.artist else "",
                artist=(
                    discord.utils.escape_markdown(l_act.artist) if l_act.artist else ""
                ),
                url=f"https://open.spotify.com/track/{l_act.track_id}",
            )
        else:
            act = f"Listening: {l_act.name}"
        return act, discord.ActivityType.listening

    def handle_watching(self, user):
        w_acts = [c for c in user.activities if c.type == discord.ActivityType.watching]
        if not w_acts:
            return None, discord.ActivityType.watching
        w_act = w_acts[0]
        act = f"Watching: {w_act.name}"
        return act, discord.ActivityType.watching

    def handle_competing(self, user):
        w_acts = [
            c for c in user.activities if c.type == discord.ActivityType.competing
        ]
        if not w_acts:
            return None, discord.ActivityType.competing
        w_act = w_acts[0]
        act = f"Competing in: {w_act.name}"
        return act, discord.ActivityType.competing

    def get_status_string(self, user):
        string = ""
        for a in [
            self.handle_custom(user),
            self.handle_playing(user),
            self.handle_listening(user),
            self.handle_streaming(user),
            self.handle_watching(user),
            self.handle_competing(user),
        ]:
            status_string, status_type = a
            if status_string is None:
                continue
            string += f"{status_string}\n"
        return string
