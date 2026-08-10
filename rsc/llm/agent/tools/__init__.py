"""Tool registration.

Importing this package is what populates `registry.TOOLS` -- each module
registers its tools via the `@tool` decorator at import time, so every module
must be imported here even though nothing references the names directly.
"""

from rsc.llm.agent.tools import docs as docs
from rsc.llm.agent.tools import league as league
from rsc.llm.agent.tools import rules as rules
from rsc.llm.agent.tools import schedule as schedule
from rsc.llm.agent.tools import stats as stats
