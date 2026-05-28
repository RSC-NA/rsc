#!/usr/bin/env python3

# sql overrides - MUST happen before importing chromadb
import sys

__import__("pysqlite3")
sys.modules["sqlite3"] = sys.modules.pop("pysqlite3")

import logging  # noqa: E402
import re  # noqa: E402
from dataclasses import dataclass  # noqa: E402
from datetime import datetime  # noqa: E402
from enum import Enum  # noqa: E402
from typing import TYPE_CHECKING, Any, cast  # noqa: E402

import chromadb  # noqa: E402
import discord  # noqa: E402
import httpx  # noqa: E402

from openai import AsyncOpenAI  # noqa: E402
from langchain_chroma import Chroma  # noqa: E402
from langchain_openai.embeddings import OpenAIEmbeddings  # noqa: E402
from langchain_core.documents import Document  # noqa: E402
from pydantic.types import SecretStr  # noqa: E402

from rsc.llm.config import (  # noqa: E402
    CHROMA_PATH,
    OPENAI_CHAT_MODEL,
    OPENAI_EMBEDDING_MODEL,
    openai_chat_completion_options,
)
from rsc.llm.sources import DocumentSource, SOURCE_TYPE_METADATA_KEY, document_source  # noqa: E402
from rsc.logs import GuildLogAdapter  # noqa: E402


if TYPE_CHECKING:
    from openai.types.chat import ChatCompletionMessageParam


logger = logging.getLogger("red.rsc.llm.query")
log = GuildLogAdapter(logger)

# Disable Loggers
logging.getLogger("chromadb").setLevel(logging.ERROR)
logging.getLogger("httpcore").setLevel(logging.ERROR)
logging.getLogger("httpx").setLevel(logging.ERROR)
logging.getLogger("openai").setLevel(logging.ERROR)
logging.getLogger("urllib3").setLevel(logging.ERROR)

CHROMA_PATH_ABS = CHROMA_PATH.absolute()

# Constants
ANCHOR_SCORE_THRESHOLD = 0.95
ANCHOR_EXPANSION_MIN_SCORE = 0.5  # Minimum score for expanded context
DYNAMIC_CUTOFF = 0.65
DEFAULT_DOCUMENT_SOURCES = (
    DocumentSource.RULEBOOK,
    DocumentSource.GLOSSARY,
    DocumentSource.DATES,
    DocumentSource.HELP,
    DocumentSource.SEASON,
    DocumentSource.PLAYERS,
    DocumentSource.PLAYER_STATS,
    DocumentSource.TEAMS,
    DocumentSource.TEAM_STATS,
    DocumentSource.STANDINGS,
    DocumentSource.FRANCHISES,
    DocumentSource.MATCHES,
)


class QueryIntent(Enum):
    """High-level intent used to route retrieval."""

    RULES = "rules"
    PLAYER = "player"
    TEAM = "team"
    FRANCHISE = "franchise"
    MATCH = "match"
    SEASON = "season"
    MIXED = "mixed"
    GENERAL = "general"


@dataclass(frozen=True)
class RetrievalPlan:
    """Document retrieval plan for one user question."""

    intent: QueryIntent
    target_sources: tuple[DocumentSource, ...]
    source_priority: tuple[DocumentSource, ...]
    query_rewrites: tuple[str, ...] = ()
    required_sources: tuple[DocumentSource, ...] = ()
    include_user_context: bool = False
    include_current_date: bool = False


@dataclass(frozen=True)
class PromptContextPolicy:
    """Controls which user context is allowed into the final LLM prompt."""

    include_player_identity: bool = False
    include_current_datetime: bool = False


RULE_NUMBER_PATTERN = re.compile(r"\b(?:rule|section)?\s*(\d+(?:\.\d+)+)\b", re.IGNORECASE)
RULE_KEYWORDS = (
    "rule",
    "rules",
    "rulebook",
    "allowed",
    "eligible",
    "eligibility",
    "forbidden",
    "violation",
    "penalty",
    "appeal",
    "behavior",
    "conduct",
    "waiver",
    "waivers",
    "draft",
    "drafted",
    "sign",
    "signed",
    "signing",
    "cut",
    "trade",
    "sub",
    "subs",
    "subbed",
    "subbing",
    "substitute",
    "substitution",
    "contract",
    "roster",
    "free agent",
    "permfa",
    "permanent free agent",
)
RULE_KEYWORD_WEIGHTS = {
    "rule": 4,
    "rules": 4,
    "rulebook": 5,
    "allowed": 2,
    "eligible": 2,
    "eligibility": 2,
    "forbidden": 3,
    "violation": 3,
    "penalty": 3,
    "appeal": 3,
    "behavior": 2,
    "conduct": 2,
    "waiver": 2,
    "waivers": 2,
    "draft": 2,
    "drafted": 2,
    "sign": 2,
    "signed": 2,
    "signing": 2,
    "cut": 2,
    "trade": 2,
    "sub": 5,
    "subs": 5,
    "subbed": 5,
    "subbing": 5,
    "substitute": 5,
    "substitution": 5,
    "sub in": 6,
    "sub out": 6,
    "subbed out": 6,
    "substituted off": 6,
    "substituted out": 6,
    "in a row": 5,
    "consecutive": 5,
    "match day": 3,
    "match days": 3,
    "same franchise": 4,
    "same team": 4,
    "twice": 3,
    "two times": 3,
    "limit": 3,
    "maximum": 3,
    "minimum": 2,
    "how many": 1,
    "contract": 2,
    "roster": 2,
    "free agent": 2,
    "fa": 2,
    "pfa": 2,
    "permfa": 2,
    "permanent free agent": 2,
}
PLAYER_KEYWORD_WEIGHTS = {
    "player": 2,
    "status": 2,
    "mmr": 3,
    "tier": 2,
    "captain": 2,
    "gm": 2,
    "general manager": 2,
    "my team": 3,
    "my franchise": 3,
    "stats": 2,
    "stat": 2,
    "goals": 2,
    "saves": 2,
    "assists": 2,
    "shots": 2,
    "mvps": 2,
    "points": 2,
}
TEAM_KEYWORD_WEIGHTS = {
    "team": 2,
    "roster": 2,
    "captain": 2,
    "lineup": 3,
    "record": 2,
    "standings": 2,
}
FRANCHISE_KEYWORD_WEIGHTS = {"franchise": 2, "gm": 2, "general manager": 2, "prefix": 3, "record": 2, "standings": 3}
MATCH_KEYWORD_WEIGHTS = {
    "match": 3,
    "matches": 3,
    "schedule": 3,
    "game": 2,
    "games": 2,
    "play": 2,
    "played": 2,
    "next": 2,
    "last": 2,
    "today": 3,
    "tomorrow": 3,
    "yesterday": 3,
}
SEASON_KEYWORD_WEIGHTS = {"season": 3, "deadline": 3, "date": 2, "dates": 2, "week": 2, "current season": 4}
PLAYER_KEYWORDS = (
    "player",
    "status",
    "mmr",
    "tier",
    "captain",
    "gm",
    "general manager",
    "my team",
    "my franchise",
    "stats",
    "stat",
    "goals",
    "saves",
    "assists",
    "shots",
    "mvps",
    "points",
)
TEAM_KEYWORDS = ("team", "roster", "captain", "lineup", "record", "standings")
FRANCHISE_KEYWORDS = ("franchise", "gm", "general manager", "prefix", "record", "standings")
MATCH_KEYWORDS = ("match", "matches", "schedule", "game", "games", "play", "played", "next", "last", "today", "tomorrow", "yesterday")
SEASON_KEYWORDS = ("season", "deadline", "date", "dates", "week", "current season")
PERSONAL_KEYWORDS = (" i ", " me ", " my ", " mine ", " myself ", " i'm ", " ive ", " i've ")
STATS_KEYWORDS = (
    "stats",
    "stat",
    "goals",
    "goal",
    "saves",
    "save",
    "assists",
    "assist",
    "shots",
    "shot",
    "mvps",
    "mvp",
    "points",
    "point",
    "shooting percentage",
    "win percentage",
    "goals per game",
    "points per game",
    "gpg",
    "ppg",
    "bpm",
    "bcpm",
    "boost per minute",
    "average speed",
    "avg speed",
    "demos",
)
TEAM_CONTEXT_KEYWORDS = ("team", "roster", "captain", "lineup", "record", "standings", "my team")
SUBSTITUTION_TERMS = ("sub", "subs", "subbed", "subbing", "substitute", "substitution", "substituted")
SUBSTITUTION_LIMIT_TERMS = (
    "in a row",
    "consecutive",
    "same franchise",
    "same team",
    "twice",
    "two times",
    "how many",
    "limit",
    "maximum",
    "match day",
    "match days",
)


# User Identity
@dataclass
class UserIdentity:
    """Identity information for the user asking the question."""

    name: str
    team: str | None = None
    franchise: str | None = None
    tier: str | None = None
    status: str | None = None
    current_datetime: datetime | None = None


def _contains_keyword(question: str, keywords: tuple[str, ...]) -> bool:
    question_l = f" {question.lower()} "
    return any(_contains_weighted_keyword(question_l, keyword) for keyword in keywords)


def _contains_weighted_keyword(question_l: str, keyword: str) -> bool:
    if " " in keyword.strip():
        return keyword in question_l
    return bool(re.search(rf"\b{re.escape(keyword)}\b", question_l))


def _score_keywords(question_l: str, keyword_weights: dict[str, int]) -> int:
    return sum(weight for keyword, weight in keyword_weights.items() if _contains_weighted_keyword(question_l, keyword))


def _has_keyword(question_l: str, keywords: tuple[str, ...]) -> bool:
    return any(_contains_weighted_keyword(question_l, keyword) for keyword in keywords)


def _build_rule_query_rewrites(question: str) -> tuple[str, ...]:
    question_l = f" {question.lower()} "
    rewrites: list[str] = []

    if _has_keyword(question_l, SUBSTITUTION_TERMS):
        substitution_context = [
            "substitute substitution consecutive match days same franchise same team",
            "FA permFA permanent free agent substitute same franchise two times in a row",
        ]
        if _has_keyword(question_l, ("same franchise", "franchise", "twice", "two times")):
            substitution_context.append("free agent permFA cannot substitute same franchise two times in a row")
        if _has_keyword(question_l, ("same team", "team", "highest tier")):
            substitution_context.append("highest tier substitute same team up to two match days in a row")
        if _has_keyword(question_l, ("subbed out", "sub out", "substituted off", "out", "consecutive")):
            substitution_context.append("player being substituted off cannot be out more than two consecutive match days")
        rewrites.extend(substitution_context)

    return tuple(dict.fromkeys(rewrites))


def _rule_score(question: str) -> int:
    question_l = f" {question.lower()} "
    score = _score_keywords(question_l, RULE_KEYWORD_WEIGHTS)
    if RULE_NUMBER_PATTERN.search(question):
        score += 8
    if _has_keyword(question_l, SUBSTITUTION_TERMS) and _has_keyword(question_l, SUBSTITUTION_LIMIT_TERMS):
        score += 6
    return score


def _build_player_stats_query_rewrites(identity: UserIdentity | None) -> tuple[str, ...]:
    player_prefix = f"{identity.name} " if identity else ""
    return (f"{player_prefix}player stats goals assists saves shots points MVPs shooting percentage boost per minute average speed",)


def _contains_personal_reference(question: str, identity: UserIdentity | None) -> bool:
    question_l = f" {question.lower()} "
    if any(keyword in question_l for keyword in PERSONAL_KEYWORDS):
        return True
    if not identity:
        return False
    identity_terms = [identity.name, identity.team, identity.franchise, identity.tier]
    return any(term and term.lower() in question_l for term in identity_terms)


def build_retrieval_plan(question: str, user_identity: UserIdentity | None = None) -> RetrievalPlan:
    """Classify a question and decide which document sources should be searched."""
    question_l = f" {question.lower()} "
    rule_score = _rule_score(question)
    match_score = _score_keywords(question_l, MATCH_KEYWORD_WEIGHTS)
    season_score = _score_keywords(question_l, SEASON_KEYWORD_WEIGHTS)
    player_score = _score_keywords(question_l, PLAYER_KEYWORD_WEIGHTS)
    team_score = _score_keywords(question_l, TEAM_KEYWORD_WEIGHTS)
    franchise_score = _score_keywords(question_l, FRANCHISE_KEYWORD_WEIGHTS)
    asks_about_rules = bool(RULE_NUMBER_PATTERN.search(question)) or rule_score >= 4 or _contains_keyword(question, RULE_KEYWORDS)
    asks_about_matches = match_score >= 3 or _contains_keyword(question, MATCH_KEYWORDS)
    asks_about_season = season_score >= 3 or _contains_keyword(question, SEASON_KEYWORDS)
    asks_about_player = player_score >= 2 or _contains_keyword(question, PLAYER_KEYWORDS)
    asks_about_team = team_score >= 2 or _contains_keyword(question, TEAM_KEYWORDS)
    asks_about_franchise = franchise_score >= 2 or _contains_keyword(question, FRANCHISE_KEYWORDS)
    asks_about_stats = _has_keyword(question_l, STATS_KEYWORDS)
    asks_about_team_context = _has_keyword(question_l, TEAM_CONTEXT_KEYWORDS)
    is_personal = _contains_personal_reference(question, user_identity)
    uses_personal_pronoun = any(keyword in question_l for keyword in PERSONAL_KEYWORDS)

    if asks_about_rules:
        return RetrievalPlan(
            intent=QueryIntent.RULES,
            target_sources=(
                DocumentSource.RULEBOOK,
                DocumentSource.GLOSSARY,
                DocumentSource.HELP,
                DocumentSource.DATES,
                DocumentSource.SEASON,
            ),
            source_priority=(
                DocumentSource.RULEBOOK,
                DocumentSource.GLOSSARY,
                DocumentSource.HELP,
                DocumentSource.DATES,
                DocumentSource.SEASON,
            ),
            query_rewrites=_build_rule_query_rewrites(question),
            required_sources=(DocumentSource.RULEBOOK,),
            include_user_context=False,
            include_current_date=asks_about_season,
        )
    if asks_about_matches:
        return RetrievalPlan(
            intent=QueryIntent.MATCH,
            target_sources=(
                DocumentSource.MATCHES,
                DocumentSource.TEAMS,
                DocumentSource.SEASON,
                DocumentSource.DATES,
                DocumentSource.GLOSSARY,
            ),
            source_priority=(
                DocumentSource.MATCHES,
                DocumentSource.SEASON,
                DocumentSource.DATES,
                DocumentSource.TEAMS,
                DocumentSource.GLOSSARY,
            ),
            include_user_context=is_personal,
            include_current_date=True,
        )
    if asks_about_team and team_score >= player_score and not uses_personal_pronoun:
        target_sources = (
            (
                DocumentSource.TEAM_STATS,
                DocumentSource.STANDINGS,
                DocumentSource.TEAMS,
                DocumentSource.PLAYERS,
                DocumentSource.FRANCHISES,
                DocumentSource.GLOSSARY,
                DocumentSource.SEASON,
            )
            if asks_about_stats
            else (
                DocumentSource.TEAMS,
                DocumentSource.TEAM_STATS,
                DocumentSource.STANDINGS,
                DocumentSource.PLAYERS,
                DocumentSource.FRANCHISES,
                DocumentSource.GLOSSARY,
                DocumentSource.SEASON,
            )
        )
        return RetrievalPlan(
            intent=QueryIntent.TEAM,
            target_sources=target_sources,
            source_priority=target_sources,
            required_sources=(DocumentSource.TEAM_STATS,) if asks_about_stats else (),
        )
    if asks_about_player or is_personal:
        target_sources = [DocumentSource.PLAYER_STATS, DocumentSource.PLAYERS, DocumentSource.TEAMS]
        if not asks_about_stats:
            target_sources = [DocumentSource.PLAYERS, DocumentSource.PLAYER_STATS, DocumentSource.TEAMS]
        if asks_about_team_context:
            target_sources.extend((DocumentSource.TEAM_STATS, DocumentSource.STANDINGS))
        target_sources.extend((DocumentSource.FRANCHISES, DocumentSource.GLOSSARY, DocumentSource.SEASON))
        return RetrievalPlan(
            intent=QueryIntent.PLAYER,
            target_sources=tuple(target_sources),
            source_priority=tuple(target_sources),
            query_rewrites=_build_player_stats_query_rewrites(user_identity) if asks_about_stats else (),
            required_sources=(DocumentSource.PLAYER_STATS,) if asks_about_stats else (),
            include_user_context=True,
            include_current_date=asks_about_season,
        )
    if asks_about_team:
        target_sources = (
            (
                DocumentSource.TEAM_STATS,
                DocumentSource.STANDINGS,
                DocumentSource.TEAMS,
                DocumentSource.PLAYERS,
                DocumentSource.FRANCHISES,
                DocumentSource.GLOSSARY,
                DocumentSource.SEASON,
            )
            if asks_about_stats
            else (
                DocumentSource.TEAMS,
                DocumentSource.TEAM_STATS,
                DocumentSource.STANDINGS,
                DocumentSource.PLAYERS,
                DocumentSource.FRANCHISES,
                DocumentSource.GLOSSARY,
                DocumentSource.SEASON,
            )
        )
        return RetrievalPlan(
            intent=QueryIntent.TEAM,
            target_sources=target_sources,
            source_priority=target_sources,
            required_sources=(DocumentSource.TEAM_STATS,) if asks_about_stats else (),
        )
    if asks_about_franchise:
        return RetrievalPlan(
            intent=QueryIntent.FRANCHISE,
            target_sources=(
                DocumentSource.FRANCHISES,
                DocumentSource.STANDINGS,
                DocumentSource.TEAMS,
                DocumentSource.GLOSSARY,
                DocumentSource.SEASON,
            ),
            source_priority=(
                DocumentSource.FRANCHISES,
                DocumentSource.STANDINGS,
                DocumentSource.TEAMS,
                DocumentSource.GLOSSARY,
                DocumentSource.SEASON,
            ),
        )
    if asks_about_season:
        return RetrievalPlan(
            intent=QueryIntent.SEASON,
            target_sources=(
                DocumentSource.SEASON,
                DocumentSource.DATES,
                DocumentSource.RULEBOOK,
                DocumentSource.GLOSSARY,
                DocumentSource.MATCHES,
                DocumentSource.STANDINGS,
            ),
            source_priority=(
                DocumentSource.SEASON,
                DocumentSource.DATES,
                DocumentSource.RULEBOOK,
                DocumentSource.GLOSSARY,
                DocumentSource.MATCHES,
                DocumentSource.STANDINGS,
            ),
            include_current_date=True,
        )
    return RetrievalPlan(
        intent=QueryIntent.GENERAL,
        target_sources=DEFAULT_DOCUMENT_SOURCES,
        source_priority=DEFAULT_DOCUMENT_SOURCES,
        include_user_context=False,
        include_current_date=False,
    )


def build_search_query(question: str, user_identity: UserIdentity | None, plan: RetrievalPlan) -> str:
    """Build the semantic search query without leaking irrelevant user context into retrieval."""
    retrieval_question = question
    query_context_parts: list[str] = []

    if user_identity and plan.include_user_context:
        retrieval_question = clean_question(question, user_identity.name)
        if user_identity.team:
            query_context_parts.append(f"Team: {user_identity.team}")
        if user_identity.franchise:
            query_context_parts.append(f"Franchise: {user_identity.franchise}")
        if user_identity.tier:
            query_context_parts.append(f"Tier: {user_identity.tier}")
        query_context_parts.append(f"Player: {user_identity.name}")

    if user_identity and plan.include_current_date and user_identity.current_datetime:
        date_str = user_identity.current_datetime.strftime("%m-%d-%Y")
        query_context_parts.append(f"Current Date: {date_str}")

    if not query_context_parts:
        return retrieval_question
    return f"{retrieval_question}\n" + "\n".join(query_context_parts)


def build_search_queries(question: str, user_identity: UserIdentity | None, plan: RetrievalPlan) -> tuple[str, ...]:
    """Build the primary semantic query plus deterministic rewrite variants."""
    queries = [build_search_query(question, user_identity, plan)]
    queries.extend(build_search_query(rewrite, user_identity, plan) for rewrite in plan.query_rewrites)
    return tuple(dict.fromkeys(queries))


def build_prompt_context_policy(plan: RetrievalPlan) -> PromptContextPolicy:
    """Build the final prompt context policy from the retrieval plan."""
    return PromptContextPolicy(
        include_player_identity=plan.include_user_context,
        include_current_datetime=plan.include_current_date,
    )


def _source_priority_boost(doc: Document, plan: RetrievalPlan) -> float:
    doc_source = document_source(doc)
    if not doc_source:
        return 0.0
    source_values = [source.value for source in plan.source_priority]
    if doc_source not in source_values:
        return 0.0
    priority_index = source_values.index(doc_source)
    return max(0.0, 0.25 - (priority_index * 0.12))


def prioritize_documents(
    docs: list[tuple[Document, float, float]],
    plan: RetrievalPlan,
) -> list[tuple[Document, float, float]]:
    """Sort documents using relevance with a small source-priority boost."""
    return sorted(
        docs,
        key=lambda item: (item[2] + _source_priority_boost(item[0], plan), item[2]),
        reverse=True,
    )


def ensure_source_coverage(
    selected: list[tuple[Document, float, float]],
    candidates: list[tuple[Document, float, float]],
    plan: RetrievalPlan,
    count: int,
) -> list[tuple[Document, float, float]]:
    """Keep required source families represented in the final context when possible."""
    required_sources = plan.required_sources

    if not required_sources:
        return selected[:count]

    result = list(selected)
    required_values = {source.value for source in required_sources}
    for source in required_sources:
        if any(document_source(doc) == source.value for doc, _distance, _score in result):
            continue
        candidate = next((item for item in candidates if document_source(item[0]) == source.value), None)
        if candidate:
            result.append(candidate)

    if len(result) <= count:
        return result

    protected = [item for item in result if document_source(item[0]) in required_values]
    others = [item for item in result if document_source(item[0]) not in required_values]
    return [*protected, *others[: max(0, count - len(protected))]]


async def _similarity_search_with_source(
    llm_db: Chroma,
    query: str,
    count: int,
    source: DocumentSource | None = None,
) -> list[tuple[Document, float]]:
    if not source:
        return await llm_db.asimilarity_search_with_score(query, k=count)
    return await llm_db.asimilarity_search_with_score(query, k=count, filter={SOURCE_TYPE_METADATA_KEY: source.value})


async def retrieve_documents(
    llm_db: Chroma,
    query: str,
    plan: RetrievalPlan,
    count: int,
) -> list[tuple[Document, float]]:
    """Run source-aware Chroma searches for the planned document sources."""
    results: list[tuple[Document, float]] = []
    per_source_count = max(2, count)
    query_variants = tuple(dict.fromkeys((query, *plan.query_rewrites)))
    for source in plan.target_sources:
        source_results: list[tuple[Document, float]] = []
        for query_variant in query_variants:
            source_results.extend(await _similarity_search_with_source(llm_db, query_variant, per_source_count, source=source))
        log.debug("Retrieved %d candidate documents from %s", len(source_results), source.value)
        results.extend(source_results)

    if results:
        return results

    log.debug("Filtered retrieval returned no results; falling back to unfiltered search.")
    return await _similarity_search_with_source(llm_db, query, count)


def format_time_context(identity: UserIdentity | None) -> str:
    """Format current date/time context for time-aware prompts."""
    if not (identity and identity.current_datetime):
        return ""

    dt_str = identity.current_datetime.strftime("%A, %B %d, %Y at %I:%M %p %Z")
    return (
        f"Current Date and Time: {dt_str}\n"
        "Use the current date above to determine relative time references "
        '(e.g., "today", "tomorrow", "yesterday", "this week", "last week") '
        "when answering questions about dates or match schedules."
    )


def format_player_context(identity: UserIdentity | None) -> str:
    """Format player identity for prompts that explicitly need personal context."""
    if not identity:
        return ""

    context_parts = []
    context_parts.append(f"The user asking this question is {identity.name}")

    if identity.status in ("RO", "IR", "AR", "RN"):  # Rostered statuses
        if identity.team and identity.franchise and identity.tier:
            context_parts.append(f", who plays for {identity.team} ({identity.franchise}) in the {identity.tier} tier")
    elif identity.status in ("FA", "DE", "PF", "PW"):  # Free agent statuses
        if identity.tier:
            context_parts.append(f", a free agent in the {identity.tier} tier")
        else:
            context_parts.append(", a free agent")

    context_parts.append(".")
    return "".join(context_parts)


def format_user_context(identity: UserIdentity | None, plan: RetrievalPlan) -> str:
    """Format only the user context allowed by the retrieval plan."""
    policy = build_prompt_context_policy(plan)
    context_parts = []

    if policy.include_current_datetime:
        context_parts.append(format_time_context(identity))

    if policy.include_player_identity:
        context_parts.append(format_player_context(identity))

    return "\n\n".join(part for part in context_parts if part)


def build_prompt_guidance(plan: RetrievalPlan) -> str:
    """Return intent-specific guidance for the final answer prompt."""
    if plan.intent is QueryIntent.RULES:
        return (
            "This is a rules-oriented question. Use rulebook, help, dates, and season context as the authority. "
            "Do not personalize the answer or infer facts about the asking player unless the question explicitly asks you "
            "to apply the rule to them."
        )

    if plan.include_user_context:
        return (
            "Use the user identity context only to resolve personal references such as I, me, my, my team, or my franchise. "
            "Do not let identity context override retrieved RSC source context."
        )

    if plan.include_current_date:
        return "Use date/time context only for relative date references. Do not personalize the answer."

    return "Do not personalize the answer unless the retrieved context and the question require it."


def clean_question(text: str, user_name: str, bot_name: str | None = None) -> str:
    """
    Clean and normalize a question by substituting pronouns with actual names.

    Args:
        text: The question text to clean
        user_name: The name to substitute for first-person pronouns (I, me, my, etc.)
        bot_name: The name to substitute for second-person pronouns (you, your, etc.)

    Returns:
        Cleaned question with pronouns replaced
    """
    cleaned = text

    # First-person pronouns (referring to the user)
    # Handle contractions first (I'm, I've, I'd, I'll)
    cleaned = re.sub(r"\bI'?m\b", f"{user_name} is", cleaned, flags=re.IGNORECASE)
    cleaned = re.sub(r"\bI'?ve\b", f"{user_name} has", cleaned, flags=re.IGNORECASE)
    cleaned = re.sub(r"\bI'?d\b", f"{user_name} would", cleaned, flags=re.IGNORECASE)
    cleaned = re.sub(r"\bI'?ll\b", f"{user_name} will", cleaned, flags=re.IGNORECASE)

    # Standard first-person pronouns
    cleaned = re.sub(r"\b(I|me)\b", user_name, cleaned, flags=re.IGNORECASE)
    cleaned = re.sub(r"\b(my|mine)\b", f"{user_name}'s", cleaned, flags=re.IGNORECASE)
    cleaned = re.sub(r"\bmyself\b", user_name, cleaned, flags=re.IGNORECASE)

    # Second-person pronouns (referring to the bot)
    if bot_name:
        cleaned = re.sub(r"\b(you|your|yours|yourself)\b", bot_name, cleaned, flags=re.IGNORECASE)

    return cleaned


# Template
PROMPT_TEMPLATE = """
You are a discord bot that runs a gaming league called RSC. The league is for the game Rocket League and is structured similar to the NFL.

{user_context}

{context_guidance}

You have access to the following retrieved context from RSC sources:

{context}

Use rulebook context as the authority for rules, eligibility, roster moves, conduct, and enforcement questions.
Use API context as the authority for live league state such as players, teams, franchises, matches, and season data.
Answer the question using the context provided above. If you can provide rule number references, do so.
Do not create your own acronyms.
If you cannot answer the question based on the context provided, say so clearly. Do not try to make assumptions.
Keep your response under 2000 characters for Discord compatibility.

Do NOT respond with anything that could be considered a discord bot command (e.g., starting with a "!" or "?").
"""

TICKET_SUMMARY_SYSTEM_PROMPT = """
You summarize private Discord support tickets for league staff.

Given a ticket transcript, produce a concise, factual summary with these sections:
1) Issue
2) Key Timeline
3) Actions Taken
4) Current Status
5) Recommended Next Step

Requirements:
- Be neutral and avoid speculation.
- If details are uncertain, explicitly say what is unclear.
- Transcript markers like [image-1], [image-2], etc. map to the attached images in the same numeric order.
- Analyze image contents to gain additional context relevant to the ticket.
- Keep under 1500 characters.
- Do not output any bot command prefixes.
"""


def normalize_distances(
    docs: list[tuple[Document, float]],
) -> list[tuple[Document, float, float]]:
    """
    Convert raw distances into normalized relevance scores (0-1).
    Higher score = more relevant.
    """
    distances = [d for _, d in docs]
    min_d, max_d = min(distances), max(distances)

    def normalize(d: float) -> float:
        if max_d == min_d:
            return 1.0
        return 1 - ((d - min_d) / (max_d - min_d))

    return [(doc, dist, normalize(dist)) for doc, dist in docs]


def deduplicate_documents(
    scored: list[tuple[Document, float, float]],
) -> list[tuple[Document, float, float]]:
    """
    Remove duplicate chunks from the same document.
    """
    seen = set()
    deduped = []

    for doc, distance, score in sorted(scored, key=lambda x: x[2], reverse=True):
        key = (
            doc.metadata.get("source"),
            doc.metadata.get("id") or doc.id,
            doc.metadata.get("chunk_index"),
        )
        log.debug("Inspecting document chunk for deduplication: %s", key)
        if key in seen:
            log.debug(f"Deduplicating document chunk: {key}")
            continue

        seen.add(key)
        deduped.append((doc, distance, score))

    return deduped


def apply_dynamic_cutoff(
    docs: list[tuple[Document, float, float]],
    ratio: float = DYNAMIC_CUTOFF,
) -> list[tuple[Document, float, float]]:
    """
    Keep only documents close to the best match.
    """
    if not docs:
        return []

    sorted_docs = sorted(docs, key=lambda x: x[2], reverse=True)
    top_score = sorted_docs[0][2]

    filtered = [d for d in sorted_docs if d[2] >= top_score * ratio]
    log.debug("Dynamic cutoff at %.2f: kept %d of %d documents", ratio, len(filtered), len(docs))

    return filtered or sorted_docs[:1]


def build_context(
    docs: list[tuple[Document, float, float]],
) -> tuple[str, list[dict[str, str | int | None]]]:
    """
    Assemble final prompt context and source list with full metadata.

    Returns:
        Tuple of (context_string, list of metadata dicts with source, id, etc.)
    """
    context = "\n\n---\n\n".join(
        f"[Source Type: {document_source(doc) or 'unknown'} | Relevance {score:.2f}]\n{doc.page_content}" for doc, _distance, score in docs
    )

    sources = [
        {
            "source": doc.metadata.get("source"),
            "id": doc.metadata.get("id"),
            "chunk_index": doc.metadata.get("chunk_index"),
            "source_type": document_source(doc),
        }
        for doc, _distance, _score in docs
    ]

    return context, sources


async def expand_context_from_anchors(
    anchors: list[Document],
    llm_db: Chroma,
    question: str,
    plan: RetrievalPlan,
    top_n: int = 3,
    min_score: float = ANCHOR_EXPANSION_MIN_SCORE,
) -> list[tuple[Document, float, float]]:
    """
    Given high-confidence anchors, fetch related chunks from Chroma to expand context.

    Uses a combined query of the original question and anchor content to find
    contextually relevant adjacent information.
    """
    if not anchors:
        return []

    extra_docs: list[tuple[Document, float]] = []
    seen_ids: set[str] = set()

    # Add original question as an anchor
    question_anchor = Document(
        page_content=question,
        metadata={"source": "query_anchor"},
    )

    anchors = [*anchors, question_anchor]

    # Track anchor IDs to avoid re-adding them
    for anchor in anchors:
        if anchor.id:
            seen_ids.add(anchor.id)

    for anchor in anchors:
        source = anchor.metadata.get("source", "")

        # Create a more targeted query combining question context with anchor source

        log.debug(f"Expanding context from anchor. source={source} ID={anchor.id}")

        # Search with the combined query for better relevance
        similar: list[tuple[Document, float]] = []
        for source in plan.target_sources:
            similar.extend(await _similarity_search_with_source(llm_db, anchor.page_content, top_n, source=source))

        for doc, distance in similar:
            # Skip if we've already seen this document
            if doc.id and doc.id in seen_ids:
                continue
            if doc.id:
                seen_ids.add(doc.id)
            extra_docs.append((doc, distance))

    if not extra_docs:
        return []

    # Normalize and filter by minimum score
    scored = normalize_distances(extra_docs)

    # Filter out low-confidence expansions
    filtered = [(doc, dist, score) for doc, dist, score in scored if score >= min_score]

    log.debug(f"Anchor expansion: {len(extra_docs)} candidates, {len(filtered)} passed min_score={min_score}")

    return filtered


async def llm_query(
    guild: discord.Guild,
    org_name: str,
    api_key: str,
    question: str,
    threshold: float = 0.4,
    count: int = 5,
    model: str = OPENAI_CHAT_MODEL,
    user_identity: UserIdentity | None = None,
) -> tuple[str | None, list[dict[str, str | int | None]]]:
    """
    Query the LLM with context from ChromaDB.

    Args:
        guild: Discord guild for logging
        org_name: OpenAI organization name
        api_key: OpenAI API key
        question: User's question
        threshold: Minimum similarity score (0-1)
        count: Maximum number of documents to retrieve
        model: OpenAI model to use
        user_identity: Optional identity of the user asking the question

    Returns:
        Tuple of (response_text, source_list)
    """
    log.debug(f"Querying chroma db. Count={count} Threshold={threshold}", guild=guild)

    http_client = httpx.AsyncClient()
    secret_key = SecretStr(api_key)

    try:
        # Load DB with proper tenant/database structure
        chroma_client = chromadb.PersistentClient(
            path=str(CHROMA_PATH),
            tenant=chromadb.config.DEFAULT_TENANT,
            database=chromadb.config.DEFAULT_DATABASE,
        )
        llm_db = Chroma(
            collection_name=str(guild.id),
            client=chroma_client,
            embedding_function=OpenAIEmbeddings(
                model=OPENAI_EMBEDDING_MODEL, organization=org_name, api_key=secret_key, http_async_client=http_client
            ),
        )

        retrieval_plan = build_retrieval_plan(question, user_identity)
        search_queries = build_search_queries(question, user_identity, retrieval_plan)
        search_query = search_queries[0]

        # Search the DB with distance scores (lower is better)
        log.debug(f"Retrieval intent: {retrieval_plan.intent.value}", guild=guild)
        log.debug(f"Retrieval document sources: {[source.value for source in retrieval_plan.target_sources]}", guild=guild)
        log.debug(f"Search Query: {search_query}", guild=guild)
        if len(search_queries) > 1:
            log.debug(f"Search Query Rewrites: {search_queries[1:]}", guild=guild)
        similar = await retrieve_documents(llm_db, search_query, retrieval_plan, count)

        if not similar:
            log.debug("Unable to find matching results.", guild=guild)
            return (None, [])

        log.debug(f"Similar result count: {len(similar)}", guild=guild)

        # Retrieval pipeline
        scored = normalize_distances(similar)

        for doc, distance, score in scored:
            log.debug(
                f"Normalized score={score:.3f} Distance={distance:.4f} source={doc.metadata.get('source')}",
                guild=guild,
            )
            log.debug(f"Document content: {doc.page_content[:100]}", guild=guild)

        # Identify high-confidence anchors (>= 0.95 Default)
        anchors = [doc for doc, _, score in scored if score >= ANCHOR_SCORE_THRESHOLD]
        extra_context_docs = await expand_context_from_anchors(anchors, llm_db, question=question, plan=retrieval_plan, top_n=3)
        log.debug(f"Expanded {len(extra_context_docs)} extra context documents from anchors.", guild=guild)
        if extra_context_docs:
            for extra_doc, distance, score in extra_context_docs:
                log.debug(
                    f"Extra context score={score:.3f} Distance={distance:.4f} source={extra_doc.metadata.get('source')}",
                    guild=guild,
                )
                log.debug(f"Extra context content: {extra_doc.page_content[:100]}", guild=guild)
            scored.extend(extra_context_docs)

        # Continue pipeline
        deduped = deduplicate_documents(scored)
        prioritized = prioritize_documents(deduped, retrieval_plan)
        thresholded = [doc for doc in prioritized if doc[2] >= threshold]
        final_docs = apply_dynamic_cutoff(thresholded or prioritized[:count])[:count]
        final_docs = ensure_source_coverage(final_docs, prioritized, retrieval_plan, count)

        for doc, distance, score in final_docs:
            log.debug(
                f"Final score={score:.3f} distance={distance:.4f} source={doc.metadata.get('source')}",
                guild=guild,
            )

        context_text, sources = build_context(final_docs)
        log.debug(f"Context: {context_text}", guild=guild)

        user_context = format_user_context(user_identity, retrieval_plan)
        context_guidance = build_prompt_guidance(retrieval_plan)
        log.debug(
            "Prompt context policy: include_player_identity=%s include_current_datetime=%s",
            retrieval_plan.include_user_context,
            retrieval_plan.include_current_date,
            guild=guild,
        )
        prompt = PROMPT_TEMPLATE.format(
            context=context_text,
            user_context=user_context,
            context_guidance=context_guidance,
        )

        messages: list[ChatCompletionMessageParam] = [
            {"role": "system", "content": prompt},
            {"role": "user", "content": question},
        ]

        llm = AsyncOpenAI(
            organization=org_name,
            api_key=api_key,
            http_client=http_client,
        )

        response = await llm.chat.completions.create(
            messages=messages,
            **openai_chat_completion_options(model),
        )

        response_text = response.choices[0].message.content

        if not response_text:
            return (None, [])

        log.debug(f"LLM Response: {response_text}", guild=guild)

        if len(response_text) > 2000:
            return ("Sorry, that response is too long for me to put in Discord.", [])

        return (response_text, sources)
    finally:
        await http_client.aclose()


async def summarize_ticket_messages(
    guild: discord.Guild,
    org_name: str,
    api_key: str,
    transcript: str,
    image_data_urls: list[str] | None = None,
    model: str = OPENAI_CHAT_MODEL,
) -> str | None:
    """Summarize a ticket transcript for Discord output."""
    if not transcript.strip():
        return None

    http_client = httpx.AsyncClient()

    try:
        llm = AsyncOpenAI(
            organization=org_name,
            api_key=api_key,
            http_client=http_client,
        )

        user_content: list[dict[str, Any]] = [{"type": "text", "text": transcript}]
        if image_data_urls:
            user_content.extend(
                [{"type": "image_url", "image_url": {"url": image_data_url, "detail": "high"}} for image_data_url in image_data_urls]
            )

        messages = [
            {"role": "system", "content": TICKET_SUMMARY_SYSTEM_PROMPT},
            {"role": "user", "content": user_content},
        ]

        response = await llm.chat.completions.create(
            messages=cast("Any", messages),
            **openai_chat_completion_options(model),
        )

        response_text = response.choices[0].message.content
        if not response_text:
            return None

        response_text = response_text.strip()
        if len(response_text) > 2000:
            response_text = response_text[:1997].rstrip() + "..."

        log.debug("Generated ticket summary output.", guild=guild)
        return response_text
    finally:
        await http_client.aclose()


# if __name__ == "__main__":
#     import argparse
#     from dotenv import load_dotenv, find_dotenv
#     loop = asyncio.get_event_loop()

#     # Create CLI
#     parser = argparse.ArgumentParser(description="Ask the RSC LLM a question")
#     parser.add_argument("question", type=str, help="Question to ask the LLM")
#     argv = parser.parse_args()

#     if not argv.question:
#         print("No question provided")
#         sys.exit(1)

#     # Env
#     env_file = find_dotenv()
#     print(f"Env Location: {env_file}")
#     env_loaded = load_dotenv(find_dotenv())
#     print(f"Env loaded: {env_loaded}")

#     # Org
#     org = os.environ.get("OPENAI_API_ORG")
#     key = os.environ.get("OPENAI_API_KEY")

#     if not (org and key):
#         print("OpenAI org and or key are not configured.")
#         sys.exit(1)

#     response, sources = loop.run_until_complete(
#         llm_query(org_name=org, api_key=key, question=argv.question)
#     )

#     if not response:
#         print("No response available.")
#         sys.exit(1)

#     print(f"Sources: {sources}\n")
#     print(f"Question: {argv.question}\n")
#     print(f"Response: {response}\n")
