#!/usr/bin/env python3

import logging
import sys
from pathlib import Path

import discord
import httpx
from langchain.prompts import ChatPromptTemplate
from langchain.vectorstores.chroma import Chroma
from langchain_core.documents import Document
from langchain_openai import ChatOpenAI
from langchain_openai.embeddings import OpenAIEmbeddings
from pydantic.v1.types import SecretStr

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

# LLM_DB = Chroma(
#     persist_directory=str(CHROMA_PATH), embedding_function=OpenAIEmbeddings()
# )

# Template

PROMPT_TEMPLATE = """
Answer the question based only on the following context:

{context}

---

Answer the question based on the above context, do not create your own acronyms: {question}
"""


async def llm_query(
    guild: discord.Guild,
    org_name: str,
    api_key: str,
    question: str,
    threshold: float = 0.65,
    count: int = 5,
) -> tuple[str | list | None, list[str | None]]:
    log.debug(f"Querying chroma db. Count={count} Threshold={threshold}", guild=guild)

    http_client = httpx.AsyncClient()

    secret_key = SecretStr(api_key)

    # Load DB
    llm_db = Chroma(
        collection_name=str(guild.id),
        persist_directory=str(CHROMA_PATH),
        embedding_function=OpenAIEmbeddings(
            organization=org_name, api_key=secret_key, async_client=http_client
        ),
    )

    if not llm_db:
        raise RuntimeError("Chroma DB does not exist")

    # Search the DB.
    similar = llm_db.similarity_search_with_relevance_scores(question, k=count)

    if not similar:
        log.debug("Unable to find matching results.", guild=guild)
        return (None, [])

    log.debug(f"Similar result count: {len(similar)}", guild=guild)

    results: list[tuple[Document, float]] = []
    for r in similar:
        log.debug(f"Result Threshold: {r[1]:.4f}", guild=guild)
        if r[1] > threshold and r not in results:
            results.append(r)

    if not results:
        log.debug("Unable to find matching results.", guild=guild)
        return (None, [])

    log.debug(f"Final Result count: {len(results)}", guild=guild)

    context_text = "\n\n---\n\n".join([doc.page_content for doc, _score in results])
    prompt_template = ChatPromptTemplate.from_template(PROMPT_TEMPLATE)
    prompt = prompt_template.format(context=context_text, question=question)
    log.debug(prompt)

    model = ChatOpenAI(
        organization=org_name, api_key=secret_key, async_client=http_client
    )
    response_text = model.invoke(prompt)

    await http_client.aclose()

    sources: list[str | None] = [doc.metadata.get("source") for doc, _score in results]
    if not response_text.content:
        return (None, [])
    log.debug(f"LLM Response: {response_text.content}", guild=guild)
    if len(response_text.content) > 2000:
        return ("Sorry that response is too long for me to put in discord.", [])

    return (response_text.content, sources)


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
