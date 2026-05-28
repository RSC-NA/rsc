from datetime import UTC, datetime

import pytest
from langchain_core.documents import Document

from rsc.llm.query import (
    QueryIntent,
    RetrievalPlan,
    UserIdentity,
    build_context,
    build_prompt_guidance,
    build_retrieval_plan,
    build_search_queries,
    build_search_query,
    deduplicate_documents,
    ensure_source_coverage,
    format_user_context,
    prioritize_documents,
    retrieve_documents,
)
from rsc.llm.sources import DocumentSource


def user_identity() -> UserIdentity:
    return UserIdentity(
        name="nickm",
        team="Boost Hunters",
        franchise="Boost Club",
        tier="Elite",
        status="RO",
        current_datetime=datetime(2026, 5, 28, 12, tzinfo=UTC),
    )


def test_rule_questions_do_not_embed_player_context() -> None:
    identity = user_identity()
    plan = build_retrieval_plan("What are the roster change rules?", identity)
    search_query = build_search_query("What are the roster change rules?", identity, plan)

    assert plan.intent is QueryIntent.RULES
    assert plan.target_sources == (
        DocumentSource.RULEBOOK,
        DocumentSource.GLOSSARY,
        DocumentSource.HELP,
        DocumentSource.DATES,
        DocumentSource.SEASON,
    )
    assert not plan.include_user_context
    assert "Boost Hunters" not in search_query
    assert "Player: nickm" not in search_query


def test_rule_questions_do_not_put_player_context_in_prompt() -> None:
    identity = user_identity()
    plan = build_retrieval_plan("What are the roster change rules?", identity)

    user_context = format_user_context(identity, plan)
    guidance = build_prompt_guidance(plan)

    assert user_context == ""
    assert "rules-oriented" in guidance
    assert "Boost Hunters" not in guidance


def test_personal_team_questions_embed_player_context() -> None:
    identity = user_identity()
    plan = build_retrieval_plan("Who is my GM?", identity)
    search_query = build_search_query("Who is my GM?", identity, plan)

    assert plan.intent is QueryIntent.PLAYER
    assert plan.include_user_context
    assert "Team: Boost Hunters" in search_query
    assert "Franchise: Boost Club" in search_query
    assert "Player: nickm" in search_query
    assert "Who is nickm's GM?" in search_query


def test_player_stat_questions_search_player_stats() -> None:
    identity = user_identity()
    plan = build_retrieval_plan("How many goals do I have?", identity)

    assert plan.intent is QueryIntent.PLAYER
    assert DocumentSource.PLAYER_STATS in plan.target_sources
    assert plan.source_priority[0] is DocumentSource.PLAYER_STATS
    assert plan.required_sources == (DocumentSource.PLAYER_STATS,)
    assert plan.include_user_context


def test_my_stats_questions_prioritize_player_stats_over_profile_context() -> None:
    identity = user_identity()
    plan = build_retrieval_plan("what are my stats?", identity)
    search_queries = build_search_queries("what are my stats?", identity, plan)

    assert plan.intent is QueryIntent.PLAYER
    assert plan.target_sources[:3] == (DocumentSource.PLAYER_STATS, DocumentSource.PLAYERS, DocumentSource.TEAMS)
    assert plan.required_sources == (DocumentSource.PLAYER_STATS,)
    assert "Player: nickm" in search_queries[0]
    assert any("nickm player stats goals assists saves shots points" in query for query in search_queries)


def test_team_stat_questions_search_team_stats_and_standings() -> None:
    identity = user_identity()
    plan = build_retrieval_plan("What is the Boost Hunters record and stats?", identity)

    assert plan.intent is QueryIntent.TEAM
    assert plan.source_priority[0] is DocumentSource.TEAM_STATS
    assert DocumentSource.TEAM_STATS in plan.target_sources
    assert DocumentSource.STANDINGS in plan.target_sources
    assert plan.required_sources == (DocumentSource.TEAM_STATS,)


def test_personal_team_questions_put_player_context_in_prompt() -> None:
    identity = user_identity()
    plan = build_retrieval_plan("Who is my GM?", identity)

    user_context = format_user_context(identity, plan)

    assert "nickm" in user_context
    assert "Boost Hunters" in user_context
    assert "Boost Club" in user_context


def test_match_questions_embed_current_date() -> None:
    identity = user_identity()
    plan = build_retrieval_plan("When is my next match?", identity)
    search_query = build_search_query("When is my next match?", identity, plan)

    assert plan.intent is QueryIntent.MATCH
    assert plan.include_current_date
    assert "Current Date: 05-28-2026" in search_query


def test_non_personal_match_questions_put_date_but_not_player_context_in_prompt() -> None:
    identity = user_identity()
    plan = build_retrieval_plan("When are matches today?", identity)

    user_context = format_user_context(identity, plan)

    assert plan.intent is QueryIntent.MATCH
    assert plan.include_current_date
    assert not plan.include_user_context
    assert "Current Date and Time" in user_context
    assert "Boost Hunters" not in user_context
    assert "The user asking" not in user_context


def test_rule_question_with_personal_word_keeps_retrieval_query_unpersonalized() -> None:
    identity = user_identity()
    plan = build_retrieval_plan("Can I be drafted under the rules?", identity)
    search_query = build_search_query("Can I be drafted under the rules?", identity, plan)

    assert plan.intent is QueryIntent.RULES
    assert not plan.include_user_context
    assert "Can I be drafted under the rules?" in search_query
    assert "nickm" not in search_query
    assert "Boost Hunters" not in search_query


@pytest.mark.parametrize(
    ("question", "expected_terms"),
    [
        ("How many days can I sub in a row?", ("substitute", "consecutive", "match days")),
        ("How many days can I sub in for a team in a row?", ("same team", "two match days")),
        ("Can I sub for the same franchise twice?", ("same franchise", "two times")),
        (
            "How many consecutive match days can a player be subbed out?",
            ("substituted off", "more than two consecutive match days"),
        ),
    ],
)
def test_colloquial_substitution_questions_route_to_rulebook(question: str, expected_terms: tuple[str, ...]) -> None:
    identity = user_identity()
    plan = build_retrieval_plan(question, identity)
    search_queries = build_search_queries(question, identity, plan)
    combined_queries = "\n".join(search_queries).lower()

    assert plan.intent is QueryIntent.RULES
    assert DocumentSource.RULEBOOK in plan.target_sources
    assert DocumentSource.GLOSSARY in plan.target_sources
    assert DocumentSource.RULEBOOK is plan.source_priority[0]
    assert not plan.include_user_context
    assert len(search_queries) > 1
    assert "Player: nickm" not in combined_queries
    assert "Boost Hunters" not in combined_queries
    for expected_term in expected_terms:
        assert expected_term in combined_queries


@pytest.mark.asyncio
async def test_rule_retrieval_does_not_search_player_or_team_sources() -> None:
    class FakeChroma:
        def __init__(self) -> None:
            self.filters: list[dict[str, str] | None] = []

        async def asimilarity_search_with_score(
            self,
            query: str,
            k: int,
            filter: dict[str, str] | None = None,
        ) -> list[tuple[Document, float]]:
            self.filters.append(filter)
            return []

    identity = user_identity()
    plan = build_retrieval_plan("What are the roster change rules?", identity)
    fake_chroma = FakeChroma()

    await retrieve_documents(fake_chroma, "What are the roster change rules?", plan, count=5)

    searched_sources = {source_filter["source_type"] for source_filter in fake_chroma.filters if source_filter}
    assert DocumentSource.PLAYERS.value not in searched_sources
    assert DocumentSource.TEAMS.value not in searched_sources
    assert searched_sources == {source.value for source in plan.target_sources}


@pytest.mark.parametrize(
    "question",
    [
        "What are the roster change rules?",
        "Who is my GM?",
        "When is my next match?",
        "Which franchise has this prefix?",
        "What is the current season?",
        "Tell me about RSC.",
    ],
)
def test_glossary_is_available_to_all_retrieval_plans(question: str) -> None:
    plan = build_retrieval_plan(question, user_identity())

    assert DocumentSource.GLOSSARY in plan.target_sources


@pytest.mark.asyncio
async def test_rule_retrieval_searches_rewrite_variants() -> None:
    class FakeChroma:
        def __init__(self) -> None:
            self.queries: list[str] = []

        async def asimilarity_search_with_score(
            self,
            query: str,
            k: int,
            filter: dict[str, str] | None = None,
        ) -> list[tuple[Document, float]]:
            self.queries.append(query)
            return []

    plan = build_retrieval_plan("How many days can I sub in a row?", user_identity())
    fake_chroma = FakeChroma()

    await retrieve_documents(fake_chroma, "How many days can I sub in a row?", plan, count=5)

    assert any("substitute substitution consecutive match days" in query for query in fake_chroma.queries)


def test_deduplicate_documents_uses_metadata_id() -> None:
    first = Document(page_content="first", metadata={"source": "Rules", "id": "1.1", "chunk_index": 0})
    second = Document(page_content="second", metadata={"source": "Rules", "id": "1.2", "chunk_index": 1})
    duplicate = Document(page_content="duplicate", metadata={"source": "Rules", "id": "1.1", "chunk_index": 0})

    deduped = deduplicate_documents([(first, 0.1, 1.0), (second, 0.2, 0.9), (duplicate, 0.3, 0.8)])

    assert [doc.metadata["id"] for doc, _distance, _score in deduped] == ["1.1", "1.2"]


def test_rule_priority_can_outrank_player_context() -> None:
    plan = RetrievalPlan(
        intent=QueryIntent.RULES,
        target_sources=(DocumentSource.RULEBOOK, DocumentSource.PLAYERS),
        source_priority=(DocumentSource.RULEBOOK, DocumentSource.PLAYERS),
    )
    rule_doc = Document(page_content="rule", metadata={"source_type": "rulebook", "source": "RSC Rules", "id": "1.1"})
    player_doc = Document(page_content="player", metadata={"source_type": "players", "source": "Players API", "id": "99"})

    prioritized = prioritize_documents([(player_doc, 0.1, 0.88), (rule_doc, 0.2, 0.78)], plan)

    assert prioritized[0][0] is rule_doc


def test_rule_source_coverage_keeps_rulebook_candidate() -> None:
    plan = RetrievalPlan(
        intent=QueryIntent.RULES,
        target_sources=(DocumentSource.RULEBOOK, DocumentSource.HELP),
        source_priority=(DocumentSource.RULEBOOK, DocumentSource.HELP),
        required_sources=(DocumentSource.RULEBOOK,),
    )
    help_doc = Document(page_content="help", metadata={"source_type": "help", "source": "Help", "id": "help"})
    rule_doc = Document(page_content="rule", metadata={"source_type": "rulebook", "source": "Rules", "id": "5.6.3.2"})

    selected = [(help_doc, 0.1, 1.0)]
    candidates = [(help_doc, 0.1, 1.0), (rule_doc, 0.2, 0.7)]
    final_docs = ensure_source_coverage(selected, candidates, plan, count=1)

    assert final_docs[0][0] is rule_doc


def test_stats_source_coverage_keeps_player_stats_candidate() -> None:
    plan = RetrievalPlan(
        intent=QueryIntent.PLAYER,
        target_sources=(DocumentSource.PLAYER_STATS, DocumentSource.PLAYERS),
        source_priority=(DocumentSource.PLAYER_STATS, DocumentSource.PLAYERS),
        required_sources=(DocumentSource.PLAYER_STATS,),
    )
    player_doc = Document(page_content="profile", metadata={"source_type": "players", "source": "Players API", "id": "nickm"})
    stats_doc = Document(
        page_content="stats",
        metadata={"source_type": "player_stats", "source": "Player Stats API", "id": "stats:nickm"},
    )

    selected = [(player_doc, 0.1, 1.0)]
    candidates = [(player_doc, 0.1, 1.0), (stats_doc, 0.2, 0.7)]
    final_docs = ensure_source_coverage(selected, candidates, plan, count=1)

    assert final_docs[0][0] is stats_doc


def test_build_context_includes_source_type_and_sources() -> None:
    doc = Document(
        page_content="Rule text",
        metadata={"source_type": "rulebook", "source": "RSC Rules: 1.1", "id": "1.1", "chunk_index": 0},
    )

    context, sources = build_context([(doc, 0.1, 1.0)])

    assert "Source Type: rulebook" in context
    assert sources == [{"source": "RSC Rules: 1.1", "id": "1.1", "chunk_index": 0, "source_type": "rulebook"}]
