from typing import Any

OPENAI_CHAT_TEMPERATURE: float | None = None

# Agent models. All three are deliberately the same small model: the league is
# funded out of pocket, and a larger model on the sub-agent would undo the
# saving the sub-agent exists to produce.
OPENAI_AGENT_MODEL = "gpt-5.4-mini"
OPENAI_SUBAGENT_MODEL = "gpt-5.4-mini"
OPENAI_SUMMARY_MODEL = "gpt-5.4-mini"

# Bump when the cached system prefix changes shape, so stale cache shards are
# not reused across a deploy.
PROMPT_VERSION = 1

# Iteration and token ceilings. The loop re-sends its whole context on every
# iteration, so iteration count multiplies cost -- these are the primary spend
# control, not a safety net.
AGENT_MAX_ITERATIONS = 4
AGENT_MAX_TOOL_CALLS = 8
AGENT_MAX_OUTPUT_TOKENS = 900
SUBAGENT_MAX_OUTPUT_TOKENS = 600
AGENT_MAX_TOTAL_TOKENS = 60_000
TOOL_RESULT_MAX_CHARS = 6_000

TOOL_TIMEOUT = 20.0
AGENT_TOTAL_TIMEOUT = 60.0
OPENAI_REQUEST_TIMEOUT = 45.0

# ~12k tokens. Only reached when lexical search finds no section to scope to.
RULES_SUBAGENT_MAX_CONTEXT_CHARS = 48_000
RULES_SUBAGENT_MAX_SECTIONS = 5

# Short TTL: rosters move intraday after transactions, so this exists to
# collapse bursts, not to serve stale data.
API_CACHE_TTL = 300.0
API_CACHE_MAXSIZE = 256


# Returns `Any` values because the result is splatted into the OpenAI SDK's
# TypedDict kwargs, which a concrete `str | float` union cannot satisfy.
def openai_chat_completion_options(model: str = OPENAI_AGENT_MODEL) -> dict[str, Any]:
    options: dict[str, Any] = {"model": model}
    if OPENAI_CHAT_TEMPERATURE is not None:
        options["temperature"] = OPENAI_CHAT_TEMPERATURE
    return options
