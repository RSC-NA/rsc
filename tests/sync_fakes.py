"""A fake guild and member for running the role sync end to end.

The member's roles and nickname change when the sync writes them, so a test can
read the result back and run a second sync against it.
"""

from collections.abc import Iterable
from unittest.mock import AsyncMock, MagicMock

import discord
from rscapi.models.franchise_gm import FranchiseGM
from rscapi.models.franchise_list import FranchiseList
from rscapi.models.league_player import LeaguePlayer
from rscapi.models.league_player_member import LeaguePlayerMember
from rscapi.models.league_player_status_enum import LeaguePlayerStatusEnum
from rscapi.models.player_franchise import PlayerFranchise
from rscapi.models.player_team import PlayerTeam
from rscapi.models.tier import Tier

from rsc import const
from rsc.enums import Status

MEMBER_ID = 138778232802508801
OCEAN_ROLE = "The Ocean (someone)"
DESERT_ROLE = "The Desert (someoneelse)"
TIERS = [Tier(name="Premier", position=1), Tier(name="Elite", position=2)]
ROLE_NAMES = (
    const.LEAGUE_ROLE,
    const.SPECTATOR_ROLE,
    const.FORMER_PLAYER_ROLE,
    const.FREE_AGENT_ROLE,
    const.PERM_FA_ROLE,
    const.PERM_FA_WAITING_ROLE,
    const.DRAFT_ELIGIBLE,
    const.IR_ROLE,
    const.CAPTAIN_ROLE,
    const.SUBBED_OUT_ROLE,
    const.AGM_ROLE,
    const.GM_ROLE,
    "Premier",
    "PremierFA",
    "Elite",
    "EliteFA",
    OCEAN_ROLE,
    DESERT_ROLE,
)


def sync_guild() -> MagicMock:
    guild = MagicMock(spec=discord.Guild)
    guild.id = 395806681994493964
    guild.name = "RSC 3v3"
    guild.roles = []
    for name in ROLE_NAMES:
        role = MagicMock(spec=discord.Role)
        role.name = name
        guild.roles.append(role)
    return guild


def sync_member(guild: MagicMock, held: Iterable[str] = (), nick: str = "nickm") -> MagicMock:
    held = set(held)
    member = MagicMock(spec=discord.Member)
    member.id = MEMBER_ID
    member.guild = guild
    member.display_name = nick
    member.mention = f"<@{MEMBER_ID}>"
    member.roles = [r for r in guild.roles if r.name in held]

    async def add_roles(*roles: discord.Role) -> None:
        member.roles = member.roles + [r for r in roles if r not in member.roles]

    async def remove_roles(*roles: discord.Role) -> None:
        member.roles = [r for r in member.roles if r not in roles]

    async def edit(*, nick: str) -> None:
        member.display_name = nick

    member.add_roles = AsyncMock(side_effect=add_roles)
    member.remove_roles = AsyncMock(side_effect=remove_roles)
    member.edit = AsyncMock(side_effect=edit)
    return member


def role_names(member: MagicMock) -> set[str]:
    return {r.name for r in member.roles}


def discord_requests(member: MagicMock) -> int:
    """Requests discord.py sends for the writes so far: one per role added or removed, one per nickname edit."""
    role_writes = sum(len(c.args) for c in member.add_roles.await_args_list + member.remove_roles.await_args_list)
    return role_writes + member.edit.await_count


def forget_writes(member: MagicMock) -> None:
    for write in (member.add_roles, member.remove_roles, member.edit):
        write.reset_mock()


def league_player(status: Status, name: str = "nickm") -> LeaguePlayer:
    """The member's row, on a team of The Ocean in Premier."""
    franchise = PlayerFranchise(name="The Ocean", prefix="OCE", gm=FranchiseGM(rsc_name="someone", discord_id=7))
    return LeaguePlayer.model_construct(
        status=LeaguePlayerStatusEnum(status.value),
        captain=False,
        tier=TIERS[0],
        team=PlayerTeam(name="Waves", franchise=franchise),
        player=LeaguePlayerMember(name=name, discord_id=MEMBER_ID),
    )


def agm_franchise() -> FranchiseList:
    """The Ocean, as the API lists it when the member is one of its AGMs."""
    return FranchiseList(
        name="The Ocean",
        prefix="OCE",
        gm=FranchiseGM(rsc_name="someone", discord_id=7),
        agms=[FranchiseGM(rsc_name="nickm", discord_id=MEMBER_ID)],
    )
