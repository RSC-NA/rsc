#!/usr/bin/env python3

# sql overrides - MUST happen before importing chromadb
import sys

__import__("pysqlite3")
sys.modules["sqlite3"] = sys.modules.pop("pysqlite3")

import logging  # noqa: E402
import re  # noqa: E402
from dataclasses import dataclass  # noqa: E402
from pathlib import Path  # noqa: E402

import chromadb  # noqa: E402
import discord  # noqa: E402
import httpx  # noqa: E402

from openai import AsyncOpenAI  # noqa: E402
from langchain_chroma import Chroma  # noqa: E402
from langchain_openai.embeddings import OpenAIEmbeddings  # noqa: E402
from langchain_core.documents import Document  # noqa: E402
from pydantic.types import SecretStr  # noqa: E402

from rsc.logs import GuildLogAdapter  # noqa: E402


logger = logging.getLogger("red.rsc.llm.query")
log = GuildLogAdapter(logger)

# Disable Loggers
logging.getLogger("chromadb").setLevel(logging.ERROR)
logging.getLogger("httpcore").setLevel(logging.ERROR)
logging.getLogger("httpx").setLevel(logging.ERROR)
logging.getLogger("openai").setLevel(logging.ERROR)
logging.getLogger("urllib3").setLevel(logging.ERROR)

# Prepare the DB.
CHROMA_PATH = Path(__file__).parent / "db"
CHROMA_PATH_ABS = CHROMA_PATH.absolute()

# Constants
ANCHOR_SCORE_THRESHOLD = 0.95
ANCHOR_EXPANSION_MIN_SCORE = 0.5  # Minimum score for expanded context
OPENAI_TEMPERATURE = 0.3
DYNAMIC_CUTOFF = 0.65


# User Identity
@dataclass
class UserIdentity:
    """Identity information for the user asking the question."""

    name: str
    team: str | None = None
    franchise: str | None = None
    tier: str | None = None
    status: str | None = None


def format_user_context(identity: UserIdentity | None) -> str:
    """Format user identity for inclusion in the system prompt."""
    if not identity:
        return ""

    context_parts = [f"The user asking this question is {identity.name}"]

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
You have access to the following context from the RSC rulebooks, team information, and player information:

{context}

Answer the question using the context provided above. If you can provide rule number references, do so.
Do not create your own acronyms.
If you cannot answer the question based on the context provided, say so clearly. Do not try to make assumptions"
Keep your response under 2000 characters for Discord compatibility.

Do NOT respond with anything that could be considered a discord bot command (e.g., starting with a "!" or "?").
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
            doc.id,
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
) -> tuple[str, list[str | None]]:
    """
    Assemble final prompt context and source list.
    """
    context = "\n\n---\n\n".join(f"[Relevance {score:.2f}]\n{doc.page_content}" for doc, _distance, score in docs)

    sources = [doc.metadata.get("source") for doc, _distance, _score in docs]

    return context, sources


async def expand_context_from_anchors(
    anchors: list[Document],
    llm_db: Chroma,
    question: str,
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
        similar = await llm_db.asimilarity_search_with_score(
            anchor.page_content,
            k=top_n,
        )

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
    model: str = "gpt-5.2",
    user_identity: UserIdentity | None = None,
) -> tuple[str | None, list[str | None]]:
    """
    Query the LLM with context from ChromaDB.

    Args:
        guild: Discord guild for logging
        org_name: OpenAI organization name
        api_key: OpenAI API key
        question: User's question
        threshold: Minimum similarity score (0-1)
        count: Maximum number of documents to retrieve
        model: OpenAI model to use (default: gpt-4o)
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
                model="text-embedding-3-small", organization=org_name, api_key=secret_key, http_async_client=http_client
            ),
        )

        # Add date context for match-related questions
        if "match" in question.lower():
            log.debug("Question appears to be match-related.", guild=guild)
            question += f"\nDate: {discord.utils.utcnow().date().strftime('%m-%d-%Y')}"

        # Search the DB with distance scores (lower is better)
        log.debug(f"Initial Question: {question}", guild=guild)
        similar = await llm_db.asimilarity_search_with_score(question, k=count)

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
        extra_context_docs = await expand_context_from_anchors(anchors, llm_db, question=question, top_n=3)
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
        final_docs = apply_dynamic_cutoff(deduped)

        for doc, distance, score in final_docs:
            log.debug(
                f"Final score={score:.3f} distance={distance:.4f} source={doc.metadata.get('source')}",
                guild=guild,
            )

        context_text, sources = build_context(final_docs)
        log.debug(f"Context: {context_text}", guild=guild)

        # Prompt with optional user context
        user_context = format_user_context(user_identity)
        prompt = PROMPT_TEMPLATE.format(context=context_text, user_context=user_context)

        messages = [
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
            model=model,
            temperature=0.3,
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
