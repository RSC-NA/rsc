import logging

import discord
from rscapi.models.player import Player
from rscapi.models.player_transaction_updates import PlayerTransactionUpdates
from rscapi.models.tier import Tier
from rscapi.models.transaction_response import TransactionResponse

from rsc import const
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
        raise AttributeError(
            f"PlayerTransactionUpdate object has no new team data for signed player: {player.display_name} ({player.id})"
        )

    if not ptu.new_team.tier:
        raise AttributeError(f"{ptu.new_team.name} has no tier data.")

    if not ptu.player.team:
        raise AttributeError(f"{player.display_name} ({player.id}) has no team data.")

    if not ptu.player.team.franchise:
        raise AttributeError(
            f"{player.display_name} ({player.id}) has no franchise data."
        )

    # Remove old tier roles and tier FA role on discord.Member
    if tiers:
        for r in player.roles:
            for tier in tiers:
                if r.name.replace("FA", "").lower() == tier.name.lower():
                    log.debug(f"Removing role: {r.name}", guild=guild)
                    await player.remove_roles(r)

    # FA Role:
    log.debug(f"Removing FA roles from {player.id}", guild=guild)
    log.debug(f"Player Tier: {ptu.player.tier.name}", guild=guild)
    fa_role = await utils.get_free_agent_role(guild)
    await player.remove_roles(fa_role)

    # Remove old franchise role if it exists
    old_frole = await utils.franchise_role_from_disord_member(player)
    if old_frole:
        await player.remove_roles(old_frole)

    # Add franchise role
    frole = await utils.franchise_role_from_league_player(guild, ptu.player)
    log.debug(f"Adding franchise role to {player.id}: {frole.name}", guild=guild)

    # Verify player has tier role
    tier_role = await utils.get_tier_role(guild, name=ptu.new_team.tier)
    log.debug(f"Adding tier role to {player.id}: {tier_role.name}", guild=guild)
    await player.add_roles(frole, tier_role)

    # Update player prefix
    new_nick = (
        f"{ptu.player.team.franchise.prefix} | {await utils.remove_prefix(player)}"
    )
    log.debug(f"Changing {player.id} signed player nick: {new_nick}", guild=guild)
    try:
        await player.edit(nick=new_nick)
    except discord.Forbidden as exc:
        log.warning(
            f"Unable to update nickname {player.display_name} ({player.id}): {exc}"
        )


async def update_cut_player_discord(
    guild: discord.Guild,
    player: discord.Member,
    response: TransactionResponse,
    ptu: PlayerTransactionUpdates,
):
    if not ptu.old_team:
        raise AttributeError(
            f"{player.display_name} ({player.id}) has no old team data."
        )

    if not ptu.old_team.tier:
        raise AttributeError(
            f"{player.display_name} ({player.id}) has no old team tier data."
        )

    if not ptu.player.tier:
        raise AttributeError(f"{player.display_name} ({player.id}) has no tier data.")

    if not response.first_franchise:
        raise AttributeError(
            f"{player.display_name} ({player.id}) has first franchise data."
        )

    roles_to_remove: list[discord.Role] = []
    roles_to_add: list[discord.Role] = []

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
    roles_to_add.append(fa_role)
    roles_to_add.append(tier_fa_role)

    # Franchise Role
    franchise_role = await utils.franchise_role_from_name(
        guild, response.first_franchise.name
    )
    if not franchise_role:
        log.error(
            f"Unable to find franchise name during cut: {response.first_franchise.name}",
            guild=guild,
        )
        raise ValueError(
            f"Unable to find franchise role for **{response.first_franchise.name}**"
        )

    # Make changes for Non-GM player
    if response.first_franchise.gm.discord_id != player.id:
        new_nick = f"FA | {await utils.remove_prefix(player)}"
        roles_to_remove.append(franchise_role)

        # Add Dev League Interest if it exists
        dev_league_role = discord.utils.get(guild.roles, name=const.DEV_LEAGUE_ROLE)
        if dev_league_role:
            roles_to_add.append(dev_league_role)
    else:
        new_nick = player.display_name
        roles_to_add.remove(fa_role)
        roles_to_add.remove(tier_fa_role)

    log.debug(f"Removing cut player roles: {roles_to_remove}", guild=guild)
    await player.remove_roles(*roles_to_remove)
    log.debug(f"Adding cut player roles: {roles_to_add}", guild=guild)
    await player.add_roles(*roles_to_add)

    log.debug(f"Updating cut player nickname: {new_nick}", guild=guild)
    try:
        await player.edit(nick=new_nick)
    except discord.Forbidden as exc:
        log.warning(
            f"Unable to update nickname {player.display_name} ({player.id}): {exc}"
        )


async def update_team_captain_discord(
    guild: discord.Guild,
    players: list[Player],
):
    cpt_role = await utils.get_captain_role(guild)

    for p in players:
        m = guild.get_member(p.discord_id)
        if not m:
            log.error(
                f"Unable to find rostered player in guild: {p.discord_id}", guild=guild
            )
            continue

        if p.captain:
            log.debug(f"Adding captain role: {m.display_name} ({m.id})", guild=guild)
            if cpt_role not in m.roles:
                await m.add_roles(cpt_role)
        else:
            log.debug(f"Removing captain role: {m.display_name} ({m.id})", guild=guild)
            await m.remove_roles(cpt_role)


async def update_nonplaying_discord(
    guild: discord.Guild, member: discord.Member, tiers: list[Tier]
):
    former_player_role = await utils.get_former_player_role(guild)
    spectator_role = await utils.get_spectator_role(guild)

    # Bulk remove/add to help avoid rate limit
    roles_to_remove: list[discord.Role] = []
    roles_to_add: list[discord.Role] = []

    # Franchise Role
    frole = await utils.franchise_role_from_disord_member(member)
    if frole:
        roles_to_remove.append(frole)

    # Find applicable roles
    for r in member.roles:
        # Tiers
        for tier in tiers:
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

    if spectator_role not in member.roles:
        roles_to_add.append(spectator_role)

    # Remove Roles
    if roles_to_remove:
        log.debug(f"Removing roles: {roles_to_remove}", guild=guild)
        await member.remove_roles(*roles_to_remove)

    # Determine Former Player by prefix
    if await utils.get_prefix(member):
        if former_player_role not in member.roles:
            roles_to_add.append(former_player_role)
        new_nick = await utils.remove_prefix(member)
        log.debug(f"Updating nickname: {new_nick}", guild=guild)
        try:
            await member.edit(nick=new_nick)
        except discord.Forbidden as exc:
            log.warning(
                f"Unable to update nickname {member.display_name} ({member.id}): {exc}"
            )

    # Add Roles
    if roles_to_remove:
        log.debug(f"Adding Roles: {roles_to_add}", guild=guild)
        await member.add_roles(*roles_to_add)
