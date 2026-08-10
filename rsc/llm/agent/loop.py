"""The tool-calling agent loop.

Built on the Responses API rather than chat completions, for `max_tool_calls`
(a server side cap that holds even if the loop logic is wrong),
`prompt_cache_key`, and `store=False`.

The single fact that shapes everything here: the loop re-sends its entire
context on every iteration. Iterations multiply cost, tool results are paid for
again on each subsequent turn, and parallel tool calls are a cost saving rather
than merely a latency one.
"""

import asyncio
import json
import logging
import time
from dataclasses import dataclass, field
from typing import Any

from openai import APIError, RateLimitError
from openai.types.responses import Response, ResponseFunctionToolCall

from rsc.exceptions import RscException
from rsc.logs import GuildLogAdapter
from rsc.llm.agent.budget import log_usage
from rsc.llm.agent.cache import cache_key
from rsc.llm.agent.context import AgentContext
from rsc.llm.agent.format import clamp
from rsc.llm.agent.prompts import build_system_prefix, build_user_block
from rsc.llm.agent.registry import TOOLS, tool_schemas
from rsc.llm.agent.safety import sanitize_response
from rsc.llm.config import (
    AGENT_MAX_ITERATIONS,
    AGENT_MAX_OUTPUT_TOKENS,
    AGENT_MAX_TOOL_CALLS,
    AGENT_MAX_TOTAL_TOKENS,
    AGENT_TOTAL_TIMEOUT,
    OPENAI_AGENT_MODEL,
    OPENAI_REQUEST_TIMEOUT,
    PROMPT_VERSION,
    TOOL_TIMEOUT,
)

logger = logging.getLogger("red.rsc.llm.agent")
log = GuildLogAdapter(logger)


class AgentError(Exception):
    """A failure the user should see, as opposed to one the model can retry."""


@dataclass(slots=True)
class AgentResult:
    answer: str
    tools_called: list[str] = field(default_factory=list)
    citations: list[str] = field(default_factory=list)
    iterations: int = 0


async def _dispatch(ctx: AgentContext, call: ResponseFunctionToolCall) -> str:
    """Run one tool call. Never raises.

    Failures are returned to the *model* as text rather than aborting the run,
    so it can try a different tool or tell the user the API is down. Only
    loop-level provider errors reach the user.
    """
    name = getattr(call, "name", "") or ""
    entry = TOOLS.get(name)
    if entry is None:
        return f"ERROR: unknown tool {name!r}"

    raw_args = getattr(call, "arguments", "") or "{}"
    try:
        kwargs = json.loads(raw_args) if isinstance(raw_args, str) else dict(raw_args)
    except (json.JSONDecodeError, TypeError, ValueError):
        return "ERROR: arguments were not valid JSON"
    if not isinstance(kwargs, dict):
        return "ERROR: arguments must be a JSON object"

    ctx.tools_called.record(name)

    async def run() -> str:
        return await asyncio.wait_for(entry.handler(ctx, **kwargs), TOOL_TIMEOUT)

    try:
        if entry.cacheable and ctx.cache is not None:
            result = await ctx.cache.get_or_fetch(cache_key(ctx.guild.id, name, kwargs), run)
        else:
            result = await run()
    except RscException as exc:
        reason = exc.reason or exc.message or "request failed"
        log.warning(f"Tool {name} API error: {reason}", guild=ctx.guild)
        return f"ERROR: RSC API - {reason}"
    except TimeoutError:
        log.warning(f"Tool {name} timed out.", guild=ctx.guild)
        return f"ERROR: {name} timed out"
    except (TypeError, ValueError, KeyError, AttributeError) as exc:
        log.warning(f"Tool {name} failed: {exc}", guild=ctx.guild)
        return f"ERROR: {exc}"

    return clamp(result)


async def _respond(ctx: AgentContext, system: str, input_items: list[Any], *, with_tools: bool) -> Response:
    """One model call, with a single retry reserved for rate limiting.

    Retries are the fastest way to double a bill, so nothing else is retried.
    """
    kwargs: dict[str, Any] = {
        "model": OPENAI_AGENT_MODEL,
        "instructions": system,
        "input": input_items,
        "max_output_tokens": AGENT_MAX_OUTPUT_TOKENS,
        "store": False,
        "prompt_cache_key": f"rsc-agent-v{PROMPT_VERSION}-{ctx.guild.id}",
        "timeout": OPENAI_REQUEST_TIMEOUT,
    }
    if with_tools:
        kwargs["tools"] = tool_schemas()
        kwargs["parallel_tool_calls"] = True
        kwargs["max_tool_calls"] = AGENT_MAX_TOOL_CALLS

    try:
        return await ctx.client.responses.create(**kwargs)
    except RateLimitError:
        log.warning("OpenAI rate limited, retrying once.", guild=ctx.guild)
        await asyncio.sleep(2)
        try:
            return await ctx.client.responses.create(**kwargs)
        except APIError as exc:
            raise AgentError("The AI service is rate limited. Try again shortly.") from exc
    except APIError as exc:
        raise AgentError(f"The AI service returned an error: {exc}") from exc


def _output_text(response: Response) -> str:
    """Model text, sanitized.

    Every answer leaves the loop through here, so the command and credential
    guards cannot be bypassed by a new command or listener forgetting to call
    them.
    """
    text = getattr(response, "output_text", None)
    return sanitize_response((text or "").strip())


def _function_calls(response: Response) -> list[ResponseFunctionToolCall]:
    return [item for item in (getattr(response, "output", None) or []) if getattr(item, "type", "") == "function_call"]


async def _run(ctx: AgentContext, question: str) -> AgentResult:
    system = build_system_prefix()
    # Identity and current time change every question, so they go in the user
    # message. In the system prefix they would guarantee a cache miss on every
    # single request.
    input_items: list[Any] = [{"role": "user", "content": build_user_block(question, ctx)}]

    for _ in range(AGENT_MAX_ITERATIONS):
        ctx.iterations += 1
        response = await _respond(ctx, system, input_items, with_tools=True)
        ctx.usage.record(getattr(response, "usage", None))

        if ctx.usage.total > AGENT_MAX_TOTAL_TOKENS:
            log.warning(
                f"Token ceiling hit ({ctx.usage.total} > {AGENT_MAX_TOTAL_TOKENS}); forcing an answer.",
                guild=ctx.guild,
            )
            return await _final_answer(ctx, system, input_items)

        calls = _function_calls(response)
        if not calls:
            return AgentResult(
                answer=_output_text(response),
                tools_called=list(ctx.tools_called.names),
                citations=list(ctx.citations),
                iterations=ctx.iterations,
            )

        # Reasoning items must round-trip verbatim or the provider rejects the
        # follow-up as an incomplete conversation.
        input_items.extend(response.output)
        results = await asyncio.gather(*(_dispatch(ctx, call) for call in calls))
        input_items.extend(
            {"type": "function_call_output", "call_id": call.call_id, "output": result} for call, result in zip(calls, results, strict=True)
        )

    return await _final_answer(ctx, system, input_items)


async def _final_answer(ctx: AgentContext, system: str, input_items: list[Any]) -> AgentResult:
    """Force a reply with tools withdrawn.

    An exhausted loop should answer from what it already gathered rather than
    erroring -- partial information beats no information.
    """
    ctx.iterations += 1
    response = await _respond(ctx, system, input_items, with_tools=False)
    ctx.usage.record(getattr(response, "usage", None))
    return AgentResult(
        answer=_output_text(response),
        tools_called=list(ctx.tools_called.names),
        citations=list(ctx.citations),
        iterations=ctx.iterations,
    )


async def run_agent(ctx: AgentContext, question: str) -> AgentResult:
    """Answer a question, logging what it cost."""
    started = time.monotonic()
    try:
        result = await asyncio.wait_for(_run(ctx, question), AGENT_TOTAL_TIMEOUT)
    except TimeoutError as exc:
        raise AgentError("That took too long to answer. Try a narrower question.") from exc
    finally:
        log_usage(
            guild_id=ctx.guild.id,
            user_id=ctx.identity.discord_id if ctx.identity and ctx.identity.discord_id else 0,
            surface=ctx.surface,
            model=OPENAI_AGENT_MODEL,
            usage=ctx.usage,
            tools=list(ctx.tools_called.names),
            iterations=ctx.iterations,
            elapsed=time.monotonic() - started,
        )

    if not result.answer:
        raise AgentError("I could not come up with an answer for that.")
    return result
