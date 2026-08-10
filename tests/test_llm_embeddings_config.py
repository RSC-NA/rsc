"""Pins on the agent's model and budget configuration.

These constants are the spend controls. Changing one should be a deliberate act
with a test update alongside it, not an incidental edit.
"""

from inspect import signature

from rsc.llm import summarize
from rsc.llm.config import (
    AGENT_MAX_ITERATIONS,
    AGENT_MAX_OUTPUT_TOKENS,
    AGENT_MAX_TOOL_CALLS,
    AGENT_MAX_TOTAL_TOKENS,
    OPENAI_AGENT_MODEL,
    OPENAI_CHAT_TEMPERATURE,
    OPENAI_SUBAGENT_MODEL,
    OPENAI_SUMMARY_MODEL,
    RULES_SUBAGENT_MAX_CONTEXT_CHARS,
    SUBAGENT_MAX_OUTPUT_TOKENS,
    TOOL_RESULT_MAX_CHARS,
    openai_chat_completion_options,
)


def test_agent_uses_the_expected_model() -> None:
    assert OPENAI_AGENT_MODEL == "gpt-5.4-mini"


def test_subagent_is_not_a_larger_model_than_the_agent() -> None:
    """A bigger sub-agent model would undo the saving it exists to produce."""
    assert OPENAI_SUBAGENT_MODEL == OPENAI_AGENT_MODEL


def test_summarizer_shares_the_configured_model() -> None:
    assert OPENAI_SUMMARY_MODEL == OPENAI_AGENT_MODEL
    assert signature(summarize.summarize_ticket_messages).parameters["model"].default == OPENAI_SUMMARY_MODEL


def test_chat_options_omit_unsupported_temperature_by_default() -> None:
    assert OPENAI_CHAT_TEMPERATURE is None
    assert openai_chat_completion_options() == {"model": OPENAI_AGENT_MODEL}


def test_iteration_and_token_ceilings_are_bounded() -> None:
    """The loop re-sends its whole context each iteration, so these multiply."""
    assert 1 <= AGENT_MAX_ITERATIONS <= 6
    assert AGENT_MAX_TOOL_CALLS <= 12
    assert AGENT_MAX_OUTPUT_TOKENS <= 1500
    assert SUBAGENT_MAX_OUTPUT_TOKENS <= AGENT_MAX_OUTPUT_TOKENS
    assert AGENT_MAX_TOTAL_TOKENS <= 100_000


def test_tool_and_subagent_context_budgets_are_bounded() -> None:
    assert TOOL_RESULT_MAX_CHARS <= 10_000
    # ~12k tokens: enough for a whole rulebook fallback, not for all three.
    assert RULES_SUBAGENT_MAX_CONTEXT_CHARS <= 60_000


def test_chroma_configuration_is_gone() -> None:
    """The vector store was removed; leftover config would invite its return."""
    from rsc.llm import config

    assert not hasattr(config, "CHROMA_PATH")
    assert not hasattr(config, "OPENAI_EMBEDDING_MODEL")
