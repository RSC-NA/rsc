"""Tests for the agent loop's control flow and failure handling.

The OpenAI client is faked rather than mocked against the real types because
`Response.output_text` is a computed property on the real model -- constructing
genuine `Response` objects would mean supplying every required field just to
script a two-turn conversation.
"""

import asyncio
import json
from datetime import UTC, datetime
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock

import pytest

from rsc.exceptions import RscException
from rsc.llm.agent.context import AgentContext
from rsc.llm.agent.loop import AgentError, _dispatch, run_agent
from rsc.llm.agent.registry import TOOLS, AgentTool
from rsc.llm.config import AGENT_MAX_ITERATIONS, AGENT_MAX_TOTAL_TOKENS, TOOL_RESULT_MAX_CHARS
from rsc.llm.rulebook import load_rulebooks


def fn_call(name: str, args: dict | str, call_id: str = "call_1") -> SimpleNamespace:
    return SimpleNamespace(
        type="function_call",
        name=name,
        arguments=args if isinstance(args, str) else json.dumps(args),
        call_id=call_id,
    )


def text_item(text: str) -> SimpleNamespace:
    return SimpleNamespace(type="output_text", text=text)


def fake_response(output: list, *, in_tokens: int = 100, out_tokens: int = 20, cached: int = 0) -> SimpleNamespace:
    return SimpleNamespace(
        output=output,
        output_text="".join(item.text for item in output if getattr(item, "type", "") == "output_text"),
        usage=SimpleNamespace(
            input_tokens=in_tokens,
            output_tokens=out_tokens,
            total_tokens=in_tokens + out_tokens,
            input_tokens_details=SimpleNamespace(cached_tokens=cached),
            output_tokens_details=SimpleNamespace(reasoning_tokens=0),
        ),
    )


@pytest.fixture(autouse=True)
async def _rulebooks():
    """The system prefix embeds the rulebook table of contents."""
    await load_rulebooks()


@pytest.fixture
def guild():
    mock = MagicMock()
    mock.id = 12345
    mock.name = "RSC"
    return mock


@pytest.fixture
def ctx(guild):
    client = MagicMock()
    client.responses = MagicMock()
    return AgentContext(
        cog=MagicMock(),
        guild=guild,
        client=client,
        now=datetime(2026, 8, 10, 12, 0, tzinfo=UTC),
    )


@pytest.fixture
def registered_tool():
    """Register a throwaway tool and remove it afterwards."""
    created: list[str] = []

    def register(name: str, handler, cacheable: bool = False) -> None:
        TOOLS[name] = AgentTool(
            name=name,
            description="test tool",
            parameters={"type": "object", "properties": {}, "required": []},
            handler=handler,
            cacheable=cacheable,
        )
        created.append(name)

    yield register

    for name in created:
        TOOLS.pop(name, None)


# Dispatch


async def test_dispatch_runs_tool_and_records_it(ctx, registered_tool):
    registered_tool("echo_tool", AsyncMock(return_value="hello"))

    result = await _dispatch(ctx, fn_call("echo_tool", {}))

    assert result == "hello"
    assert ctx.tools_called.names == ["echo_tool"]


async def test_dispatch_passes_arguments(ctx, registered_tool):
    async def handler(_ctx, value: str) -> str:
        return f"got {value}"

    registered_tool("arg_tool", handler)

    assert await _dispatch(ctx, fn_call("arg_tool", {"value": "x"})) == "got x"


async def test_dispatch_reports_unknown_tool(ctx):
    result = await _dispatch(ctx, fn_call("does_not_exist", {}))

    assert result.startswith("ERROR: unknown tool")


async def test_dispatch_reports_malformed_arguments(ctx, registered_tool):
    registered_tool("echo_tool", AsyncMock(return_value="hello"))

    result = await _dispatch(ctx, fn_call("echo_tool", "{not json"))

    assert result == "ERROR: arguments were not valid JSON"


async def test_dispatch_surfaces_api_errors_to_the_model(ctx, registered_tool):
    """An RSC API failure must not abort the run.

    The model can pick a different tool or tell the user the API is down; an
    exception here would lose the whole answer.
    """
    registered_tool("bad_tool", AsyncMock(side_effect=RscException(message="league is down")))

    result = await _dispatch(ctx, fn_call("bad_tool", {}))

    assert result.startswith("ERROR: RSC API")
    assert "league is down" in result


async def test_dispatch_reports_bad_arguments_with_valid_options(ctx, registered_tool):
    registered_tool("picky_tool", AsyncMock(side_effect=ValueError("unknown status 'XX'")))

    result = await _dispatch(ctx, fn_call("picky_tool", {}))

    assert result == "ERROR: unknown status 'XX'"


async def test_dispatch_times_out_slow_tools(ctx, registered_tool, monkeypatch):
    async def slow(_ctx) -> str:
        await asyncio.sleep(5)
        return "never"

    monkeypatch.setattr("rsc.llm.agent.loop.TOOL_TIMEOUT", 0.01)
    registered_tool("slow_tool", slow)

    result = await _dispatch(ctx, fn_call("slow_tool", {}))

    assert result == "ERROR: slow_tool timed out"


async def test_dispatch_truncates_oversized_output(ctx, registered_tool):
    """A runaway tool result must not blow the context budget.

    Truncation says how much was dropped: a silently shortened list reads as a
    complete one, which is the failure mode this whole design replaced.
    """
    oversized = "\n".join(f"row {i} " + "x" * 40 for i in range(2000))
    registered_tool("big_tool", AsyncMock(return_value=oversized))

    result = await _dispatch(ctx, fn_call("big_tool", {}))

    assert "truncated" in result
    assert len(result) <= TOOL_RESULT_MAX_CHARS + 200
    assert result.endswith("Narrow your filters.")


# Loop


async def test_loop_returns_answer_without_tool_calls(ctx):
    ctx.client.responses.create = AsyncMock(return_value=fake_response([text_item("42 franchises.")]))

    result = await run_agent(ctx, "how many franchises?")

    assert result.answer == "42 franchises."
    assert result.iterations == 1


async def test_loop_feeds_tool_output_back_with_matching_call_id(ctx, registered_tool):
    registered_tool("echo_tool", AsyncMock(return_value="tool said hi"))
    ctx.client.responses.create = AsyncMock(
        side_effect=[
            fake_response([fn_call("echo_tool", {}, call_id="abc")]),
            fake_response([text_item("done")]),
        ]
    )

    result = await run_agent(ctx, "question")

    assert result.answer == "done"
    second_call = ctx.client.responses.create.await_args_list[1]
    outputs = [item for item in second_call.kwargs["input"] if isinstance(item, dict) and item.get("type") == "function_call_output"]
    assert outputs == [{"type": "function_call_output", "call_id": "abc", "output": "tool said hi"}]


async def test_loop_dispatches_parallel_tool_calls(ctx, registered_tool):
    registered_tool("tool_a", AsyncMock(return_value="A"))
    registered_tool("tool_b", AsyncMock(return_value="B"))
    ctx.client.responses.create = AsyncMock(
        side_effect=[
            fake_response([fn_call("tool_a", {}, "id_a"), fn_call("tool_b", {}, "id_b")]),
            fake_response([text_item("both")]),
        ]
    )

    await run_agent(ctx, "question")

    assert ctx.tools_called.names == ["tool_a", "tool_b"]


async def test_loop_stops_at_iteration_cap_and_forces_an_answer(ctx, registered_tool):
    """An exhausted loop answers from what it gathered rather than erroring."""
    registered_tool("echo_tool", AsyncMock(return_value="more"))
    ctx.client.responses.create = AsyncMock(
        side_effect=[
            *[fake_response([fn_call("echo_tool", {})]) for _ in range(AGENT_MAX_ITERATIONS)],
            fake_response([text_item("best effort")]),
        ]
    )

    result = await run_agent(ctx, "question")

    assert result.answer == "best effort"
    assert ctx.client.responses.create.await_count == AGENT_MAX_ITERATIONS + 1
    # The forced final call must withdraw the tools, or it would loop forever.
    assert "tools" not in ctx.client.responses.create.await_args_list[-1].kwargs


async def test_loop_trips_the_token_ceiling(ctx, registered_tool):
    registered_tool("echo_tool", AsyncMock(return_value="more"))
    ctx.client.responses.create = AsyncMock(
        side_effect=[
            fake_response([fn_call("echo_tool", {})], in_tokens=AGENT_MAX_TOTAL_TOKENS + 1),
            fake_response([text_item("stopped early")]),
        ]
    )

    result = await run_agent(ctx, "question")

    assert result.answer == "stopped early"
    assert ctx.client.responses.create.await_count == 2


async def test_loop_raises_when_the_model_returns_nothing(ctx):
    ctx.client.responses.create = AsyncMock(return_value=fake_response([]))

    with pytest.raises(AgentError):
        await run_agent(ctx, "question")


async def test_usage_accumulates_across_iterations(ctx, registered_tool):
    registered_tool("echo_tool", AsyncMock(return_value="x"))
    ctx.client.responses.create = AsyncMock(
        side_effect=[
            fake_response([fn_call("echo_tool", {})], in_tokens=100, out_tokens=10, cached=80),
            fake_response([text_item("done")], in_tokens=200, out_tokens=20, cached=150),
        ]
    )

    await run_agent(ctx, "question")

    assert ctx.usage.input_tokens == 300
    assert ctx.usage.output_tokens == 30
    assert ctx.usage.cached_tokens == 230
    assert ctx.usage.calls == 2


async def test_prompt_cache_key_is_stable_per_guild(ctx):
    ctx.client.responses.create = AsyncMock(return_value=fake_response([text_item("hi")]))

    await run_agent(ctx, "question")

    assert ctx.client.responses.create.await_args.kwargs["prompt_cache_key"].endswith(str(ctx.guild.id))
