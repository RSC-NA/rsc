import logging
import os

import sentry_sdk
from redbot.core.bot import Red

from rsc.core import RSC

logging.basicConfig()
log = logging.getLogger("red.rsc.__init__")


def init_sentry():
    """Report errors to Sentry when SENTRY_DSN is set. Only the production host sets it."""
    dsn = os.environ.get("SENTRY_DSN")
    if not dsn:
        log.debug("SENTRY_DSN is not set. Sentry is disabled.")
        return
    # Safe to call again on a cog reload. The new client replaces the old one.
    # Error-level log records become Sentry events, which covers command errors
    # (Red logs them with log.exception) and the task loops.
    sentry_sdk.init(
        dsn=dsn,
        environment=os.environ.get("SENTRY_ENVIRONMENT", "production"),
        send_default_pii=False,
    )
    log.info("Sentry error reporting is enabled.")


async def setup(bot: Red):
    init_sentry()
    rsc = RSC(bot)
    await bot.add_cog(rsc)
