from rsc.core import RSC

import logging

logging.basicConfig()
log = logging.getLogger("red.rsc.__init__")


async def setup(bot):
    rsc = RSC(bot)
    await bot.add_cog(rsc)
