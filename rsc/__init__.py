import logging
import os

import sentry_sdk
from redbot.core.bot import Red
from sentry_sdk.integrations.logging import LoggingIntegration
from sentry_sdk.integrations.openai import OpenAIIntegration
from sentry_sdk.scrubber import DEFAULT_DENYLIST, EventScrubber

from rsc.core import RSC

logging.basicConfig()
log = logging.getLogger("red.rsc.__init__")

# Local variable names that hold API keys in this cog (the RSC, OpenAI and
# ballchasing keys). Sentry's default denylist misses them, and stack frame
# locals are sent with every event.
SENTRY_DENYLIST = [*DEFAULT_DENYLIST, "key", "openai_key", "auth_key"]


def init_sentry():
    """Report errors to Sentry when SENTRY_DSN is set. Only the production host sets it."""
    dsn = os.environ.get("SENTRY_DSN")
    if not dsn:
        log.debug("SENTRY_DSN is not set. Sentry is disabled.")
        return
    # Safe to call again on a cog reload. The new client replaces the old one.
    #
    # Errors only. There is no tracing: nothing in a Discord bot maps to a request,
    # so traces would cost quota and show little. The release comes from
    # SENTRY_RELEASE if set.
    #
    # send_default_pii and data_collection stay unset, so the SDK collects no PII.
    # send_default_pii is deprecated, and passing a data_collection dict opts into
    # collecting most categories.
    sentry_sdk.init(
        dsn=dsn,
        environment=os.environ.get("SENTRY_ENVIRONMENT", "production"),
        integrations=[
            # Error-level records become events. That covers command errors (Red
            # logs them with log.exception), task loop failures and anything the
            # cog logs as an error. Info and above ride along as breadcrumbs, so
            # debug output (full LLM payloads) never leaves the host.
            LoggingIntegration(level=logging.INFO, event_level=logging.ERROR),
        ],
        # It reports every failed OpenAI call as unhandled, even when the llm
        # module catches it and answers the user.
        disabled_integrations=[OpenAIIntegration()],
        event_scrubber=EventScrubber(denylist=SENTRY_DENYLIST, recursive=True),
    )
    log.info("Sentry error reporting is enabled.")


async def setup(bot: Red):
    init_sentry()
    rsc = RSC(bot)
    await bot.add_cog(rsc)
