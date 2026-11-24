import logging
from collections.abc import Iterable

import discord
from rscapi.models.franchise import Franchise
from rscapi.models.franchise_list import FranchiseList
from rscapi.models.league_player import LeaguePlayer
from rscapi.models.player import Player
from rscapi.models.player_transaction_updates import PlayerTransactionUpdates
from rscapi.models.team_player import TeamPlayer
from rscapi.models.tier import Tier
from rscapi.models.transaction_response import TransactionResponse

from rsc import const
from rsc.enums import Status, SubStatus
from rsc.logs import GuildLogAdapter
from rsc.transactions import planner
from rsc.transactions.writer import NicknameRefusedError, apply_member_changes
from rsc.utils import utils

logger = logging.getLogger("red.rsc.transactions.roles")
log = GuildLogAdapter(logger)

# Roles each move finds by name. Checked before the API call, so a missing role stops
# the move with nothing changed, instead of failing after the API has applied it.
# Tier and franchise roles come from the API's answer, so they can't be checked first.
CUT_ROLES = (const.CAPTAIN_ROLE, const.FORMER_PLAYER_ROLE, const.FREE_AGENT_ROLE, const.SPECTATOR_ROLE)
SIGN_ROLES = (const.DRAFT_ELIGIBLE, const.FORMER_PLAYER_ROLE, const.FREE_AGENT_ROLE, const.SPECTATOR_ROLE)
SUB_ROLES = (const.SUBBED_OUT_ROLE,)
IR_ROLES = (const.IR_ROLE,)
RETIRE_ROLES = (const.AGM_ROLE, const.FORMER_PLAYER_ROLE, const.LEAGUE_ROLE)
CAPTAIN_ROLES = (const.CAPTAIN_ROLE,)


def missing_roles(guild: discord.Guild, names: Iterable[str]) -> list[str]:
    """The roles in `names` that don't exist in the guild, in the order given."""
    return [name for name in names if not discord.utils.get(guild.roles, name=name)]


async def apply_roles_and_name(
    member: discord.Member,
    *,
    remove: list[discord.Role],
    add: list[discord.Role],
    name: str,
    prefix: str | None,
) -> None:
    """Send a member's role changes and nickname through `apply_member_changes`.

    A name that cannot be a nickname, such as one too long for Discord, still
    gets its roles written. The error is raised afterwards, as is
    `NicknameRefusedError` when Discord will not let the bot write the nickname.
    """
    try:
        nick = await utils.discord_name_change(member, name, prefix)
    except ValueError:
        await apply_member_changes(member, remove=remove, add=add)
        raise
    await apply_member_changes(member, remove=remove, add=add, nick=nick)


async def update_signed_player_discord(
    guild: discord.Guild,
    player: discord.Member,
    ptu: PlayerTransactionUpdates,
    tiers: list[Tier] | None = None,
):
    # We check roles and name here just in case.
    if not ptu.player.tier:
        raise AttributeError(f"{player.display_name} ({player.id}) has no tier data.")

    if not ptu.new_team:
        raise AttributeError(f"PlayerTransactionUpdate object has no new team data for signed player: {player.display_name} ({player.id})")

    if not ptu.new_team.tier:
        raise AttributeError(f"{ptu.new_team.name} has no tier data.")

    if not ptu.player.team:
        raise AttributeError(f"{player.display_name} ({player.id}) has no team data.")

    if not ptu.player.team.franchise:
        raise AttributeError(f"{player.display_name} ({player.id}) has no franchise data.")

    roles_to_remove: list[discord.Role] = []
    roles_to_add: list[discord.Role] = []

    # Remove old tier roles and tier FA role on discord.Member
    if tiers:
        for r in player.roles:
            for tier in tiers:
                if r in roles_to_remove:
                    continue

                if r.name.endswith("FA") or (r.name.lower() == tier.name.lower() and r.name.lower() != ptu.new_team.tier.lower()):
                    roles_to_remove.append(r)
    else:
        # Remove FA tier role
        for r in player.roles:
            if r in roles_to_remove:
                continue

            if r.name.endswith("FA"):
                roles_to_remove.append(r)

    # Remove Spectator
    spec_role = await utils.get_spectator_role(guild)
    if spec_role in player.roles:
        roles_to_remove.append(spec_role)

    # Remove Former Player
    former_role = await utils.get_former_player_role(guild)
    if former_role in player.roles:
        roles_to_remove.append(former_role)

    # FA Role:
    fa_role = await utils.get_free_agent_role(guild)
    if fa_role in player.roles:
        roles_to_remove.append(fa_role)

    # Draft Eligible role
    de_role = await utils.get_draft_eligible_role(guild)
    if de_role in player.roles:
        roles_to_remove.append(de_role)

    # Remove old franchise role if it exists
    old_frole = await utils.franchise_role_from_disord_member(player)
    if old_frole:
        roles_to_remove.append(old_frole)

    # Add franchise role
    frole = await utils.franchise_role_from_league_player(guild, ptu.player)
    if frole:
        roles_to_add.append(frole)
    else:
        raise ValueError(f"New franchise role not found for {player.display_name} ({player.id})")

    # Verify player has tier role
    tier_role = await utils.get_tier_role(guild, name=ptu.new_team.tier)
    if tier_role:
        if tier_role not in player.roles:
            roles_to_add.append(tier_role)
    else:
        raise ValueError(f"Tier role not found: {ptu.new_team.tier}")

    try:
        await apply_roles_and_name(
            player, remove=roles_to_remove, add=roles_to_add, name=ptu.player.player.name, prefix=ptu.player.team.franchise.prefix
        )
    except NicknameRefusedError as exc:
        log.warning(f"Unable to update nickname {player.display_name} ({player.id}): {exc}")


async def update_cut_player_discord(
    guild: discord.Guild,
    player: discord.Member,
    response: TransactionResponse,
    ptu: PlayerTransactionUpdates,
    devleague: bool = True,
):
    if not ptu.old_team:
        raise AttributeError(f"{player.display_name} ({player.id}) has no old team data.")

    if not ptu.old_team.tier:
        raise AttributeError(f"{player.display_name} ({player.id}) has no old team tier data.")

    if not ptu.player.tier:
        raise AttributeError(f"{player.display_name} ({player.id}) has no tier data.")

    if not response.first_franchise:
        raise AttributeError(f"{player.display_name} ({player.id}) has first franchise data.")

    roles_to_remove: list[discord.Role] = []
    roles_to_add: list[discord.Role] = []

    # Remove Spectator
    spec_role = await utils.get_spectator_role(guild)
    if spec_role in player.roles:
        roles_to_remove.append(spec_role)

    # Remove Former Player
    former_role = await utils.get_former_player_role(guild)
    if former_role in player.roles:
        roles_to_remove.append(former_role)

    # Remove captain
    captain_role = await utils.get_captain_role(guild)
    roles_to_remove.append(captain_role)

    # Update tier role, handle promotion case
    log.debug(f"Old Tier: {ptu.old_team.tier}", guild=guild)
    old_tier_role = await utils.get_tier_role(guild, ptu.old_team.tier)
    log.debug(f"New Tier: {ptu.player.tier.name}", guild=guild)
    tier_role = await utils.get_tier_role(guild, ptu.player.tier.name)
    if old_tier_role != tier_role:
        roles_to_remove.append(old_tier_role)
        roles_to_add.append(tier_role)

    # Apply tier role if they never had it
    if tier_role not in player.roles and tier_role not in roles_to_add:
        roles_to_add.append(tier_role)

    # Free agent roles
    fa_role = await utils.get_free_agent_role(guild)
    tier_fa_role = await utils.get_tier_fa_role(guild, ptu.player.tier.name)
    if fa_role not in player.roles:
        roles_to_add.append(fa_role)
    if tier_fa_role not in player.roles:
        roles_to_add.append(tier_fa_role)

    # Franchise Role
    franchise_role = await utils.franchise_role_from_name(guild, response.first_franchise.name)
    if not franchise_role:
        log.error(
            f"Unable to find franchise name during cut: {response.first_franchise.name}",
            guild=guild,
        )
        raise ValueError(f"Unable to find franchise role for **{response.first_franchise.name}**")

    # Make changes for Non-GM player
    first_gm = response.first_franchise.gm
    is_gm = bool(first_gm) and first_gm.discord_id == player.id
    if not is_gm:
        roles_to_remove.append(franchise_role)

        # Add Dev League Interest if it exists
        # dev_league_role = discord.utils.get(guild.roles, name=const.DEV_LEAGUE_ROLE)
        # if dev_league_role and dev_league_role not in player.roles:
        #     roles_to_add.append(dev_league_role)
    else:
        # A cut GM is not a free agent, because no other franchise can roster a GM.
        fa_roles = (fa_role, tier_fa_role)
        roles_to_add = [r for r in roles_to_add if r not in fa_roles]
        roles_to_remove.extend(r for r in fa_roles if r in player.roles)

    prefix = response.first_franchise.prefix if is_gm else "FA"
    try:
        await apply_roles_and_name(player, remove=roles_to_remove, add=roles_to_add, name=ptu.player.player.name, prefix=prefix)
    except NicknameRefusedError as exc:
        log.warning(f"Unable to update nickname {player.display_name} ({player.id}): {exc}")


async def update_team_captain_discord(
    guild: discord.Guild,
    players: list[Player] | list[TeamPlayer],
):
    cpt_role = await utils.get_captain_role(guild)

    for p in players:
        m = guild.get_member(p.discord_id)
        if not m:
            log.error(f"Unable to find rostered player in guild: {p.discord_id}", guild=guild)
            continue

        if p.captain and cpt_role not in m.roles:
            await apply_member_changes(m, add=[cpt_role])
        elif not p.captain and cpt_role in m.roles:
            await apply_member_changes(m, remove=[cpt_role])


def agm_rsc_name(member: discord.Member, franchise: Franchise | FranchiseList) -> str:
    """The RSC name to write into an AGM's nickname.

    Prefers the name the API has on the `agms` entry, the same way the
    non-playing GM sync prefers `franchise.gm.rsc_name`. Falls back to what the
    current nickname implies, since `rsc_name` is optional on `FranchiseGM` and
    a missing one is no reason to skip the prefix restore.
    """
    for agm in franchise.agms or []:
        if agm.discord_id == member.id and agm.rsc_name:
            return agm.rsc_name
    return utils.rsc_name_from_member(member)


async def agm_franchise_role(guild: discord.Guild, franchise: Franchise | FranchiseList) -> discord.Role | None:
    """The franchise role for an AGM's franchise, or `None` if it cannot be found.

    Franchise roles are named `"<Franchise> (<GM>)"`, so a franchise between GMs
    has no role name to build. Fall back to matching on the franchise name
    alone, and answer `None` rather than raising: an AGM whose role cannot be
    resolved should keep whatever they have, not be stripped bare.
    """
    try:
        return await utils.franchise_role_from_model(guild, franchise=franchise)
    except (AttributeError, ValueError):
        log.warning(f"Unable to resolve franchise role for {franchise.name} by GM name. Falling back to name match.", guild=guild)

    if not franchise.name:
        return None
    return await utils.franchise_role_from_name(guild, franchise.name)


async def status_role(guild: discord.Guild, name: str) -> discord.Role:
    """The guild's role for a name the planner gives. A name that is not a status role is a tier role or a tier FA role."""
    match name:
        case const.LEAGUE_ROLE:
            return await utils.get_league_role(guild)
        case const.FORMER_PLAYER_ROLE:
            return await utils.get_former_player_role(guild)
        case const.FREE_AGENT_ROLE:
            return await utils.get_free_agent_role(guild)
        case const.PERM_FA_ROLE:
            return await utils.get_permfa_role(guild)
        case const.PERM_FA_WAITING_ROLE:
            return await utils.get_permfa_waiting_role(guild)
        case const.DRAFT_ELIGIBLE:
            return await utils.get_draft_eligible_role(guild)
        case const.IR_ROLE:
            return await utils.get_ir_role(guild)
        case const.CAPTAIN_ROLE:
            return await utils.get_captain_role(guild)
        case const.AGM_ROLE:
            return await utils.get_agm_role(guild)
        case const.SUBBED_OUT_ROLE:
            return await utils.get_subbed_out_role(guild)
        case _ if name.endswith("FA"):
            return await utils.get_tier_fa_role(guild, name.removesuffix("FA"))
        case _:
            return await utils.get_tier_role(guild, name)


def member_state(member: discord.Member) -> planner.MemberState:
    return planner.MemberState(frozenset(role.name for role in member.roles), member.display_name)


def league_player_row(league_player: LeaguePlayer, team: planner.Seat | None = None) -> planner.Row:
    return planner.Row(
        name=league_player.player.name,
        tier=(league_player.tier.name or None) if league_player.tier else None,
        captain=bool(league_player.captain),
        subbed_out=league_player.sub_status == SubStatus.OUT,
        team=team,
    )


async def agm_seat(
    guild: discord.Guild, member: discord.Member, franchise: Franchise | FranchiseList | None
) -> tuple[planner.Seat | None, list[discord.Role]]:
    """An AGM's seat on their franchise, and the franchise role when the guild has one."""
    if not franchise:
        return None, []

    role = await agm_franchise_role(guild, franchise)
    if not role:
        log.error(
            f"Unable to find franchise role for AGM {member.display_name} ({member.id}) on {franchise.name}. "
            "Leaving their existing franchise roles in place.",
            guild=guild,
        )
    return planner.Seat(role.name if role else None, franchise.prefix, agm_rsc_name(member, franchise)), [role] if role else []


async def role_changes(
    guild: discord.Guild, member: discord.Member, plan: planner.Plan, resolved: Iterable[discord.Role] = ()
) -> tuple[list[discord.Role], list[discord.Role]]:
    """The roles to remove and to add so the member holds exactly the plan's roles.

    `resolved` holds roles the caller already has. A role to add that is not
    among them is looked up in the guild, which raises `ValueError` when the
    guild does not have it.
    """
    held = {role.name for role in member.roles}
    known = {role.name: role for role in resolved}
    remove = [role for role in member.roles if role.name not in plan.roles]
    add = [known.get(name) or await status_role(guild, name) for name in sorted(plan.roles - held)]
    return remove, add


async def send_changes(
    member: discord.Member, remove: list[discord.Role], add: list[discord.Role], nickname: planner.Rename | planner.StripPrefix
) -> None:
    if isinstance(nickname, planner.Rename):
        await apply_roles_and_name(member, remove=remove, add=add, name=nickname.name, prefix=nickname.prefix)
        return

    new_nick = await utils.remove_prefix(member)
    if new_nick == member.display_name:
        await apply_member_changes(member, remove=remove, add=add)
        return

    if len(new_nick) > 32 or not new_nick:
        await apply_member_changes(member, remove=remove, add=add)
        if new_nick:
            raise ValueError(f"Discord name is too long: {len(new_nick)} characters")
        raise ValueError(f"Error changing name. Empty or <1 characters: {member.mention}")

    await apply_member_changes(member, remove=remove, add=add, nick=new_nick)


async def sync_to_plan(guild: discord.Guild, member: discord.Member, plan: planner.Plan, resolved: Iterable[discord.Role] = ()) -> None:
    remove, add = await role_changes(guild, member, plan, resolved)
    try:
        await send_changes(member, remove, add, plan.nickname)
    except NicknameRefusedError as exc:
        log.warning(f"Unable to update nickname {member.display_name} ({member.id}): {exc}")


async def update_nonplaying_discord(
    guild: discord.Guild,
    member: discord.Member,
    tiers: list[Tier],
    default_roles: list[discord.Role] | None = None,
    *,
    agm_franchise: Franchise | FranchiseList | None,
):
    """Sync a member who is not playing in the league.

    `agm_franchise` is the franchise the API says this member is an AGM of, or
    `None`. It is the *only* AGM signal used here. Reading it off the discord
    "Assistant GM" role instead -- which is what this did before -- is circular:
    once that role goes missing the sync decides they were never an AGM, strips
    the franchise role and prefix, and nothing can put them back. A non-playing
    AGM has no `LeaguePlayer` at all, so this function is the only thing that
    ever sees them.

    Keyword only and deliberately not defaulted: a call site that forgets it
    should fail loudly rather than quietly strip someone's AGM state.
    """
    agm, resolved = await agm_seat(guild, member, agm_franchise)
    welcome = default_roles or []
    plan = planner.plan_member(
        planner.NoRow.NON_PLAYING,
        member_state(member),
        agm=agm,
        tiers=[tier.name for tier in tiers],
        welcome=[role.name for role in welcome],
    )
    if not agm_franchise:
        return await sync_to_plan(guild, member, plan, welcome)

    remove, add = await role_changes(guild, member, plan, [*resolved, *welcome])
    # ValueError is swallowed alongside a refused nickname because the roles
    # are already written when either is raised. `/transactions retire` does
    # not wrap this call, so letting a 32 character nickname raise would
    # report the whole retire as failed after the API mutation had gone through.
    try:
        await send_changes(member, remove, add, plan.nickname)
    except (NicknameRefusedError, ValueError) as exc:
        log.error(f"Unable to restore AGM nickname {member.display_name} ({member.id}): {exc}", guild=guild)


async def update_nonplaying_gm_discord(
    guild: discord.Guild,
    player: discord.Member,
    franchise: Franchise | FranchiseList,
    tiers: list[Tier],
):
    if not franchise.gm:
        raise AttributeError(f"{franchise.name} ({franchise.id}) has no GM data.")

    if franchise.gm.discord_id != player.id:
        raise ValueError(f"{player.display_name} ({player.id}) is not the GM of {franchise.name}.")

    frole = await utils.franchise_role_from_model(guild, franchise=franchise)
    plan = planner.plan_member(
        planner.NoRow.NON_PLAYING_GM,
        member_state(player),
        gm=planner.Seat(frole.name, franchise.prefix, franchise.gm.rsc_name),
        tiers=[tier.name for tier in tiers],
    )
    if not franchise.gm.rsc_name:
        remove, add = await role_changes(guild, player, plan, [frole])
        await apply_member_changes(player, remove=remove, add=add)
        raise ValueError("Franchise GM has no name in API...")

    await sync_to_plan(guild, player, plan, [frole])


async def update_unsigned_gm_discord(
    guild: discord.Guild,
    player: discord.Member,
    league_player: LeaguePlayer,
    franchise: Franchise | FranchiseList,
    tiers: list[Tier],
):
    if league_player.status != Status.UNSIGNED_GM:
        raise ValueError(f"{player.display_name} ({player.id}) is not an unsigned GM.")

    if not league_player.tier:
        raise AttributeError(f"{player.display_name} ({player.id}) has no tier data.")

    tier_role = await utils.get_tier_role(guild, name=league_player.tier.name)
    frole = await utils.franchise_role_from_model(guild, franchise=franchise)
    plan = planner.plan_member(
        Status.UNSIGNED_GM,
        member_state(player),
        row=league_player_row(league_player),
        gm=planner.Seat(frole.name, franchise.prefix),
        tiers=[tier.name for tier in tiers],
    )
    await sync_to_plan(guild, player, plan, [tier_role, frole])


async def update_rostered_discord(
    guild: discord.Guild,
    player: discord.Member,
    league_player: LeaguePlayer,
    tiers: list[Tier],
    *,
    agm_franchise: Franchise | FranchiseList | None = None,
):
    if league_player.status not in (Status.ROSTERED, Status.RENEWED, Status.IR, Status.AGMIR):
        raise ValueError(f"{player.display_name} ({player.id}) is not rostered.")

    if not league_player.tier:
        raise AttributeError(f"{player.display_name} ({player.id}) has no tier data.")

    if not league_player.team:
        raise AttributeError(f"{player.display_name} ({player.id}) has no team data")

    if not league_player.team.franchise:
        raise AttributeError(f"{player.display_name} ({player.id}) has no franchise data.")

    frole = await utils.franchise_role_from_league_player(guild, league_player)
    plan = planner.plan_member(
        Status(league_player.status),
        member_state(player),
        row=league_player_row(league_player, planner.Seat(frole.name, league_player.team.franchise.prefix)),
        # The roster owns the franchise role and the tag here, so an AGM's seat only brings the AGM role.
        agm=planner.Seat(None, agm_franchise.prefix) if agm_franchise else None,
        tiers=[tier.name for tier in tiers],
    )
    await sync_to_plan(guild, player, plan, [frole])


async def sync_unsigned_player(
    guild: discord.Guild,
    player: discord.Member,
    league_player: LeaguePlayer,
    tiers: list[Tier],
    agm_franchise: Franchise | FranchiseList | None,
    devleague: bool = False,
) -> None:
    agm, resolved = await agm_seat(guild, player, agm_franchise)
    dev_league_role = discord.utils.get(guild.roles, name=const.DEV_LEAGUE_ROLE) if devleague else None
    if dev_league_role:
        resolved.append(dev_league_role)

    plan = planner.plan_member(
        Status(league_player.status),
        member_state(player),
        row=league_player_row(league_player),
        agm=agm,
        tiers=[tier.name for tier in tiers],
        devleague=dev_league_role is not None,
    )
    await sync_to_plan(guild, player, plan, resolved)


async def update_free_agent_discord(
    guild: discord.Guild,
    player: discord.Member,
    league_player: LeaguePlayer,
    tiers: list[Tier],
    devleague: bool = False,
    *,
    agm_franchise: Franchise | FranchiseList | None,
):
    if league_player.status not in (Status.FREE_AGENT, Status.PERM_FA, Status.WAIVERS, Status.WAIVER_RELEASE, Status.WAIVER_CLAIM):
        raise ValueError(f"{player.display_name} ({player.id}) is not a free agent.")

    if not league_player.tier:
        raise AttributeError(f"{player.display_name} ({player.id}) has no tier data.")

    await sync_unsigned_player(guild, player, league_player, tiers, agm_franchise, devleague)


async def update_draft_eligible_discord(
    guild: discord.Guild,
    player: discord.Member,
    league_player: LeaguePlayer,
    tiers: list[Tier],
    devleague: bool = False,
    *,
    agm_franchise: Franchise | FranchiseList | None,
):
    if league_player.status != Status.DRAFT_ELIGIBLE:
        raise ValueError(f"{player.display_name} ({player.id}) is not draft eligible.")

    if tiers and not (league_player.tier and league_player.tier.name):
        log.warning(f"{player.display_name} ({player.id}) has no tier data.", guild=guild)

    await sync_unsigned_player(guild, player, league_player, tiers, agm_franchise, devleague)


async def update_permfa_waiting_discord(
    guild: discord.Guild,
    player: discord.Member,
    league_player: LeaguePlayer,
    tiers: list[Tier],
    *,
    agm_franchise: Franchise | FranchiseList | None,
):
    if league_player.status != Status.PERMFA_W:
        raise ValueError(f"{player.display_name} ({player.id}) is not a permfa in waiting...")

    await sync_unsigned_player(guild, player, league_player, tiers, agm_franchise)


async def update_league_player_discord(
    guild: discord.Guild,
    player: discord.Member,
    league_player: LeaguePlayer | None = None,
    tiers: list[Tier] | None = None,
    franchise: Franchise | FranchiseList | None = None,
    default_roles: list[discord.Role] | None = None,
    devleague: bool = False,
    *,
    agm_franchise: Franchise | FranchiseList | None,
):
    """Sync a member's discord state to whatever the API says about them.

    `agm_franchise` is the franchise the API lists this member as an AGM of, or
    `None`. Callers resolve it with `FranchiseMixIn.agm_franchise_of` (or, in a
    loop, `agm_franchise_map`), since these are module level functions with no
    cog to ask.

    Keyword only and deliberately not defaulted: forgetting it at a call site
    would silently strip an AGM's role, franchise role and prefix, which is the
    exact failure this parameter exists to stop.
    """
    if not tiers:
        tiers = []

    if not league_player:
        return await update_nonplaying_discord(
            guild=guild, member=player, tiers=tiers, default_roles=default_roles, agm_franchise=agm_franchise
        )

    if not league_player.status:
        raise ValueError("API returned league player with no status value")

    match league_player.status:
        case Status.ROSTERED | Status.RENEWED | Status.AGMIR | Status.IR:
            return await update_rostered_discord(
                guild=guild, player=player, league_player=league_player, tiers=tiers, agm_franchise=agm_franchise
            )
        case Status.DRAFT_ELIGIBLE:
            return await update_draft_eligible_discord(
                guild=guild, player=player, league_player=league_player, tiers=tiers, devleague=devleague, agm_franchise=agm_franchise
            )
        case Status.FREE_AGENT | Status.PERM_FA | Status.WAIVERS | Status.WAIVER_RELEASE | Status.WAIVER_CLAIM:
            return await update_free_agent_discord(
                guild=guild, player=player, league_player=league_player, tiers=tiers, devleague=devleague, agm_franchise=agm_franchise
            )
        case Status.UNSIGNED_GM:
            if not franchise:
                raise ValueError("Must provide franchise data to sync un-signed GM")
            return await update_unsigned_gm_discord(
                guild=guild, player=player, league_player=league_player, franchise=franchise, tiers=tiers
            )
        case Status.DROPPED | Status.FORMER | Status.BANNED:
            return await update_nonplaying_discord(
                guild=guild, member=player, tiers=tiers, default_roles=default_roles, agm_franchise=agm_franchise
            )
        case Status.PERMFA_W:
            return await update_permfa_waiting_discord(
                guild=guild, player=player, league_player=league_player, tiers=tiers, agm_franchise=agm_franchise
            )
        case _:
            raise ValueError(f"**{league_player.status}** is not currently supported.")
