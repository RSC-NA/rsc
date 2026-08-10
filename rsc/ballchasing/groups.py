import asyncio
import logging

import ballchasing
import discord
from rscapi.models import Match

from rsc.enums import MatchType, PostSeasonType
from rsc.logs import GuildLogAdapter

logger = logging.getLogger("red.rsc.ballchasing.groups")
log = GuildLogAdapter(logger)

# (parent group id, casefolded group name) -> group id
GroupCache = dict[tuple[str, str], str]


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


def match_day_name(match: Match) -> str:
    """Ballchasing group name for a match's match day."""
    if match.match_type is None:
        raise ValueError("API match does not have a match type (Ex: Regular Season)")

    # Match day 0 is valid. PostSeasonType.PLAYOFF is 0 and regular season
    # schedules have used day 0 as a placeholder, so only None is an error.
    if match.day is None:
        raise ValueError("API match does not have a match day value")

    if match.match_type == MatchType.POSTSEASON:
        return PostSeasonType(match.day).name.capitalize()
    return f"Match Day {match.day:02d}"


async def find_or_create_group(
    bapi: ballchasing.Api,
    *,
    name: str,
    parent: str,
    cache: GroupCache | None = None,
    guild: discord.Guild | None = None,
) -> str:
    """Resolve a ballchasing group by name under `parent`, creating it if absent.

    Callers must serialize this against themselves per guild. Ballchasing has no
    atomic find-or-create, so two concurrent callers would both miss the lookup
    and create duplicate identically named siblings.
    """
    key = (parent, name.casefold())
    if cache is not None:
        cached = cache.get(key)
        if cached:
            return cached

    # Narrow the listing server side. The filter's matching semantics are not
    # documented, so the exact comparison below is what actually decides.
    group_id = await _search_children(bapi, parent=parent, name=name, server_filter=True)

    if not group_id:
        # The name filter may be exact and case sensitive. Before creating a
        # duplicate, pay for one unfiltered listing and compare ourselves.
        group_id = await _search_children(bapi, parent=parent, name=name, server_filter=False)

    if group_id:
        log.debug(f"Found existing ballchasing group '{name}': {group_id}", guild=guild)
    else:
        log.debug(f"Creating ballchasing group: {name}", guild=guild)
        result = await bapi.create_group(
            name=name,
            parent=parent,
            player_identification=ballchasing.PlayerIdentificationBy.ID,
            team_identification=ballchasing.TeamIdentificationBy.CLUSTERS,
        )
        group_id = result.id

    if cache is not None:
        cache[key] = group_id
    return group_id


async def _search_children(bapi: ballchasing.Api, parent: str, name: str, server_filter: bool) -> str | None:
    target = name.casefold()
    async for g in bapi.get_groups(group=parent, name=name if server_filter else None):
        if g.name.casefold() == target:
            return g.id
    return None


async def rsc_match_bc_group(
    bapi: ballchasing.Api,
    guild: discord.Guild,
    tlg: str,
    match: Match,
    cache: GroupCache | None = None,
) -> str:
    """Resolve the ballchasing group for a match, creating the ladder as needed.

    Ladder: top level group -> season -> match type -> tier -> match day -> match.
    Callers must hold the guild's group lock.
    """
    # Already reported. The API stores the group we used, so there is nothing to
    # look up and nothing to race.
    if match.results and (existing := (match.results.ballchasing_group or "").strip()):
        log.debug(f"Reusing reported ballchasing group: {existing}", guild=guild, match=match)
        return existing

    if not match.home_team.tier:
        raise ValueError("API match does not have tier information for home team")

    if match.match_type is None:
        raise ValueError("API match does not have a match type (Ex: Regular Season)")

    names = [
        f"Season {match.home_team.latest_season}",
        MatchType(match.match_type).full_name,
        match.home_team.tier,
        match_day_name(match),
        f"{match.home_team.name} vs {match.away_team.name}",
    ]

    group = tlg
    for name in names:
        group = await find_or_create_group(bapi, name=name, parent=group, cache=cache, guild=guild)

    log.debug(f"Resulting match group ID: {group}", guild=guild, match=match)
    return group
