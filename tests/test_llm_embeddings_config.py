from inspect import signature

from rsc.llm import create_db, query
from rsc.llm.config import (
    CHROMA_PATH,
    OPENAI_CHAT_MODEL,
    OPENAI_CHAT_TEMPERATURE,
    OPENAI_EMBEDDING_MODEL,
    openai_chat_completion_options,
)


def test_llm_chat_model_is_shared_with_query_defaults() -> None:
    assert OPENAI_CHAT_MODEL == "gpt-5.4-mini"
    assert signature(query.llm_query).parameters["model"].default == OPENAI_CHAT_MODEL
    assert signature(query.summarize_ticket_messages).parameters["model"].default == OPENAI_CHAT_MODEL


def test_llm_chat_options_omit_unsupported_temperature_by_default() -> None:
    assert OPENAI_CHAT_TEMPERATURE is None
    assert openai_chat_completion_options() == {"model": OPENAI_CHAT_MODEL}


def test_llm_embedding_model_is_shared_between_create_and_query() -> None:
    assert OPENAI_EMBEDDING_MODEL == "text-embedding-3-large"
    assert create_db.OPENAI_EMBEDDING_MODEL == OPENAI_EMBEDDING_MODEL
    assert query.OPENAI_EMBEDDING_MODEL == OPENAI_EMBEDDING_MODEL


def test_llm_chroma_path_is_shared_between_create_and_query() -> None:
    assert create_db.CHROMA_PATH == CHROMA_PATH
    assert query.CHROMA_PATH == CHROMA_PATH
