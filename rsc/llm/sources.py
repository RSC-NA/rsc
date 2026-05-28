from enum import Enum

from langchain_core.documents import Document

SOURCE_TYPE_METADATA_KEY = "source_type"


class DocumentSource(Enum):
    """LLM document sources used for refresh, retrieval, and deletion."""

    RULEBOOK = "rulebook"
    GLOSSARY = "glossary"
    DATES = "dates"
    HELP = "help"
    FUNNY = "funny"
    FRANCHISES = "franchises"
    PLAYERS = "players"
    PLAYER_STATS = "player_stats"
    MATCHES = "matches"
    TEAMS = "teams"
    TEAM_STATS = "team_stats"
    STANDINGS = "standings"
    SEASON = "season"


STATIC_DOCUMENT_SOURCES = (
    DocumentSource.RULEBOOK,
    DocumentSource.GLOSSARY,
    DocumentSource.DATES,
    DocumentSource.HELP,
    DocumentSource.FUNNY,
)


def set_document_source(doc: Document, source: DocumentSource) -> Document:
    """Set the canonical source identity for an LLM document."""
    doc.metadata[SOURCE_TYPE_METADATA_KEY] = source.value
    return doc


def document_source(doc: Document) -> str | None:
    """Read the canonical source identity for an LLM document."""
    source = doc.metadata.get(SOURCE_TYPE_METADATA_KEY)
    return str(source) if source else None
