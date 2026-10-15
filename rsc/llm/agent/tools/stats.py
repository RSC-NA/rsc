"""Player and team statistics, including leaderboards.

The leaderboard tools are the reason this file exists. Making the model fetch
every roster and compare them would cost tens of thousands of tokens and get the
arithmetic wrong; the API already returns per-tier stats with server-computed
ranks, so ranking happens here and the model sees fifteen rows.
"""

from typing import Any

from rsc.llm.agent.context import AgentContext
from rsc.llm.agent.format import fields, name_of, table
from rsc.llm.agent.registry import tool

# Stat name -> (record attribute, server-computed rank attribute).
# Only stats the API ranks are offered, so `top_players` never has to fall back
# to sorting a full-league fetch itself.
RANKED_STATS: dict[str, tuple[str, str]] = {
    "goals": ("goals", "goals_rank"),
    "assists": ("assists", "assists_rank"),
    "saves": ("saves", "saves_rank"),
    "shots": ("shots", "shots_rank"),
    "points": ("points", "points_rank"),
    "mvps": ("mvps", "mvps_rank"),
    "demos": ("demos_inflicted", "demos_inflicted_rank"),
    "bpm": ("bpm", "bpm_rank"),
}

# Name the model sees -> record attribute. The names are the league's wording;
# the API calls wins and losses `games_won` / `games_lost`.
PLAYER_STAT_FIELDS: dict[str, str] = {
    "games_played": "games_played",
    "wins": "games_won",
    "losses": "games_lost",
    "goals": "goals",
    "assists": "assists",
    "saves": "saves",
    "shots": "shots",
    "points": "points",
    "mvps": "mvps",
    "shooting_percentage": "shooting_percentage",
    "demos_inflicted": "demos_inflicted",
    "bpm": "bpm",
    "team_goals_in_games": "team_goals_in_games",
    "opponent_goals_in_games": "opponent_goals_in_games",
}

TEAM_STAT_FIELDS: dict[str, str] = {
    "games_played": "games_played",
    "wins": "games_won",
    "losses": "games_lost",
    "goals": "goals",
    "goals_against": "opponent_goals",
    "goal_differential": "goal_differential",
    "assists": "assists",
    "saves": "saves",
    "shots": "shots",
    "shooting_percentage": "shooting_percentage",
}


def _stat_block(stats: object, stat_fields: dict[str, str]) -> dict[str, object]:
    return {name.replace("_", " ").title(): getattr(stats, attr, None) for name, attr in stat_fields.items()}


def _stat_rows(records: list[Any], value_attr: str, rank_attr: str, limit: int, min_games: int) -> list[str]:
    ranked = [
        record
        for record in records
        if getattr(record, rank_attr, None) is not None and (getattr(record, "games_played", 0) or 0) >= min_games
    ]
    ranked.sort(key=lambda record: getattr(record, rank_attr))
    rows = []
    for record in ranked[:limit]:
        value = getattr(record, value_attr, None)
        games = getattr(record, "games_played", "?")
        rows.append(f"{getattr(record, rank_attr)} | {name_of(record.player)} | {value} | {games} GP")
    return rows


@tool(
    "top_players",
    "Leaderboard of the best players in a tier for one statistic. Use this for any 'who leads', "
    "'top scorer' or 'best at' question -- never fetch rosters and compare them yourself.",
    properties={
        "stat": {
            "type": "string",
            "enum": sorted(RANKED_STATS),
            "description": "Statistic to rank by.",
        },
        "tier": {"type": "string", "description": "Tier name, e.g. Master."},
        "limit": {"type": "integer", "description": "How many players (default 10, max 15)."},
        "min_games": {"type": "integer", "description": "Ignore players below this many games played."},
    },
    required=["stat", "tier"],
    cacheable=True,
)
async def top_players(ctx: AgentContext, stat: str, tier: str, limit: int = 10, min_games: int = 0) -> str:
    if stat not in RANKED_STATS:
        return f"ERROR: unknown stat {stat!r}. Valid: {', '.join(sorted(RANKED_STATS))}"
    limit = max(1, min(int(limit), 15))

    await ctx.resolve_season()
    tier_id = await ctx.cog.tier_id_by_name(ctx.guild, tier)
    records = await ctx.cog.tier_player_stats(ctx.guild, tier_id, season=ctx.season_number)

    value_attr, rank_attr = RANKED_STATS[stat]
    rows = _stat_rows(list(records), value_attr, rank_attr, limit, int(min_games))
    return table(f"TOP {stat.upper()} - {tier}\nRANK | PLAYER | {stat.upper()} | GAMES", rows)


@tool(
    "top_teams",
    "Leaderboard of teams in a tier by a statistic.",
    properties={
        "stat": {"type": "string", "description": "Statistic, e.g. goals, wins, saves."},
        "tier": {"type": "string", "description": "Tier name."},
        "limit": {"type": "integer", "description": "How many teams (default 10, max 15)."},
    },
    required=["stat", "tier"],
    cacheable=True,
)
async def top_teams(ctx: AgentContext, stat: str, tier: str, limit: int = 10) -> str:
    limit = max(1, min(int(limit), 15))
    await ctx.resolve_season()
    tier_id = await ctx.cog.tier_id_by_name(ctx.guild, tier)
    records = list(await ctx.cog.tier_team_stats(ctx.guild, tier_id, season=ctx.season_number))

    attr = TEAM_STAT_FIELDS.get(stat, stat)
    if records and not hasattr(records[0], attr):
        available = ", ".join(name for name, field in TEAM_STAT_FIELDS.items() if hasattr(records[0], field))
        return f"ERROR: unknown team stat {stat!r}. Valid: {available}"

    records.sort(key=lambda record: getattr(record, attr, 0) or 0, reverse=True)
    rows = [
        f"{index} | {name_of(record.team)} | {getattr(record, attr, 0)} | {getattr(record, 'games_played', '?')} GP"
        for index, record in enumerate(records[:limit], start=1)
    ]
    return table(f"TOP {stat.upper()} - {tier} TEAMS\nRANK | TEAM | {stat.upper()} | GAMES", rows)


@tool(
    "get_player_stats",
    "Season statistics for one player.",
    properties={
        "name": {"type": "string", "description": "Player's RSC name."},
        "me": {"type": "boolean", "description": "Look up the asking user."},
        "postseason": {"type": "boolean", "description": "Postseason instead of regular season."},
    },
)
async def get_player_stats(
    ctx: AgentContext,
    name: str | None = None,
    me: bool = False,
    postseason: bool = False,
) -> str:
    discord_id = None
    if me:
        if ctx.identity is None or ctx.identity.discord_id is None:
            return "ERROR: could not identify the asking user."
        discord_id = ctx.identity.discord_id
        name = None
    if not name and not discord_id:
        return "ERROR: provide a name or me=true."

    players = await ctx.cog.players(ctx.guild, name=name, discord_id=discord_id, limit=1)
    if not players:
        return f"No player found for {name or discord_id!r}."

    # `player_stats` keys off the Discord member, so a player who has left the
    # server cannot be looked up this way.
    member_id = getattr(players[0].player, "discord_id", None)
    member = ctx.guild.get_member(member_id) if member_id else None
    if member is None:
        return f"{name_of(players[0].player)} is not currently in this Discord server, so stats are unavailable."

    stats: Any = await ctx.cog.player_stats(ctx.guild, member, postseason=postseason)
    if stats is None:
        return f"No statistics recorded for {name_of(players[0].player)}."

    # A deliberate subset: the model never needs all ~112 fields, and sending
    # them would dominate the context for one lookup.
    block = {"Player": name_of(players[0].player), "Tier": name_of(players[0].tier)}
    block.update(_stat_block(stats, PLAYER_STAT_FIELDS))
    games_played = getattr(stats, "games_played", None)
    if games_played:
        block["Goals Per Game"] = round((getattr(stats, "goals", None) or 0) / games_played, 2)
        block["Points Per Game"] = round((getattr(stats, "points", None) or 0) / games_played, 2)
    team_goals = getattr(stats, "team_goals_in_games", None)
    opponent_goals = getattr(stats, "opponent_goals_in_games", None)
    if team_goals is not None and opponent_goals is not None:
        block["Goal Differential"] = team_goals - opponent_goals
    return fields(block)


@tool(
    "get_team_stats",
    "Season statistics for one team.",
    properties={"team": {"type": "string", "description": "Team name."}},
    required=["team"],
    cacheable=True,
)
async def get_team_stats(ctx: AgentContext, team: str) -> str:
    await ctx.resolve_season()
    team_id = await ctx.cog.team_id_by_name(ctx.guild, team)
    stats: Any = await ctx.cog.team_stats(ctx.guild, team_id, season=ctx.season_number)
    if stats is None:
        return f"No statistics recorded for {team}."

    block = {"Team": team}
    block.update(_stat_block(stats, TEAM_STAT_FIELDS))
    return fields(block)
