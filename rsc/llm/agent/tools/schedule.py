"""Match, schedule and standings tools.

Nothing here is cacheable: schedules and results move within a day, and a stale
match result is worse than a slow one.
"""

from typing import Any

from rsc.llm.agent.context import AgentContext
from rsc.llm.agent.format import fields, format_date, name_of, table
from rsc.llm.agent.registry import tool


@tool(
    "get_schedule",
    "Matches for a team, or the league schedule for a match day. Includes results for matches "
    "already played. Use this for 'when do I play next' and 'who did X play'.",
    properties={
        "team": {"type": "string", "description": "Team name. Omit for the whole league."},
        "day": {"type": "integer", "description": "Match day number."},
        "next_only": {"type": "boolean", "description": "Only the team's next upcoming match."},
        "limit": {"type": "integer", "description": "Max rows (default 10, max 25)."},
    },
)
async def get_schedule(
    ctx: AgentContext,
    team: str | None = None,
    day: int | None = None,
    next_only: bool = False,
    limit: int = 10,
) -> str:
    limit = max(1, min(int(limit), 25))

    if next_only:
        if not team:
            return "ERROR: next_only requires a team."
        team_id = await ctx.cog.team_id_by_name(ctx.guild, team)
        match: Any = await ctx.cog.next_match(ctx.guild, team_id)
        if match is None:
            return f"{team} has no upcoming match scheduled."
        return fields(
            {
                "Match day": match.day,
                "Date": format_date(match.var_date),
                "Home": name_of(match.home_team),
                "Away": name_of(match.away_team),
                "Format": match.match_format,
            }
        )

    if team:
        team_id = await ctx.cog.team_id_by_name(ctx.guild, team)
        matches = await ctx.cog.season_matches(ctx.guild, team_id)
    else:
        await ctx.resolve_season()
        matches = await ctx.cog.matches(ctx.guild, day=day, season_number=ctx.season_number, limit=limit)

    rows = []
    for match in list(matches)[:limit]:
        home, away = name_of(match.home_team), name_of(match.away_team)
        result = ""
        home_wins = getattr(match, "home_wins", None)
        away_wins = getattr(match, "away_wins", None)
        if home_wins is not None and away_wins is not None:
            result = f" | {home_wins}-{away_wins}"
        rows.append(f"Day {match.day} | {format_date(getattr(match, 'var_date', None))} | {home} vs {away}{result}")

    header = f"SCHEDULE{f' for {team}' if team else ''}\nDAY | DATE | MATCHUP | RESULT"
    return table(header, rows)


@tool(
    "get_standings",
    "Standings, either for a tier (team by team) or across franchises.",
    properties={
        "scope": {
            "type": "string",
            "enum": ["tier", "franchise"],
            "description": "Rank teams within a tier, or franchises league-wide.",
        },
        "tier": {"type": "string", "description": "Tier name. Required when scope is 'tier'."},
    },
    required=["scope"],
)
async def get_standings(ctx: AgentContext, scope: str, tier: str | None = None) -> str:
    await ctx.resolve_season()

    if scope == "franchise":
        if ctx.season_id is None:
            return "ERROR: no current season."
        # Franchise standings key off the season *id*; tier standings take the
        # season *number*. Mixing them returns an empty list, not an error.
        standings = await ctx.cog.franchise_standings(ctx.guild, ctx.season_id)
        rows = [f"{s.franchise_standings_rank} | {name_of(s.franchise)} | {s.wins}-{s.losses} | {s.win_percentage}" for s in standings]
        return table("FRANCHISE STANDINGS\nRANK | FRANCHISE | W-L | WIN%", rows)

    if not tier:
        return "ERROR: scope 'tier' requires a tier name."
    if ctx.season_number is None:
        return "ERROR: no current season."
    tier_id = await ctx.cog.tier_id_by_name(ctx.guild, tier)
    standings = await ctx.cog.tier_standings(ctx.guild, tier_id, ctx.season_number)
    rows = [f"{s.rank} | {name_of(s.team)} | {name_of(s.franchise)} | {s.games_won}-{s.games_lost}" for s in standings]
    return table(f"{tier} STANDINGS\nRANK | TEAM | FRANCHISE | W-L", rows)


@tool(
    "get_transactions",
    "Recent league transactions (signings, cuts, trades, subs), newest first.",
    properties={
        "player": {"type": "string", "description": "Filter to one player's RSC name."},
        "limit": {"type": "integer", "description": "Max rows (default 10, max 20)."},
    },
)
async def get_transactions(ctx: AgentContext, player: str | None = None, limit: int = 10) -> str:
    limit = max(1, min(int(limit), 20))

    member = None
    if player:
        # `transaction_history` filters by discord.Member, so resolve the RSC
        # name to a guild member first.
        players = await ctx.cog.players(ctx.guild, name=player, limit=1)
        if not players:
            return f"No player found matching {player!r}."
        discord_id = getattr(players[0].player, "discord_id", None)
        member = ctx.guild.get_member(discord_id) if discord_id else None
        if member is None:
            return f"{player} is not currently in this Discord server."

    history = await ctx.cog.transaction_history(ctx.guild, player=member, limit=limit)
    rows = []
    for entry in history:
        first = name_of(entry.first_franchise)
        second = name_of(entry.second_franchise)
        move = f"{first} -> {second}" if second else first
        rows.append(f"{format_date(entry.var_date)} | {entry.type} | {move}")
    return table("DATE | TYPE | FRANCHISES", rows)
