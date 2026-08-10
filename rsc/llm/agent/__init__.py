"""Tool-calling agent for RSC league and rules questions."""

# Importing the tools package registers every tool. It must happen before
# `tool_schemas()` is called, so it is done here rather than at each call site.
from rsc.llm.agent import tools as tools
from rsc.llm.agent.budget import CooldownTracker as CooldownTracker
from rsc.llm.agent.budget import UsageAccumulator as UsageAccumulator
from rsc.llm.agent.budget import usage_day as usage_day
from rsc.llm.agent.cache import ToolCache as ToolCache
from rsc.llm.agent.context import AgentContext as AgentContext
from rsc.llm.agent.context import UserIdentity as UserIdentity
from rsc.llm.agent.loop import AgentError as AgentError
from rsc.llm.agent.loop import AgentResult as AgentResult
from rsc.llm.agent.loop import run_agent as run_agent
from rsc.llm.agent.registry import TOOLS as TOOLS
from rsc.llm.agent.registry import tool_schemas as tool_schemas
