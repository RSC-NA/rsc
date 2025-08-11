import logging

import discord
from rscapi.models.franchise import Franchise
from rscapi.models.franchise_list import FranchiseList
from rscapi.models.league_player import LeaguePlayer
from rscapi.models.player import Player
from rscapi.models.player_transaction_updates import PlayerTransactionUpdates
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
        log.debug(f"Adding roles: {roles_to_remove}", guild=guild)
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
    is_gm = response.first_franchise.gm.discord_id != player.id
    if not is_gm:
        roles_to_remove.append(franchise_role)

        # Add Dev League Interest if it exists
        dev_league_role = discord.utils.get(guild.roles, name=const.DEV_LEAGUE_ROLE)
        if dev_league_role and dev_league_role not in player.roles:
            roles_to_add.append(dev_league_role)
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
    players: list[Player],
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


async def update_nonplaying_discord(
    guild: discord.Guild,
    member: discord.Member,
    tiers: list[Tier],
    default_roles: list[discord.Role] | None = None,
):
    # Bulk remove/add to help avoid rate limit
    roles_to_remove: list[discord.Role] = []
    roles_to_add: list[discord.Role] = []

    # Remove any old franchise role if it exists
    old_froles = await utils.franchise_role_list_from_disord_member(member)
    if old_froles:
        roles_to_remove.extend(old_froles)

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
                roles_to_remove.append(r)
            case const.FREE_AGENT_ROLE:
                roles_to_remove.append(r)
            case const.IR_ROLE:
                roles_to_remove.append(r)
            case const.PERM_FA_ROLE:
                roles_to_remove.append(r)
            case const.DRAFT_ELIGIBLE:
                roles_to_remove.append(r)
            case const.DEV_LEAGUE_ROLE:
                roles_to_remove.append(r)
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

    # Determine Former Player by prefix
    if await utils.get_prefix(member):
        former_player_role = await utils.get_former_player_role(guild)
        if former_player_role not in member.roles:
            roles_to_add.append(former_player_role)

    # Update nickname
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
    ir_role = await utils.get_ir_role(guild)
    if player.status in [Status.IR, Status.AGMIR] and ir_role not in player.roles:
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
    guild: discord.Guild,
    player: discord.Member,
    league_player: LeaguePlayer,
    tiers: list[Tier],
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
):
    if not tiers:
        tiers = []

    if not league_player:
        return await update_nonplaying_discord(guild=guild, member=player, tiers=tiers, default_roles=default_roles)

    if not league_player.status:
        raise ValueError("API returned league player with no status value")

    match league_player.status:
        case Status.ROSTERED | Status.RENEWED | Status.AGMIR | Status.IR:
            return await update_rostered_discord(guild=guild, player=player, league_player=league_player, tiers=tiers)
        case Status.DRAFT_ELIGIBLE:
            return await update_draft_eligible_discord(guild=guild, player=player, league_player=league_player, tiers=tiers)
        case Status.FREE_AGENT | Status.PERM_FA | Status.WAIVERS | Status.WAIVER_RELEASE | Status.WAIVER_CLAIM:
            return await update_free_agent_discord(guild=guild, player=player, league_player=league_player, tiers=tiers)
        case Status.UNSIGNED_GM:
            if not franchise:
                raise ValueError("Must provide franchise data to sync un-signed GM")
            return await update_unsigned_gm_discord(
                guild=guild, player=player, league_player=league_player, franchise=franchise, tiers=tiers
            )
        case Status.DROPPED | Status.FORMER | Status.BANNED:
            return await update_nonplaying_discord(guild=guild, member=player, tiers=tiers, default_roles=default_roles)
        case Status.PERMFA_W:
            return await update_permfa_waiting_discord(guild=guild, player=player, league_player=league_player, tiers=tiers)
        case _:
            raise ValueError(f"**{league_player.status}** is not currently supported.")
