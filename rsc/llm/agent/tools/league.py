"""Franchise, team, player, and tier tools."""

from typing import Any

from rsc.llm.agent.context import AgentContext
from rsc.llm.agent.format import fields, format_date, humanize_status, name_of, parse_status, table
from rsc.llm.agent.registry import tool

TIER_PARAM = {"type": "string", "description": "Tier name, e.g. Master, Elite, Rival."}


@tool(
    "list_franchises",
    "Every franchise in the league with its GM. Set include_agms to also list assistant GMs. "
    "This returns the complete list -- use it for any 'all franchises' question.",
    properties={
        "include_agms": {"type": "boolean", "description": "Also include assistant GMs."},
        "tier": TIER_PARAM,
    },
    cacheable=True,
)
async def list_franchises(ctx: AgentContext, include_agms: bool = False, tier: str | None = None) -> str:
    franchises = await ctx.cog.franchises(ctx.guild, tier_name=tier)

    agms: dict[int, list[str]] = {}
    if include_agms:
        # One league-wide sweep. `FranchiseList` carries no `agms` field, so the
        # alternative is a detail fetch per franchise -- ~30 round trips.
        for role in await ctx.cog.league_elevated_roles(ctx.guild, agm=True):
            if role.franchise_id is None:
                continue
            agms.setdefault(role.franchise_id, []).append(name_of(role.member))

    rows = []
    for franchise in franchises:
        gm = name_of(franchise.gm) or "None"
        tiers = ",".join(name_of(t) for t in (franchise.tiers or []))
        row = f"{franchise.prefix} | {franchise.name} | GM: {gm}"
        if include_agms:
            # `franchise.id or -1` would be wrong: id 0 is falsy and would miss
            # its own AGMs.
            assistants = ", ".join(sorted(agms.get(franchise.id, []))) if franchise.id is not None else []
            row = f"{row} | AGMs: {assistants or 'none'}"
        rows.append(f"{row} | tiers: {tiers}")

    header = "PREFIX | FRANCHISE | GM" + (" | AGMS" if include_agms else "") + " | TIERS"
    return table(header, rows)


@tool(
    "get_franchise",
    "Details for one franchise: GM, assistant GMs, teams, tiers and win/loss record.",
    properties={"name": {"type": "string", "description": "Franchise name or prefix."}},
    required=["name"],
    cacheable=True,
)
async def get_franchise(ctx: AgentContext, name: str) -> str:
    summary = await ctx.cog.fetch_franchise(ctx.guild, name)
    if summary is None or summary.id is None:
        return f"No franchise found matching {name!r}."

    franchise: Any = await ctx.cog.franchise_by_id(ctx.guild, summary.id)
    if franchise is None:
        return f"No franchise found matching {name!r}."

    record = ""
    await ctx.resolve_season()
    if ctx.season_id is not None:
        for standing in await ctx.cog.franchise_standings(ctx.guild, ctx.season_id):
            if name_of(standing.franchise) == franchise.name:
                record = f"{standing.wins}-{standing.losses} (rank {standing.franchise_standings_rank})"
                break

    return fields(
        {
            "Franchise": franchise.name,
            "Prefix": franchise.prefix,
            "GM": name_of(franchise.gm),
            "AGMs": ", ".join(name_of(agm) for agm in (franchise.agms or [])) or "none",
            "Tiers": ", ".join(name_of(t) for t in (franchise.tiers or [])),
            "Teams": ", ".join(name_of(t) for t in (franchise.teams or [])),
            "Record": record,
        }
    )


@tool(
    "list_teams",
    "Teams in the league, optionally filtered by franchise or tier.",
    properties={
        "franchise": {"type": "string", "description": "Franchise name."},
        "tier": TIER_PARAM,
        "name": {"type": "string", "description": "Team name."},
    },
    cacheable=True,
)
async def list_teams(
    ctx: AgentContext,
    franchise: str | None = None,
    tier: str | None = None,
    name: str | None = None,
) -> str:
    teams = await ctx.cog.teams(ctx.guild, franchise=franchise, tier=tier, name=name)
    rows = [f"{team.name} | {name_of(team.franchise)} | {name_of(team.tier)}" for team in teams]
    return table("TEAM | FRANCHISE | TIER", rows)


@tool(
    "get_team_roster",
    "The current roster of a team, with each player's status, captaincy and MMR.",
    properties={"team": {"type": "string", "description": "Team name."}},
    required=["team"],
    cacheable=True,
)
async def get_team_roster(ctx: AgentContext, team: str) -> str:
    team_id = await ctx.cog.team_id_by_name(ctx.guild, team)
    players = await ctx.cog.team_players(ctx.guild, team_id)
    rows = []
    for player in players:
        captain = " (C)" if getattr(player, "captain", False) else ""
        rows.append(f"{player.name}{captain} | {humanize_status(player.status)} | MMR {player.current_mmr}")
    return table(f"ROSTER: {team}\nPLAYER | STATUS | MMR", rows)


@tool(
    "find_player",
    "Look up one player's team, franchise, tier, status, contract and MMR. Set me=true to look up the person who asked the question.",
    properties={
        "name": {"type": "string", "description": "Player's RSC name."},
        "discord_id": {"type": "integer", "description": "Player's Discord user id."},
        "me": {"type": "boolean", "description": "Look up the asking user."},
    },
)
async def find_player(
    ctx: AgentContext,
    name: str | None = None,
    discord_id: int | None = None,
    me: bool = False,
) -> str:
    if me:
        if ctx.identity is None or ctx.identity.discord_id is None:
            return "ERROR: could not identify the asking user."
        discord_id = ctx.identity.discord_id
        name = None
    if not name and not discord_id:
        return "ERROR: provide name, discord_id, or me=true."

    players = await ctx.cog.players(ctx.guild, name=name, discord_id=discord_id, limit=5)
    if not players:
        return f"No player found for {name or discord_id!r}."

    blocks = []
    for player in players:
        team = player.team
        blocks.append(
            fields(
                {
                    "Player": name_of(player.player),
                    "Status": humanize_status(player.status),
                    "Tier": name_of(player.tier),
                    "Team": name_of(team),
                    "Franchise": name_of(getattr(team, "franchise", None)),
                    "Captain": "yes" if player.captain else "no",
                    "Contract length": player.contract_length,
                    "MMR": player.current_mmr,
                }
            )
        )
    return "\n\n".join(blocks)


@tool(
    "list_players",
    "Players filtered by status, tier, franchise or team. Use status=FA for free agents, "
    "PF for permanent free agents, DE for draft eligible, RO for rostered, IR for inactive reserve. "
    "Always reports the true total even when the row list is capped.",
    properties={
        "status": {
            "type": "string",
            "description": "Status code: RO, FA, PF, DE, IR, RN, WV, AR, UG.",
        },
        "tier": TIER_PARAM,
        "franchise": {"type": "string", "description": "Franchise name."},
        "team": {"type": "string", "description": "Team name."},
        "limit": {"type": "integer", "description": "Max rows to return (default 25, max 50)."},
    },
)
async def list_players(
    ctx: AgentContext,
    status: str | None = None,
    tier: str | None = None,
    franchise: str | None = None,
    team: str | None = None,
    limit: int = 25,
) -> str:
    limit = max(1, min(int(limit), 50))
    # Raises ValueError with the valid codes, which `_dispatch` hands back to
    # the model so it can correct itself rather than failing the whole answer.
    parsed = parse_status(status) if status else None
    players = await ctx.cog.players(
        ctx.guild,
        status=parsed,
        tier_name=tier,
        franchise=franchise,
        team_name=team,
        limit=limit,
    )
    total = await ctx.cog.player_count(
        ctx.guild,
        status=parsed,
        tier_name=tier,
        franchise=franchise,
        team_name=team,
    )
    rows = [
        f"{name_of(p.player)} | {humanize_status(p.status)} | {name_of(p.tier)} | {name_of(p.team) or 'no team'} | MMR {p.current_mmr}"
        for p in players
    ]
    return table("PLAYER | STATUS | TIER | TEAM | MMR", rows, total=total)


@tool(
    "list_tiers",
    "The league's tiers, strongest first.",
    cacheable=True,
)
async def list_tiers(ctx: AgentContext) -> str:
    tiers = await ctx.cog.tiers(ctx.guild)
    return table("TIER | POSITION", [f"{tier.name} | {tier.position}" for tier in tiers])


@tool(
    "get_season_info",
    "The current season number and its key dates (signups, draft, regular season, deadlines).",
    cacheable=True,
)
async def get_season_info(ctx: AgentContext) -> str:
    season: Any = await ctx.cog.current_season(ctx.guild)
    if season is None:
        return "No current season is configured."

    block = fields(
        {
            "Season": season.number,
            "Signups open": format_date(season.signups_open),
            "Signups close": format_date(season.signup_close),
            "Draft": format_date(season.draft_date),
            "Preseason start": format_date(season.preseason_start_date),
            "Regular season start": format_date(season.regular_season_start),
            "Regular season end": format_date(season.regular_season_end),
        }
    )

    # Admin-maintained free text: deadlines and one-off dates that have no
    # field on the Season model.
    dates = await ctx.cog._get_dates(ctx.guild)
    if dates:
        block = f"{block}\n\nLeague dates:\n{dates}"
    return block
