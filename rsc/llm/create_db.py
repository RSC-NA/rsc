#!/usr/bin/env python3

# sql overrides - MUST happen before importing chromadb
import sys

__import__("pysqlite3")
sys.modules["sqlite3"] = sys.modules.pop("pysqlite3")

import hashlib  # noqa: E402
import logging  # noqa: E402
import shutil  # noqa: E402
import tempfile  # noqa: E402
from collections.abc import Callable  # noqa: E402
from pathlib import Path  # noqa: E402

import chromadb  # noqa: E402
import discord  # noqa: E402
import httpx  # noqa: E402

from langchain_community.document_loaders.directory import DirectoryLoader  # noqa: E402
from langchain_community.vectorstores.chroma import Chroma  # noqa: E402
from langchain_community.document_loaders import JSONLoader  # noqa: E402
from langchain_core.documents import Document  # noqa: E402
from langchain_openai.embeddings import OpenAIEmbeddings  # noqa: E402
from langchain_text_splitters import MarkdownTextSplitter  # noqa: E402
from pydantic.types import SecretStr  # noqa: E402
from rscapi import MatchList  # noqa: E402
from rscapi.models.franchise_list import FranchiseList  # noqa: E402
from rscapi.models.league_player import LeaguePlayer  # noqa: E402
from rscapi.models.team import Team  # noqa: E402

from rsc.llm.loaders import FranchiseDocumentLoader, PlayerDocumentLoader, RuleDocumentLoader, TeamDocumentLoader, MatchDocumentLoader  # noqa: E402
from rsc.logs import GuildLogAdapter  # noqa: E402

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

# Paths

CHROMA_PATH = Path(__file__).parent / "db"


async def load_funny_docs() -> list[Document]:
    log.debug("Loading funny documents")
    fpath = Path(__file__).parent.parent / "resources" / "funny"
    loader = DirectoryLoader(str(fpath), glob="*.md")
    documents = await loader.aload()
    for d in documents:
        d.metadata["source"] = "Funny"
    return documents


async def string_to_doc(text: str) -> Document:
    return Document(page_content=text)


async def load_help_docs() -> list[Document]:
    log.debug("Loading help documents")
    fpath = Path(__file__).parent.parent / "resources" / "help"
    loader = DirectoryLoader(str(fpath), glob="*.md")
    documents = await loader.aload()
    for d in documents:
        src = Path(d.metadata["source"])
        d.metadata["source"] = src.stem.capitalize()
    return documents


async def load_rule_style_docs(file: str | Path) -> list[Document]:
    documents = []
    loader = RuleDocumentLoader(str(file))
    async for doc in loader.alazy_load():
        log.debug(f"Document: {doc.page_content}")
        log.debug(f"Document Metadata: {doc.metadata}")
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
        log.debug(f"Document Metadata: {doc.metadata}")
        documents.append(doc)
    return documents


async def load_player_docs(players: list[LeaguePlayer], chunk_index: int = 0):
    documents = []
    loader = PlayerDocumentLoader(players, chunk_index=chunk_index)
    async for doc in loader.alazy_load():
        log.debug(f"Document: {doc.page_content}")
        log.debug(f"Document Metadata: {doc.metadata}")
        documents.append(doc)
    return documents


async def load_match_docs(matches: list[MatchList], chunk_index: int = 0):
    documents = []
    loader = MatchDocumentLoader(matches, chunk_index=chunk_index)
    async for doc in loader.alazy_load():
        log.debug(f"Document: {doc.page_content}")
        log.debug(f"Document Metadata: {doc.metadata}")
        documents.append(doc)
    return documents


async def load_team_docs(teams: list[Team]):
    documents = []
    loader = TeamDocumentLoader(teams)
    async for doc in loader.alazy_load():
        log.debug(f"Document: {doc.page_content}")
        log.debug(f"Document Metadata: {doc.metadata}")
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


async def reset_collection(guild: discord.Guild):
    """
    Reset (delete) the collection for a guild to prepare for fresh data.

    Structure:
        - Tenant: default_tenant
        - Database: default_database
        - Collection: guild.id (all documents in one collection per guild)
    """
    # Create directory if needed
    if not CHROMA_PATH.absolute().exists():
        log.debug("Creating Chroma DB Directory", guild=guild)
        CHROMA_PATH.absolute().mkdir(parents=True, exist_ok=True)

    try:
        chroma_client = chromadb.PersistentClient(
            path=str(CHROMA_PATH.absolute()),
            tenant=chromadb.config.DEFAULT_TENANT,
            database=chromadb.config.DEFAULT_DATABASE,
        )
    except Exception as e:
        # Handle incompatible database schema (e.g., missing tenants table)
        log.warning(f"ChromaDB schema incompatible, removing old database: {e}", guild=guild)
        await rm_chroma_db()
        CHROMA_PATH.absolute().mkdir(parents=True, exist_ok=True)
        chroma_client = chromadb.PersistentClient(
            path=str(CHROMA_PATH.absolute()),
            tenant=chromadb.config.DEFAULT_TENANT,
            database=chromadb.config.DEFAULT_DATABASE,
        )

    collection_name = str(guild.id)

    # Delete existing collection if it exists
    existing_collections = [c.name for c in chroma_client.list_collections()]
    if collection_name in existing_collections:
        chroma_client.delete_collection(name=collection_name)
        log.debug(f"Deleted existing collection: {collection_name}", guild=guild)
    else:
        log.debug(f"Collection {collection_name} does not exist, nothing to delete", guild=guild)


async def save_documents(guild: discord.Guild, org_name: str, api_key: str, docs: list[Document]):
    """
    Add documents to the guild's collection. Does not delete existing documents.

    Args:
        guild: Discord guild
        org_name: OpenAI organization name
        api_key: OpenAI API key
        docs: List of documents to add
    """
    if not docs:
        log.debug("No documents to save", guild=guild)
        return

    # Create directory if needed
    if not CHROMA_PATH.absolute().exists():
        log.debug("Creating Chroma DB Directory", guild=guild)
        CHROMA_PATH.absolute().mkdir(parents=True, exist_ok=True)

    log.debug(f"Saving {len(docs)} documents to Chroma DB", guild=guild)
    http_client = httpx.AsyncClient()

    try:
        chroma_client = chromadb.PersistentClient(
            path=str(CHROMA_PATH.absolute()),
            tenant=chromadb.config.DEFAULT_TENANT,
            database=chromadb.config.DEFAULT_DATABASE,
        )

        collection_name = str(guild.id)

        Chroma.from_documents(
            documents=docs,
            collection_name=collection_name,
            client=chroma_client,
            embedding=OpenAIEmbeddings(
                model="text-embedding-3-small",
                organization=org_name,
                api_key=SecretStr(api_key),
                async_client=http_client,
            ),
            collection_metadata={"hnsw:space": "cosine"},
        )
    finally:
        await http_client.aclose()

    log.info(f"Saved {len(docs)} chunks to Chroma DB.", guild=guild)


async def create_chroma_db(guild: discord.Guild, org_name: str, api_key: str, docs: list[Document]):
    """
    Reset collection and save all documents to the Chroma database.
    Legacy function that resets and saves in one call.
    """
    await reset_collection(guild)
    await save_documents(guild, org_name, api_key, docs)


async def rm_chroma_db():
    """Remove the entire ChromaDB database directory. Use delete_collection() for per-guild cleanup."""
    if CHROMA_PATH.exists() and CHROMA_PATH.is_dir() and CHROMA_PATH.name == "db":
        log.debug(f"Deleting Chroma DB directory: {CHROMA_PATH.absolute()}")
        shutil.rmtree(CHROMA_PATH.absolute())


async def get_db_stats(guild: discord.Guild) -> dict:
    """
    Get statistics about the ChromaDB for a guild.

    Returns:
        Dictionary with stats including:
        - exists: Whether the database/collection exists
        - collection_name: Name of the collection
        - document_count: Number of documents in the collection
        - db_path: Path to the database directory
    """
    stats = {
        "exists": False,
        "collection_name": str(guild.id),
        "document_count": 0,
        "db_path": str(CHROMA_PATH.absolute()),
    }

    if not CHROMA_PATH.exists():
        return stats

    try:
        chroma_client = chromadb.PersistentClient(
            path=str(CHROMA_PATH.absolute()),
            tenant=chromadb.config.DEFAULT_TENANT,
            database=chromadb.config.DEFAULT_DATABASE,
        )

        collection_name = str(guild.id)
        existing_collections = [c.name for c in chroma_client.list_collections()]

        if collection_name in existing_collections:
            stats["exists"] = True
            collection = chroma_client.get_collection(name=collection_name)
            stats["document_count"] = collection.count()
    except Exception as e:
        log.error(f"Error getting DB stats: {e}", guild=guild)

    return stats


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
