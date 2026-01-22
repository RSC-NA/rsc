#!/usr/bin/env python3

import logging
import sys
from pathlib import Path

import discord
import httpx

from openai import AsyncOpenAI
from langchain_chroma import Chroma
from langchain_openai.embeddings import OpenAIEmbeddings
from langchain_core.documents import Document
from pydantic.types import SecretStr

from rsc.logs import GuildLogAdapter


logger = logging.getLogger("red.rsc.llm.query")
log = GuildLogAdapter(logger)

# Disable Loggers
logging.getLogger("chromadb").setLevel(logging.ERROR)
logging.getLogger("httpcore").setLevel(logging.ERROR)
logging.getLogger("httpx").setLevel(logging.ERROR)
logging.getLogger("openai").setLevel(logging.ERROR)
logging.getLogger("urllib3").setLevel(logging.ERROR)


# sql overrides

__import__("pysqlite3")
sys.modules["sqlite3"] = sys.modules.pop("pysqlite3")

# Prepare the DB.
CHROMA_PATH = Path(__file__).parent / "db"
CHROMA_PATH_ABS = CHROMA_PATH.absolute()


# Template
PROMPT_TEMPLATE = """
You are a discord bot that runs a gaming league called RSC. The league is for the game Rocket League and is structured similar to the NFL.

You have access to the following context from the RSC rulebooks, team information, and player information:

{context}

Answer the question using the context provided above. Do not create your own acronyms.
If you cannot answer the question based on the context provided, say so clearly.
Keep your response under 2000 characters for Discord compatibility.

Do NOT respond with anything that could be considered a discord bot command (e.g., starting with a "!" or "?").
"""


def normalize_distances(
    docs: list[tuple["Document", float]],
) -> list[tuple["Document", float, float]]:
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
    scored: list[tuple["Document", float, float]],
) -> list[tuple["Document", float, float]]:
    """
    Remove duplicate chunks from the same document.
    """
    seen = set()
    deduped = []

    for doc, distance, score in sorted(scored, key=lambda x: x[2], reverse=True):
        key = (
            doc.metadata.get("source"),
            doc.metadata.get("document_id"),
        )
        log.debug("Inspecting document chunk for deduplication: %s - %s", key, doc.metadata.get("chunk_index"))
        if key in seen:
            log.debug(f"Deduplicating document chunk: {key}")
            continue

        seen.add(key)
        deduped.append((doc, distance, score))

    return deduped


def merge_sequential_chunks(
    docs: list[tuple[Document, float, float]],
) -> list[dict]:
    """
    Merge adjacent chunks into larger context blocks.
    """
    merged: list[list[tuple[Document, float]]] = []
    buffer: list[tuple[Document, float]] = []

    log.debug(f"Merging {len(docs)} documents into sequential chunks")
    for doc, _distance, score in docs:
        idx = doc.metadata.get("chunk_index")
        source = doc.metadata.get("source", "unknown")

        if buffer and idx is not None and buffer[-1][0].metadata.get("chunk_index") == idx - 1:
            log.debug(f"Merging chunk {idx} from {source} into buffer")
            buffer.append((doc, score))
        else:
            if buffer:
                log.debug(f"Finalizing merged group with {len(buffer)} chunks from {buffer[0][0].metadata.get('source')}")
                merged.append(buffer)
            log.debug(f"Starting new buffer with chunk {idx} from {source}")
            buffer = [(doc, score)]

    if buffer:
        log.debug(f"Finalizing final merged group with {len(buffer)} chunks")
        merged.append(buffer)

    result = [
        {
            "content": "\n".join(d.page_content for d, _ in group),
            "score": max(score for _, score in group),
            "source": group[0][0].metadata.get("source"),
        }
        for group in merged
    ]

    log.debug(f"Merged into {len(result)} final document groups")
    return result


def apply_dynamic_cutoff(
    docs: list[dict],
    ratio: float = 0.65,
) -> list[dict]:
    """
    Keep only documents close to the best match.
    """
    if not docs:
        return []

    docs.sort(key=lambda x: x["score"], reverse=True)
    top_score = docs[0]["score"]

    filtered = [d for d in docs if d["score"] >= top_score * ratio]

    return filtered or docs[:1]


def build_context(
    docs: list[dict],
) -> tuple[str, list[str | None]]:
    """
    Assemble final prompt context and source list.
    """
    context = "\n\n---\n\n".join(f"[Relevance {doc['score']:.2f}]\n{doc['content']}" for doc in docs)

    sources = [doc["source"] for doc in docs]

    return context, sources


async def llm_query(
    guild: discord.Guild,
    org_name: str,
    api_key: str,
    question: str,
    threshold: float = 0.4,
    count: int = 5,
    model: str = "gpt-5.2",
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

    Returns:
        Tuple of (response_text, source_list)
    """
    log.debug(f"Querying chroma db. Count={count} Threshold={threshold}", guild=guild)

    http_client = httpx.AsyncClient()
    secret_key = SecretStr(api_key)

    try:
        # Load DB
        llm_db = Chroma(
            collection_name=str(guild.id),
            persist_directory=str(CHROMA_PATH),
            embedding_function=OpenAIEmbeddings(
                model="text-embedding-3-small", organization=org_name, api_key=secret_key, http_async_client=http_client
            ),
        )

        # Search the DB with distance scores (lower is better)
        similar = await llm_db.asimilarity_search_with_score(question, k=count)

        if not similar:
            log.debug("Unable to find matching results.", guild=guild)
            return (None, [])

        log.debug(f"Similar result count: {len(similar)}", guild=guild)

        for doc, distance in similar:
            log.debug(
                f"Doc source={doc.metadata.get('source')} distance={distance:.4f} ID={doc.id}",
                guild=guild,
            )
            log.debug(f"Doc content: {doc.page_content[:100]}", guild=guild)

        # Retrieval pipeline
        scored = normalize_distances(similar)

        for doc, distance, score in scored:
            log.debug(
                f"Normalized score={score:.3f} Distance={distance:.4f} source={doc.metadata.get('source')}",
                guild=guild,
            )

        deduped = deduplicate_documents(scored)
        merged = merge_sequential_chunks(deduped)
        final_docs = apply_dynamic_cutoff(merged)

        for doc in final_docs:
            log.debug(
                f"Final score={doc['score']:.3f} source={doc['source']}",
                guild=guild,
            )

        context_text, sources = build_context(final_docs)
        log.debug(f"Context: {context_text}", guild=guild)

        # Prompt
        prompt = PROMPT_TEMPLATE.format(context=context_text)

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
