"""Glue between the Discord cog and the agent.

Keeps identity resolution, spend gating and context construction out of the cog
so `llm.py` stays a thin Discord surface.
"""

import logging
from dataclasses import dataclass
from datetime import datetime
from typing import TYPE_CHECKING

import discord
from openai import AsyncOpenAI

from rsc.llm.agent.budget import CooldownTracker, usage_day
from rsc.llm.agent.cache import ToolCache
from rsc.llm.agent.context import AgentContext, UserIdentity
from rsc.llm.rulebook import load_rulebooks
from rsc.logs import GuildLogAdapter

if TYPE_CHECKING:
    from rsc.abc import RSCMixIn

logger = logging.getLogger("red.rsc.llm.agent.service")
log = GuildLogAdapter(logger)


@dataclass(frozen=True, slots=True)
class BudgetVerdict:
    """Whether a question may proceed, and why not if it may not."""

    allowed: bool
    reason: str = ""
    retry_after: float = 0.0

    @property
    def rate_limited(self) -> bool:
        return self.retry_after > 0


async def resolve_agent_identity(
    cog: "RSCMixIn",
    guild: discord.Guild,
    member: discord.Member | discord.User,
) -> UserIdentity:
    """Map a Discord user onto their league identity.

    Never raises: an unidentified asker still gets an answer, just without
    "my team" style personalisation.
    """
    name = getattr(member, "display_name", None) or str(member)
    identity = UserIdentity(name=name, discord_id=member.id)
    if not isinstance(member, discord.Member):
        return identity

    try:
        players = await cog.players(guild, discord_id=member.id, limit=1)
    except Exception as exc:
        log.warning(f"Could not resolve identity for {member.id}: {exc}", guild=guild)
        return identity

    if not players:
        return identity

    player = players[0]
    team = player.team
    identity.name = player.player.name if player.player and player.player.name else name
    identity.team = team.name if team else None
    identity.franchise = team.franchise.name if team and team.franchise else None
    identity.tier = player.tier.name if player.tier else None
    identity.status = str(player.status) if player.status else None
    return identity


async def build_agent_context(
    cog: "RSCMixIn",
    guild: discord.Guild,
    member: discord.Member | discord.User,
    *,
    api_key: str,
    org: str | None,
    surface: str,
    cache: ToolCache,
    now: datetime,
) -> AgentContext:
    """Assemble everything one question needs."""
    # Cheap after the first call; guarded so a cold start still works if the
    # startup warm-up did not run.
    await load_rulebooks()

    identity = await resolve_agent_identity(cog, guild, member)
    ctx = AgentContext(
        cog=cog,
        guild=guild,
        client=AsyncOpenAI(api_key=api_key, organization=org),
        now=now,
        identity=identity,
        surface=surface,
        cache=cache,
    )
    # Resolved once here so tools do not each re-fetch it, and so the season
    # id / number distinction is settled in one place.
    try:
        await ctx.resolve_season()
    except Exception as exc:
        log.warning(f"Could not resolve current season: {exc}", guild=guild)
    return ctx


async def check_budget(
    cog: "RSCMixIn",
    guild: discord.Guild,
    member: discord.Member | discord.User,
    *,
    cooldown: CooldownTracker,
    user_cap: int,
    guild_cap: int,
    now: datetime,
) -> BudgetVerdict:
    """Apply the cooldown and daily caps.

    Elevated members bypass the per-user cap but not the guild cap -- staff
    should not be throttled mid-investigation, but nor should they be able to
    exhaust the budget on their own.
    """
    retry_after = cooldown.retry_after(guild.id, member.id)
    if retry_after > 0:
        return BudgetVerdict(allowed=False, reason="cooldown", retry_after=retry_after)

    day = usage_day(now)
    guild_used = await _usage_count(cog, guild.id, 0, day)
    if guild_cap and guild_used >= guild_cap:
        return BudgetVerdict(allowed=False, reason="guild_cap")

    privileged = False
    if isinstance(member, discord.Member):
        try:
            privileged = bool(await cog.elevated_positions(guild, member.id))
        except Exception as exc:
            log.warning(f"Could not check elevated roles for {member.id}: {exc}", guild=guild)

    if not privileged and user_cap:
        used = await _usage_count(cog, guild.id, member.id, day)
        if used >= user_cap:
            return BudgetVerdict(allowed=False, reason="user_cap")

    return BudgetVerdict(allowed=True)


async def _usage_count(cog: "RSCMixIn", guild_id: int, user_id: int, day: str) -> int:
    record = cog.config.custom("LLMUsage", str(guild_id), str(user_id))
    if await record.day() != day:
        return 0
    return int(await record.count())


async def record_usage(
    cog: "RSCMixIn",
    guild: discord.Guild,
    user_id: int,
    *,
    tokens: int,
    now: datetime,
) -> None:
    """Increment the per-user and per-guild counters for today.

    User id 0 is the guild-wide bucket.
    """
    day = usage_day(now)
    for scope in (user_id, 0):
        record = cog.config.custom("LLMUsage", str(guild.id), str(scope))
        if await record.day() != day:
            await record.day.set(day)
            await record.count.set(0)
            await record.tokens.set(0)
        await record.count.set(int(await record.count()) + 1)
        await record.tokens.set(int(await record.tokens()) + tokens)


async def usage_today(cog: "RSCMixIn", guild: discord.Guild, user_id: int, now: datetime) -> tuple[int, int]:
    """Questions asked and tokens spent today, for `/llm usage`."""
    record = cog.config.custom("LLMUsage", str(guild.id), str(user_id))
    if await record.day() != usage_day(now):
        return (0, 0)
    return (int(await record.count()), int(await record.tokens()))
