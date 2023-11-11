from rsc.core import RSC

import logging

log = logging.getLogger("red.rsc.__init__")


async def setup(bot):
    rsc = RSC(bot)

    # Handle reload of Cog
    # if rsc._api_conf:
    #     await rsc.setup()

    await bot.add_cog(rsc)
