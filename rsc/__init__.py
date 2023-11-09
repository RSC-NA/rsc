from rsc.core import RSC

import logging

log = logging.getLogger("red.rsc.__init__")


async def setup(bot):
    rsc = RSC(bot)

    # Setup API Configuration
    await rsc.prepare_api()

    # Handle cache population on reload
    if rsc._api_conf:
        await rsc.populate_cache()

    await bot.add_cog(rsc)
