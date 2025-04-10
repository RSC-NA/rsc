import asyncio
import logging

import ballchasing
import discord
from rscapi.models import Match

from rsc.enums import MatchType, PostSeasonType
from rsc.logs import GuildLogAdapter

logger = logging.getLogger("red.rsc.ballchasing.groups")
log = GuildLogAdapter(logger)


async def purge_ballchasing_group(bapi: ballchasing.Api, guild: discord.Guild, group: str):
    """Remove all replays from a ballchasing group (CAUTION: DESTRUCTIVE)"""
    try:
        async with asyncio.TaskGroup() as tg:
            async for replay in bapi.get_group_replays(group_id=group, deep=False, recurse=False):
                log.debug(f"Deleting replay: {replay.id}", guild=guild)
                tg.create_task(bapi.delete_replay(replay.id))
    except ExceptionGroup as eg:
        for err in eg.exceptions:
            raise err


async def season_bc_group(bapi: ballchasing.Api, guild: discord.Guild, tlg: str, match: Match) -> str | None:
    """Get season group ID and or create it"""
    sname = f"Season {match.home_team.latest_season}"
    season_group = None

    # Find relevant season group
    async for g in bapi.get_groups(group=tlg):
        if g.name.lower() == sname.lower():
            log.debug(f"Found existing ballchasing season group: {g.id}", guild=guild)
            season_group = g.id
            break

    # Create group if not found
    if not season_group:
        log.debug(f"Creating ballchasing season group: {sname}", guild=guild)
        result = await bapi.create_group(
            name=sname,
            parent=tlg,
            player_identification=ballchasing.PlayerIdentificationBy.ID,
            team_identification=ballchasing.TeamIdentificationBy.CLUSTERS,
        )
        season_group = result.id
    return season_group


async def match_type_group(bapi: ballchasing.Api, guild: discord.Guild, tlg: str, match: Match) -> str | None:
    """Get tier group ID and or create it"""
    season_group = await season_bc_group(bapi=bapi, guild=guild, tlg=tlg, match=match)
    if not season_group:
        return None

    if not match.match_type:
        raise ValueError("API match does not have a match type (Ex: Regular Season)")

    tname = MatchType(match.match_type).full_name
    match_type_group = None

    # Find relevant server group
    async for g in bapi.get_groups(group=season_group):
        if g.name.lower() == tname.lower():
            log.debug(f"Found existing ballchasing match type group: {g.id}", guild=guild)
            match_type_group = g.id
            break

    # Create group if not found
    if not match_type_group:
        log.debug(f"Creating ballchasing match type group: {tname}", guild=guild)
        result = await bapi.create_group(
            name=tname,
            parent=season_group,
            player_identification=ballchasing.PlayerIdentificationBy.ID,
            team_identification=ballchasing.TeamIdentificationBy.CLUSTERS,
        )
        match_type_group = result.id
    return match_type_group


async def tier_bc_group(bapi: ballchasing.Api, guild: discord.Guild, tlg: str, match: Match) -> str | None:
    """Get tier group ID and or create it"""
    mtype_group = await match_type_group(bapi=bapi, guild=guild, tlg=tlg, match=match)
    if not mtype_group:
        return None

    tname = match.home_team.tier
    tier_group = None

    # Find relevant server group
    async for g in bapi.get_groups(group=mtype_group):
        if g.name.lower() == tname.lower():
            log.debug(f"Found existing ballchasing tier group: {g.id}", guild=guild)
            tier_group = g.id
            break

    # Create group if not found
    if not tier_group:
        log.debug(f"Creating ballchasing tier group: {tname}", guild=guild)
        result = await bapi.create_group(
            name=tname,
            parent=mtype_group,
            player_identification=ballchasing.PlayerIdentificationBy.ID,
            team_identification=ballchasing.TeamIdentificationBy.CLUSTERS,
        )
        tier_group = result.id
    return tier_group


async def match_day_bc_group(bapi: ballchasing.Api, guild: discord.Guild, tlg: str, match: Match) -> str | None:
    """Get match group ID and or create it"""
    tier_group = await tier_bc_group(bapi=bapi, guild=guild, tlg=tlg, match=match)
    if not tier_group:
        return None

    if not match.match_type:
        raise ValueError("API match does not have a match type (Ex: Regular Season)")

    if not match.day:
        raise ValueError("API match does not have a match day value")

    if match.match_type == MatchType.POSTSEASON:
        playoff_round = PostSeasonType(match.day)
        mdname = playoff_round.name.capitalize()
    else:
        mdname = f"Match Day {match.day:02d}"

    # Find relevant server group
    md_group = None
    async for g in bapi.get_groups(group=tier_group):
        if g.name.lower() == mdname.lower():
            log.debug(f"Found existing ballchasing match day group: {g.id}", guild=guild)
            md_group = g.id
            break

    # Create group if not found
    if not md_group:
        log.debug(f"Creating match day ballchasing group: {mdname}", guild=guild)
        result = await bapi.create_group(
            name=mdname,
            parent=tier_group,
            player_identification=ballchasing.PlayerIdentificationBy.ID,
            team_identification=ballchasing.TeamIdentificationBy.CLUSTERS,
        )
        md_group = result.id
    return md_group


async def rsc_match_bc_group(bapi: ballchasing.Api, guild: discord.Guild, tlg: str, match: Match) -> str | None:
    """Get match group ID and or create it starting with top level group (tlg)"""
    md_group = await match_day_bc_group(bapi=bapi, guild=guild, tlg=tlg, match=match)
    if not md_group:
        return None

    mname = f"{match.home_team.name} vs {match.away_team.name}"
    match_group = None

    # Find relevant server group
    async for g in bapi.get_groups(group=md_group):
        if g.name.lower() == mname.lower():
            log.debug(f"Found existing ballchasing match group: {g.id}", guild=guild)
            match_group = g.id
            break

    # Create group if not found
    if not match_group:
        log.debug(f"Creating match ballchasing group: {mname}", guild=guild)
        result = await bapi.create_group(
            name=mname,
            parent=md_group,
            player_identification=ballchasing.PlayerIdentificationBy.ID,
            team_identification=ballchasing.TeamIdentificationBy.CLUSTERS,
        )
        match_group = result.id
    return match_group
