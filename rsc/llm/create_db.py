#!/usr/bin/env python3

import asyncio
import logging
import shutil
import sys
import tempfile
from pathlib import Path

from langchain.document_loaders.directory import DirectoryLoader
from langchain.vectorstores.chroma import Chroma
from langchain_community.document_loaders import JSONLoader
from langchain_core.documents import Document
from langchain_openai.embeddings import OpenAIEmbeddings
from langchain_text_splitters import MarkdownTextSplitter

log = logging.getLogger("red.rsc.llm.create")

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
    return documents


async def load_rule_docs() -> list[Document]:
    log.debug("Loading rule documents")
    fpath = Path(__file__).parent.parent / "resources" / "rules"
    loader = DirectoryLoader(str(fpath), glob="*.md")
    documents = loader.load()
    return documents


async def load_help_docs() -> list[Document]:
    log.debug("Loading help documents")
    fpath = Path(__file__).parent.parent / "resources" / "help"
    loader = DirectoryLoader(str(fpath), glob="*.md")
    documents = loader.load()
    return documents


async def markdown_to_documents(docs: list[Document]) -> list[Document]:
    md_splitter = MarkdownTextSplitter()
    return md_splitter.split_documents(docs)


async def json_to_docs(data: str | bytes, jq_schema: str) -> list[Document]:
    with tempfile.NamedTemporaryFile() as fd:
        if isinstance(data, str):
            fd.write(data.encode("utf-8"))
        elif isinstance(data, bytes):
            fd.write(data)
        else:
            raise TypeError("JSON data must be str or bytes")
        loader = JSONLoader(file_path=fd.name, jq_schema=jq_schema, text_content=False)
        chunks = loader.load()

    return chunks


async def create_chroma_db(org_name: str, api_key: str, docs: list[Document]):
    # Clear out the database first.
    # await rm_chroma_db()
    # Load DB
    if not CHROMA_PATH.absolute().exists():
        CHROMA_PATH.absolute().mkdir(parents=True, exist_ok=True)
        await asyncio.sleep(5)

    # Create a new DB from the documents.
    db = Chroma.from_documents(
        docs,
        OpenAIEmbeddings(organization=org_name, api_key=api_key),
        persist_directory=str(CHROMA_PATH.absolute()),
    )
    db.persist()
    log.info(f"Saved {len(docs)} chunks to {CHROMA_PATH}.")


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
