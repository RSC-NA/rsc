import logging

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
from rsc.enums import Status
from rsc.logs import GuildLogAdapter
from rsc.utils import utils

logger = logging.getLogger("red.rsc.transactions.roles")
log = GuildLogAdapter(logger)


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

    # Update roles at same time to reduce API calls
    if roles_to_remove:
        log.debug(f"Removing roles: {roles_to_remove}", guild=guild)
        await player.remove_roles(*roles_to_remove)
    if roles_to_add:
        log.debug(f"Adding roles: {roles_to_add}", guild=guild)
        await player.add_roles(*roles_to_add)

    # Update player prefix
    try:
        log.debug(f"Changing {player.id} signed player nick", guild=guild)
        await utils.update_discord_name(member=player, name=ptu.player.player.name, prefix=ptu.player.team.franchise.prefix)
    except discord.Forbidden as exc:
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
        roles_to_add.remove(fa_role)
        roles_to_add.remove(tier_fa_role)

    if roles_to_remove:
        log.debug(f"Removing cut player roles: {roles_to_remove}", guild=guild)
        await player.remove_roles(*roles_to_remove)
    if roles_to_add:
        log.debug(f"Adding cut player roles: {roles_to_add}", guild=guild)
        await player.add_roles(*roles_to_add)

    log.debug("Updating cut player nickname", guild=guild)
    try:
        if is_gm:
            await utils.update_discord_name(member=player, name=ptu.player.player.name, prefix=response.first_franchise.prefix)
        else:
            await utils.update_discord_name(member=player, name=ptu.player.player.name, prefix="FA")
    except discord.Forbidden as exc:
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
            log.debug(f"Adding captain role: {m.display_name} ({m.id})", guild=guild)
            await m.add_roles(cpt_role)
        elif cpt_role in m.roles:
            log.debug(f"Removing captain role: {m.display_name} ({m.id})", guild=guild)
            await m.remove_roles(cpt_role)


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


async def apply_agm_role_updates(
    guild: discord.Guild,
    member: discord.Member,
    agm_franchise: Franchise | FranchiseList | None,
    roles_to_add: list[discord.Role],
    roles_to_remove: list[discord.Role],
    manage_franchise_roles: bool = True,
) -> discord.Role | None:
    """Fold the AGM reconcile into a caller's pending role batch.

    The API is authoritative in both directions: an AGM who lost the role gets
    it back, and a member the API no longer lists loses it. Merging into the
    caller's lists rather than writing directly keeps this to the one bulk
    add/remove pair every sync helper already makes.

    `manage_franchise_roles` is False on the rostered path, where the roster --
    not franchise staff -- owns the franchise role and the nickname prefix.

    Returns the AGM's franchise role when one was resolved.
    """
    agm_role = await utils.get_agm_role(guild)

    if not agm_franchise:
        if agm_role in member.roles:
            roles_to_remove.append(agm_role)
        return None

    if agm_role not in member.roles and agm_role not in roles_to_add:
        roles_to_add.append(agm_role)

    # Added here rather than left to the caller's role sweep: those sweeps only
    # iterate roles the member already has, so an AGM who lost the league role
    # would never get it back.
    league_role = await utils.get_league_role(guild)
    if league_role not in member.roles and league_role not in roles_to_add:
        roles_to_add.append(league_role)

    if not manage_franchise_roles:
        return None

    # Resolved before anything is stripped so a lookup failure leaves the
    # member's existing franchise roles alone instead of orphaning them.
    agm_frole = await agm_franchise_role(guild, agm_franchise)
    if not agm_frole:
        log.error(
            f"Unable to find franchise role for AGM {member.display_name} ({member.id}) on {agm_franchise.name}. "
            "Leaving their existing franchise roles in place.",
            guild=guild,
        )
        return None

    if agm_frole not in member.roles and agm_frole not in roles_to_add:
        roles_to_add.append(agm_frole)

    # An AGM keeps the one franchise role the API gives them and loses every other.
    for r in await utils.franchise_role_list_from_disord_member(member):
        if r != agm_frole and r not in roles_to_remove:
            roles_to_remove.append(r)

    return agm_frole


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
    # Bulk remove/add to help avoid rate limit
    roles_to_remove: list[discord.Role] = []
    roles_to_add: list[discord.Role] = []

    is_agm = agm_franchise is not None

    await apply_agm_role_updates(
        guild=guild,
        member=member,
        agm_franchise=agm_franchise,
        roles_to_add=roles_to_add,
        roles_to_remove=roles_to_remove,
    )

    # Remove any old franchise role if it exists. The AGM case is handled above,
    # which keeps the one franchise role the API gives them.
    if not is_agm:
        roles_to_remove.extend(await utils.franchise_role_list_from_disord_member(member))

    for r in member.roles:
        # Find tier roles
        for tier in tiers:
            if r in roles_to_remove:
                continue

            if r.name.replace("FA", "").lower() == tier.name.lower():
                roles_to_remove.append(r)

        # All player roles
        match r.name:
            case const.LEAGUE_ROLE:
                # Don't remove league role if AGM. The add case is handled above
                # so that an AGM missing the role also gets it back.
                if not is_agm:
                    roles_to_remove.append(r)
            case const.FREE_AGENT_ROLE:
                roles_to_remove.append(r)
            case const.IR_ROLE:
                roles_to_remove.append(r)
            case const.PERM_FA_ROLE:
                roles_to_remove.append(r)
            case const.DRAFT_ELIGIBLE:
                roles_to_remove.append(r)
            # case const.DEV_LEAGUE_ROLE:
            #     roles_to_remove.append(r)
            case const.CAPTAIN_ROLE:
                roles_to_remove.append(r)
            case const.SUBBED_OUT_ROLE:
                roles_to_remove.append(r)
            case const.PERM_FA_WAITING_ROLE:
                roles_to_remove.append(r)

    # Default Roles
    if default_roles:
        for r in default_roles:
            if r not in member.roles:
                roles_to_add.append(r)  # noqa: PERF401

    # Remove Roles
    if roles_to_remove:
        log.debug(f"Removing roles ({member.id}): {roles_to_remove}", guild=guild)
        await member.remove_roles(*roles_to_remove)

    # Determine Former Player by prefix. An AGM keeps a franchise prefix as
    # staff, not as a leftover from playing, so it says nothing about them.
    if not is_agm and await utils.get_prefix(member):
        former_player_role = await utils.get_former_player_role(guild)
        if former_player_role not in member.roles:
            roles_to_add.append(former_player_role)

    # Update nickname
    if agm_franchise:
        # Restore the franchise prefix rather than merely leaving it alone: an
        # AGM whose prefix was stripped has no other path back to it.
        #
        # ValueError is swallowed alongside Forbidden because the roles above are
        # already written. `/transactions retire` does not wrap this call, so
        # letting a 32 character nickname raise would report the whole retire as
        # failed after the API mutation had gone through.
        try:
            log.debug(f"Restoring AGM prefix ({member.id}): {agm_franchise.prefix}", guild=guild)
            await utils.update_discord_name(
                member=member,
                name=agm_rsc_name(member, agm_franchise),
                prefix=agm_franchise.prefix,
            )
        except (discord.Forbidden, ValueError) as exc:
            log.error(f"Unable to restore AGM nickname {member.display_name} ({member.id}): {exc}", guild=guild)
    else:
        new_nick = await utils.remove_prefix(member)

        if new_nick != member.display_name:
            try:
                log.debug(f"Updating nickname ({member.id}): {new_nick}", guild=guild)

                if len(new_nick) > 32:
                    raise ValueError(f"Discord name is too long: {len(new_nick)} characters")

                if not new_nick or len(new_nick) < 1:
                    raise ValueError(f"Error changing name. Empty or <1 characters: {member.mention}")
                await member.edit(nick=new_nick)
            except discord.Forbidden as exc:
                log.warning(f"Unable to update nickname {member.display_name} ({member.id}): {exc}")

    # Add Roles
    if roles_to_add:
        log.debug(f"Adding Roles ({member.id}): {roles_to_add}", guild=guild)
        await member.add_roles(*roles_to_add)


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

    roles_to_remove: list[discord.Role] = []
    roles_to_add: list[discord.Role] = []

    # Remove old tier roles and tier FA role
    if tiers:
        for r in player.roles:
            for tier in tiers:
                if r in roles_to_remove:
                    continue

                if r.name.endswith("FA") or r.name.lower() == tier.name.lower():
                    roles_to_remove.append(r)

    # Remove Spectator
    spec_role = await utils.get_spectator_role(guild)
    if spec_role in player.roles:
        roles_to_remove.append(spec_role)

    # Remove Former Player
    former_role = await utils.get_former_player_role(guild)
    if former_role in player.roles:
        roles_to_remove.append(former_role)

    # PermFA role
    permfa_role = await utils.get_permfa_role(guild)
    if permfa_role in player.roles:
        roles_to_remove.append(permfa_role)

    # FA Role:
    fa_role = await utils.get_free_agent_role(guild)
    if fa_role in player.roles:
        roles_to_remove.append(fa_role)

    # Draft Eligible role
    de_role = await utils.get_draft_eligible_role(guild)
    if de_role in player.roles:
        roles_to_remove.append(de_role)

    # League Role
    league_role = await utils.get_league_role(guild)
    if league_role not in player.roles:
        roles_to_add.append(league_role)

    # Remove Captain
    captain_role = await utils.get_captain_role(guild)
    if captain_role in player.roles:
        roles_to_remove.append(captain_role)

    # A franchise's GM cannot also be one of its AGMs -- the API rejects it -- so
    # a leftover AGM role here is stale.
    agm_role = await utils.get_agm_role(guild)
    if agm_role in player.roles:
        roles_to_remove.append(agm_role)

    # Add franchise role
    frole = await utils.franchise_role_from_model(guild, franchise=franchise)
    if frole and frole not in player.roles:
        roles_to_add.append(frole)
    elif not frole:
        raise ValueError(f"New franchise role not found for {player.display_name} ({player.id})")

    # Remove any old franchise role if it exists
    old_froles = await utils.franchise_role_list_from_disord_member(player)
    if old_froles:
        # Don't remove current franchise if present
        if frole in old_froles:
            old_froles.remove(frole)
        roles_to_remove.extend(old_froles)

    # Update roles at same time to reduce API calls
    if roles_to_remove:
        log.debug(f"Removing roles: {roles_to_remove}", guild=guild)
        await player.remove_roles(*roles_to_remove)
    if roles_to_add:
        log.debug(f"Adding roles: {roles_to_add}", guild=guild)
        await player.add_roles(*roles_to_add)

    # Update player prefix
    try:
        log.debug(f"Changing {player.id} non-playing GM nick", guild=guild)
        if not franchise.gm.rsc_name:
            raise ValueError("Franchise GM has no name in API...")
        await utils.update_discord_name(member=player, name=franchise.gm.rsc_name, prefix=franchise.prefix)
    except discord.Forbidden as exc:
        log.warning(f"Unable to update nickname {player.display_name} ({player.id}): {exc}")


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

    roles_to_remove: list[discord.Role] = []
    roles_to_add: list[discord.Role] = []

    # Remove old tier roles and tier FA role
    if tiers:
        for r in player.roles:
            for tier in tiers:
                if r in roles_to_remove:
                    continue

                if r.name.endswith("FA") or (r.name.lower() == tier.name.lower() and r.name.lower() != league_player.tier.name.lower()):
                    roles_to_remove.append(r)

    # Remove Spectator
    spec_role = await utils.get_spectator_role(guild)
    if spec_role in player.roles:
        roles_to_remove.append(spec_role)

    # Remove Former Player
    former_role = await utils.get_former_player_role(guild)
    if former_role in player.roles:
        roles_to_remove.append(former_role)

    # PermFA role
    permfa_role = await utils.get_permfa_role(guild)
    if permfa_role in player.roles:
        roles_to_remove.append(permfa_role)

    # FA Role:
    fa_role = await utils.get_free_agent_role(guild)
    if fa_role in player.roles:
        roles_to_remove.append(fa_role)

    # Draft Eligible role
    de_role = await utils.get_draft_eligible_role(guild)
    if de_role in player.roles:
        roles_to_remove.append(de_role)

    # League Role
    league_role = await utils.get_league_role(guild)
    if league_role not in player.roles:
        roles_to_add.append(league_role)

    # Remove Captain
    captain_role = await utils.get_captain_role(guild)
    if captain_role in player.roles:
        roles_to_remove.append(captain_role)

    # IR Role
    ir_role = await utils.get_ir_role(guild)
    if ir_role in player.roles:
        roles_to_remove.append(ir_role)

    # Verify player has tier role
    tier_role = await utils.get_tier_role(guild, name=league_player.tier.name)
    if not tier_role:
        raise ValueError(f"Tier role not found: {league_player.tier.name}")

    if tier_role not in player.roles:
        roles_to_add.append(tier_role)

    # Add franchise role
    frole = await utils.franchise_role_from_model(guild, franchise=franchise)
    if frole and frole not in player.roles:
        # Add franchise role if it's not already there
        if frole not in player.roles:
            roles_to_add.append(frole)
    elif not frole:
        raise ValueError(f"New franchise role not found for {player.display_name} ({player.id})")

    # Remove any old franchise role if it exists
    old_froles = await utils.franchise_role_list_from_disord_member(player)
    if old_froles:
        # Don't remove current franchise if present
        if frole in old_froles:
            old_froles.remove(frole)
        roles_to_remove.extend(old_froles)

    # Update roles at same time to reduce API calls
    if roles_to_remove:
        log.debug(f"Removing roles: {roles_to_remove}", guild=guild)
        await player.remove_roles(*roles_to_remove)
    if roles_to_add:
        log.debug(f"Adding roles: {roles_to_add}", guild=guild)
        await player.add_roles(*roles_to_add)

    # Update player prefix
    try:
        await utils.update_discord_name(member=player, name=league_player.player.name, prefix=franchise.prefix)
    except discord.Forbidden as exc:
        log.warning(f"Unable to update nickname {player.display_name} ({player.id}): {exc}")


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

    # Do not sync dropped players
    if league_player.status == Status.DROPPED:
        return

    roles_to_remove: list[discord.Role] = []
    roles_to_add: list[discord.Role] = []

    # AGM role only. The roster owns the franchise role and the prefix here, so
    # a rostered AGM already has both -- but the AGM role itself still has to
    # track the API, since nothing else reconciles it for a rostered member.
    await apply_agm_role_updates(
        guild=guild,
        member=player,
        agm_franchise=agm_franchise,
        roles_to_add=roles_to_add,
        roles_to_remove=roles_to_remove,
        manage_franchise_roles=False,
    )

    # Remove old tier roles and tier FA role on discord.Member
    if tiers:
        for r in player.roles:
            for tier in tiers:
                if r in roles_to_remove:
                    continue

                if r.name.endswith("FA") or (r.name.lower() == tier.name.lower() and r.name.lower() != league_player.tier.name.lower()):
                    roles_to_remove.append(r)

    # Remove Spectator
    spec_role = await utils.get_spectator_role(guild)
    if spec_role in player.roles:
        roles_to_remove.append(spec_role)

    # Remove Former Player
    former_role = await utils.get_former_player_role(guild)
    if former_role in player.roles:
        roles_to_remove.append(former_role)

    # PermFA role
    permfa_role = await utils.get_permfa_role(guild)
    if permfa_role in player.roles:
        roles_to_remove.append(permfa_role)

    # IR
    #
    # `league_player.status`, not `player.status`: `player` is a discord.Member,
    # whose `status` is online/idle/offline and never equals a league Status. As
    # written before, the IR role was never added and always removed -- which hit
    # AGM IR members in particular.
    ir_role = await utils.get_ir_role(guild)
    if league_player.status in [Status.IR, Status.AGMIR] and ir_role not in player.roles:
        roles_to_add.append(ir_role)
    elif ir_role in player.roles:
        roles_to_remove.append(ir_role)

    # FA Role:
    fa_role = await utils.get_free_agent_role(guild)
    if fa_role in player.roles:
        roles_to_remove.append(fa_role)

    # Draft Eligible role
    de_role = await utils.get_draft_eligible_role(guild)
    if de_role in player.roles:
        roles_to_remove.append(de_role)

    # League Role
    league_role = await utils.get_league_role(guild)
    if league_role not in player.roles:
        roles_to_add.append(league_role)

    # Captain
    captain_role = await utils.get_captain_role(guild)
    if league_player.captain and captain_role not in player.roles:
        roles_to_add.append(captain_role)
    elif not league_player.captain and captain_role in player.roles:
        roles_to_remove.append(captain_role)

    # Add franchise role
    frole = await utils.franchise_role_from_league_player(guild, league_player)
    if frole and frole not in player.roles:
        # Add franchise role if it's not already there
        if frole not in player.roles:
            roles_to_add.append(frole)
    elif not frole:
        raise ValueError(f"New franchise role not found for {player.display_name} ({player.id})")

    # Remove any old franchise role if it exists
    old_froles = await utils.franchise_role_list_from_disord_member(player)
    if old_froles:
        # Don't remove current franchise if present
        if frole in old_froles:
            old_froles.remove(frole)
        roles_to_remove.extend(old_froles)

    # PermFA Waiting
    permfa_waiting_role = await utils.get_permfa_waiting_role(guild)
    if permfa_waiting_role in player.roles:
        roles_to_remove.append(permfa_waiting_role)

    # Verify player has tier role
    tier_role = await utils.get_tier_role(guild, name=league_player.tier.name)
    if tier_role and tier_role not in player.roles:
        roles_to_add.append(tier_role)

    # Update roles at same time to reduce API calls
    if roles_to_remove:
        log.debug(f"Removing roles: {roles_to_remove}", guild=guild)
        await player.remove_roles(*roles_to_remove)
    if roles_to_add:
        log.debug(f"Adding roles: {roles_to_add}", guild=guild)
        await player.add_roles(*roles_to_add)

    # Update player prefix
    try:
        await utils.update_discord_name(member=player, name=league_player.player.name, prefix=league_player.team.franchise.prefix)
    except discord.Forbidden as exc:
        log.warning(f"Unable to update nickname {player.display_name} ({player.id}): {exc}")


async def update_free_agent_discord(
    guild: discord.Guild, player: discord.Member, league_player: LeaguePlayer, tiers: list[Tier], devleague: bool = False
):
    if league_player.status not in (Status.FREE_AGENT, Status.PERM_FA, Status.WAIVERS, Status.WAIVER_RELEASE, Status.WAIVER_CLAIM):
        raise ValueError(f"{player.display_name} ({player.id}) is not a free agent.")

    if not league_player.tier:
        raise AttributeError(f"{player.display_name} ({player.id}) has no tier data.")

    roles_to_remove: list[discord.Role] = []
    roles_to_add: list[discord.Role] = []

    # Remove old tier roles and tier FA role on discord.Member
    if tiers:
        for r in player.roles:
            for tier in tiers:
                if r in roles_to_remove:
                    continue

                if (
                    r.name.replace("FA", "").lower() == tier.name.lower()
                    and r.name.replace("FA", "").lower() != league_player.tier.name.lower()
                ):
                    roles_to_remove.append(r)

    # Remove any old franchise role if it exists
    old_froles = await utils.franchise_role_list_from_disord_member(player)
    if old_froles:
        roles_to_remove.extend(old_froles)

    # Remove Spectator
    spec_role = await utils.get_spectator_role(guild)
    if spec_role in player.roles:
        roles_to_remove.append(spec_role)

    # Remove Former Player
    former_role = await utils.get_former_player_role(guild)
    if former_role in player.roles:
        roles_to_remove.append(former_role)

    # League Role:
    league_role = await utils.get_league_role(guild)
    if league_role not in player.roles:
        roles_to_add.append(league_role)

    # IR Role
    ir_role = await utils.get_ir_role(guild)
    if ir_role in player.roles:
        roles_to_remove.append(ir_role)

    # Remove captain
    captain_role = await utils.get_captain_role(guild)
    if captain_role in player.roles:
        roles_to_remove.append(captain_role)

    # Update tier role, handle promotion case
    tier_role = await utils.get_tier_role(guild, league_player.tier.name)
    if tier_role not in player.roles:
        roles_to_add.append(tier_role)

    # Free agent roles
    if league_player.status == Status.FREE_AGENT:
        fa_role = await utils.get_free_agent_role(guild)
        if fa_role not in player.roles:
            roles_to_add.append(fa_role)
    elif league_player.status == Status.PERM_FA:
        fa_role = await utils.get_permfa_role(guild)
        if fa_role not in player.roles:
            roles_to_add.append(fa_role)

    # Tier FA role
    tier_fa_role = await utils.get_tier_fa_role(guild, league_player.tier.name)
    if tier_fa_role not in player.roles:
        roles_to_add.append(tier_fa_role)

    # Dev League
    if devleague:
        dev_league_role = discord.utils.get(guild.roles, name=const.DEV_LEAGUE_ROLE)
        if dev_league_role and dev_league_role not in player.roles:
            roles_to_add.append(dev_league_role)

    # PermFA Waiting
    permfa_waiting_role = await utils.get_permfa_waiting_role(guild)
    if permfa_waiting_role in player.roles:
        roles_to_remove.append(permfa_waiting_role)

    if roles_to_remove:
        log.debug(f"Removing roles: {roles_to_remove}", guild=guild)
        await player.remove_roles(*roles_to_remove)
    if roles_to_add:
        log.debug(f"Adding roles: {roles_to_add}", guild=guild)
        await player.add_roles(*roles_to_add)

    try:
        if league_player.status in [Status.FREE_AGENT, Status.WAIVERS, Status.WAIVER_RELEASE, Status.WAIVER_CLAIM]:
            await utils.update_discord_name(member=player, name=league_player.player.name, prefix="FA")
        elif league_player.status == Status.PERM_FA:
            await utils.update_discord_name(member=player, name=league_player.player.name, prefix="PFA")
    except discord.Forbidden as exc:
        log.warning(f"Unable to update nickname {player.display_name} ({player.id}): {exc}")


async def update_draft_eligible_discord(
    guild: discord.Guild,
    player: discord.Member,
    league_player: LeaguePlayer,
    tiers: list[Tier],
    devleague: bool = False,
):
    if league_player.status != Status.DRAFT_ELIGIBLE:
        raise ValueError(f"{player.display_name} ({player.id}) is not draft eligible.")

    roles_to_remove: list[discord.Role] = []
    roles_to_add: list[discord.Role] = []

    # Remove old tier roles and tier FA role on discord.Member
    if tiers and league_player.tier and league_player.tier.name:
        for r in player.roles:
            for tier in tiers:
                if r in roles_to_remove:
                    continue

                if r.name.replace("FA", "").lower() == tier.name.lower() and r.name.lower() != league_player.tier.name.lower():
                    roles_to_remove.append(r)
    elif tiers:
        log.warning(f"{player.display_name} ({player.id}) has no tier data.", guild=guild)
        for r in player.roles:
            for tier in tiers:
                if r.name.replace("FA", "").lower() == tier.name.lower():
                    roles_to_remove.append(r)  # noqa: PERF401

    # Remove any old franchise role if it exists
    old_froles = await utils.franchise_role_list_from_disord_member(player)
    if old_froles:
        roles_to_remove.extend(old_froles)

    # Remove Spectator
    spec_role = await utils.get_spectator_role(guild)
    if spec_role in player.roles:
        roles_to_remove.append(spec_role)

    # Remove Former Player
    former_role = await utils.get_former_player_role(guild)
    if former_role in player.roles:
        roles_to_remove.append(former_role)

    # League Role:
    league_role = await utils.get_league_role(guild)
    if league_role not in player.roles:
        roles_to_add.append(league_role)

    # PermFA Role:
    permfa_role = await utils.get_permfa_role(guild)
    if permfa_role in player.roles:
        roles_to_remove.append(permfa_role)

    # Remove captain
    captain_role = await utils.get_captain_role(guild)
    if captain_role in player.roles:
        roles_to_remove.append(captain_role)

    # Update tier role, handle promotion case
    if league_player.tier and league_player.tier.name:
        tier_role = await utils.get_tier_role(guild, league_player.tier.name)
        if tier_role not in player.roles:
            roles_to_add.append(tier_role)

    # IR Role
    ir_role = await utils.get_ir_role(guild)
    if ir_role in player.roles:
        roles_to_remove.append(ir_role)

    # Free agent roles
    fa_role = await utils.get_free_agent_role(guild)
    if fa_role in player.roles:
        roles_to_remove.append(fa_role)

    # Draft Eligible
    de_role = await utils.get_draft_eligible_role(guild)
    if de_role not in player.roles:
        roles_to_add.append(de_role)

    # Dev League
    if devleague:
        dev_league_role = discord.utils.get(guild.roles, name=const.DEV_LEAGUE_ROLE)
        if dev_league_role and dev_league_role not in player.roles:
            roles_to_add.append(dev_league_role)

    if roles_to_remove:
        log.debug(f"Removing roles: {roles_to_remove}", guild=guild)
        await player.remove_roles(*roles_to_remove)
    if roles_to_add:
        log.debug(f"Adding roles: {roles_to_add}", guild=guild)
        await player.add_roles(*roles_to_add)

    try:
        await utils.update_discord_name(member=player, name=league_player.player.name, prefix="DE")
    except discord.Forbidden as exc:
        log.warning(f"Unable to update nickname {player.display_name} ({player.id}): {exc}")


async def update_permfa_waiting_discord(
    guild: discord.Guild,
    player: discord.Member,
    league_player: LeaguePlayer,
    tiers: list[Tier],
):
    if league_player.status != Status.PERMFA_W:
        raise ValueError(f"{player.display_name} ({player.id}) is not a permfa in waiting...")

    roles_to_remove: list[discord.Role] = []
    roles_to_add: list[discord.Role] = []

    # PermFA waiting should have no tier roles yet
    if tiers:
        for r in player.roles:
            for tier in tiers:
                if r in roles_to_remove:
                    continue

                if r.name.replace("FA", "").lower() == tier.name.lower():
                    roles_to_remove.append(r)

    # Remove any old franchise role if it exists
    old_froles = await utils.franchise_role_list_from_disord_member(player)
    if old_froles:
        roles_to_remove.extend(old_froles)

    # Remove Spectator
    spec_role = await utils.get_spectator_role(guild)
    if spec_role in player.roles:
        roles_to_remove.append(spec_role)

    # Remove Former Player
    former_role = await utils.get_former_player_role(guild)
    if former_role in player.roles:
        roles_to_remove.append(former_role)

    # League Role:
    league_role = await utils.get_league_role(guild)
    if league_role not in player.roles:
        roles_to_add.append(league_role)

    # IR Role
    ir_role = await utils.get_ir_role(guild)
    if ir_role in player.roles:
        roles_to_remove.append(ir_role)

    # Remove captain
    captain_role = await utils.get_captain_role(guild)
    if captain_role in player.roles:
        roles_to_remove.append(captain_role)

    # Free agent roles
    fa_role = await utils.get_free_agent_role(guild)
    if fa_role in player.roles:
        roles_to_remove.append(fa_role)

    # Draft Eligible
    de_role = await utils.get_draft_eligible_role(guild)
    if de_role in player.roles:
        roles_to_remove.append(de_role)

    # PermFA role:
    permfa_role = await utils.get_permfa_role(guild)
    if permfa_role in player.roles:
        roles_to_remove.append(permfa_role)

    # Add PermFA Waiting role
    permfa_waiting_role = await utils.get_permfa_waiting_role(guild)
    if permfa_waiting_role not in player.roles:
        roles_to_add.append(permfa_waiting_role)

    if roles_to_remove:
        log.debug(f"Removing roles: {roles_to_remove}", guild=guild)
        await player.remove_roles(*roles_to_remove)
    if roles_to_add:
        log.debug(f"Adding roles: {roles_to_add}", guild=guild)
        await player.add_roles(*roles_to_add)

    try:
        await utils.update_discord_name(member=player, name=league_player.player.name, prefix="PFW")
    except discord.Forbidden as exc:
        log.warning(f"Unable to update nickname {player.display_name} ({player.id}): {exc}")


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

    # An AGM cannot be a free agent or draft eligible -- they sign with the
    # franchise they staff or they do not play. Reaching here means the API's
    # two records disagree, and following either one silently would hide it.
    if agm_franchise and league_player.status in (
        Status.FREE_AGENT,
        Status.PERM_FA,
        Status.PERMFA_W,
        Status.DRAFT_ELIGIBLE,
        Status.WAIVERS,
        Status.WAIVER_RELEASE,
        Status.WAIVER_CLAIM,
    ):
        log.warning(
            f"{player.display_name} ({player.id}) is an AGM of {agm_franchise.name} but has league player status "
            f"{league_player.status}. Syncing by status; the API records need to be reconciled by hand.",
            guild=guild,
        )

    match league_player.status:
        case Status.ROSTERED | Status.RENEWED | Status.AGMIR | Status.IR:
            return await update_rostered_discord(
                guild=guild, player=player, league_player=league_player, tiers=tiers, agm_franchise=agm_franchise
            )
        case Status.DRAFT_ELIGIBLE:
            return await update_draft_eligible_discord(
                guild=guild, player=player, league_player=league_player, tiers=tiers, devleague=devleague
            )
        case Status.FREE_AGENT | Status.PERM_FA | Status.WAIVERS | Status.WAIVER_RELEASE | Status.WAIVER_CLAIM:
            return await update_free_agent_discord(
                guild=guild, player=player, league_player=league_player, tiers=tiers, devleague=devleague
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
            return await update_permfa_waiting_discord(guild=guild, player=player, league_player=league_player, tiers=tiers)
        case _:
            raise ValueError(f"**{league_player.status}** is not currently supported.")
