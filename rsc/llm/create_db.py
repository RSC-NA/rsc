#!/usr/bin/env python3

import asyncio
import hashlib
import logging
import shutil
import sys
import tempfile
from collections.abc import Callable
from pathlib import Path

import discord
import httpx
from langchain.document_loaders.directory import DirectoryLoader
from langchain.vectorstores.chroma import Chroma
from langchain_community.document_loaders import JSONLoader
from langchain_core.documents import Document
from langchain_openai.embeddings import OpenAIEmbeddings
from langchain_text_splitters import MarkdownTextSplitter
from pydantic.v1.types import SecretStr
from rscapi.models.franchise_list import FranchiseList
from rscapi.models.league_player import LeaguePlayer
from rscapi.models.team import Team

from rsc.llm.loaders import (
    FranchiseDocumentLoader,
    PlayerDocumentLoader,
    RuleDocumentLoader,
    TeamDocumentLoader,
)
from rsc.logs import GuildLogAdapter

logger = logging.getLogger("red.rsc.llm.create")
log = GuildLogAdapter(logger)

# Disable Loggers
logging.getLogger("chromadb").setLevel(logging.ERROR)
logging.getLogger("httpcore").setLevel(logging.ERROR)
logging.getLogger("httpx").setLevel(logging.ERROR)
logging.getLogger("langchain_community").setLevel(logging.ERROR)
logging.getLogger("MARKDOWN").setLevel(logging.ERROR)
logging.getLogger("openai").setLevel(logging.ERROR)
logging.getLogger("unstructured").setLevel(logging.ERROR)
logging.getLogger("urllib3").setLevel(logging.ERROR)

# sql overrides

__import__("pysqlite3")
sys.modules["sqlite3"] = sys.modules.pop("pysqlite3")

# Paths

CHROMA_PATH = Path(__file__).parent / "db"


async def load_funny_docs() -> list[Document]:
    log.debug("Loading funny documents")
    fpath = Path(__file__).parent.parent / "resources" / "funny"
    loader = DirectoryLoader(str(fpath), glob="*.md")
    documents = loader.load()
    for d in documents:
        d.metadata["source"] = "Funny"
    return documents


async def string_to_doc(text: str) -> Document:
    return Document(page_content=text)


async def load_help_docs() -> list[Document]:
    log.debug("Loading help documents")
    fpath = Path(__file__).parent.parent / "resources" / "help"
    loader = DirectoryLoader(str(fpath), glob="*.md")
    documents = loader.load()
    for d in documents:
        src = Path(d.metadata["source"])
        d.metadata["source"] = src.stem.capitalize()
    return documents


async def load_rule_style_docs(file: str | Path) -> list[Document]:
    documents = []
    loader = RuleDocumentLoader(str(file))
    async for doc in loader.alazy_load():
        log.debug(f"Document: {doc.page_content}")
        log.debug(f"Document Source: {doc.metadata}")
        documents.append(doc)
    return documents


async def markdown_to_documents(docs: list[Document]) -> list[Document]:
    md_splitter = MarkdownTextSplitter()
    return md_splitter.split_documents(docs)


def franchise_metadata(record: dict, metadata: dict):
    log.debug(f"Metadata: {metadata}")
    metadata["source"] = "API"
    return metadata


async def json_to_docs(data: str, jq_schema: str, metadata_func: Callable | None) -> list[Document]:
    with tempfile.NamedTemporaryFile() as fd:
        if isinstance(data, str):
            fd.write(data.encode("utf-8"))
        elif isinstance(data, bytes):
            fd.write(data)
        else:
            raise TypeError("JSON data must be str or bytes")
        loader = JSONLoader(
            file_path=fd.name,
            jq_schema=jq_schema,
            text_content=False,
            metadata_func=franchise_metadata,
        )
        chunks = loader.load()

    return chunks


async def load_franchise_docs(franchises: list[FranchiseList]):
    documents = []
    loader = FranchiseDocumentLoader(franchises)
    async for doc in loader.alazy_load():
        log.debug(f"Document: {doc.page_content}")
        log.debug(f"Document Source: {doc.metadata}")
        documents.append(doc)
    return documents


async def load_player_docs(players: list[LeaguePlayer]):
    documents = []
    loader = PlayerDocumentLoader(players)
    async for doc in loader.alazy_load():
        log.debug(f"Document: {doc.page_content}")
        log.debug(f"Document Source: {doc.metadata}")
        documents.append(doc)
    return documents


async def load_team_docs(teams: list[Team]):
    documents = []
    loader = TeamDocumentLoader(teams)
    async for doc in loader.alazy_load():
        log.debug(f"Document: {doc.page_content}")
        log.debug(f"Document Source: {doc.metadata}")
        documents.append(doc)
    return documents


async def generate_document_hashes(docs: list[Document]) -> list[str]:
    hashes = []
    for doc in docs:
        source = doc.metadata.get("source")
        api_id = doc.metadata.get("id")

        if source and api_id:
            ident = f"{source}/{api_id}"
        elif source:
            ident = f"{source}"
        elif api_id:
            log.warning(f"LLM Document has no source: {doc.page_content[:50]}")
            ident = f"{api_id}"
        else:
            log.warning(f"LLM Document has no metadata: {doc.page_content[:50]}")
            ident = doc.page_content

        hash = hashlib.sha256(ident.encode("utf-8")).hexdigest()
        hashes.append(hash)

    return hashes


async def create_chroma_db(guild: discord.Guild, org_name: str, api_key: str, docs: list[Document]):
    # Clear out the database first.
    await rm_chroma_db()

    # Create directory if needed
    if not CHROMA_PATH.absolute().exists():
        # Create brand new DB if it doesn't exist
        log.debug("Creating Chroma DB Directory", guild=guild)
        CHROMA_PATH.absolute().mkdir(parents=True, exist_ok=True)
        await asyncio.sleep(5)

    log.debug("Saving Chroma DB.", guild=guild)
    Chroma.from_documents(
        documents=docs,
        collection_name=str(guild.id),
        embedding=OpenAIEmbeddings(
            organization=org_name,
            api_key=SecretStr(api_key),
            async_client=httpx.AsyncClient(),
        ),
        persist_directory=str(CHROMA_PATH.absolute()),
    )
    log.info(f"Saved {len(docs)} chunks to {CHROMA_PATH}.", guild=guild)


async def rm_chroma_db():
    if CHROMA_PATH.exists() and CHROMA_PATH.is_dir() and CHROMA_PATH.name == "db":
        log.debug(f"Deleting Chroma DB directory: {CHROMA_PATH.absolute()}")
        shutil.rmtree(CHROMA_PATH.absolute())
        await asyncio.sleep(5)


# if __name__ == "__main__":
#     loop = asyncio.get_event_loop()

#     # Env
#     # envpath = Path(__file__).parent.parent.parent()
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

#     # Store
#     docs: list[Document] = []

#     # Read in Markdown documents
#     ruledocs = loop.run_until_complete(load_rule_docs())
#     helpdocs = loop.run_until_complete(load_help_docs())

#     for d in ruledocs:
#         print(f"Loaded Document: {d.metadata}")
#     for d in helpdocs:
#         print(f"Loaded Document: {d.metadata}")

#     markdown_docs = loop.run_until_complete(markdown_to_documents(ruledocs))
#     docs.extend(markdown_docs)
#     markdown_docs = loop.run_until_complete(markdown_to_documents(helpdocs))
#     docs.extend(markdown_docs)

#     loop.run_until_complete(create_chroma_db(org_name=org, api_key=key, docs=docs))
#     print("Chroma database created")
