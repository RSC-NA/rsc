from rsc.core import RSC

import logging

log = logging.getLogger("red.rsc.__init__")


async def setup(bot):
    rsc = RSC(bot)

    # Setup
    await rsc.prepare_api()

    # Populate some caches for autocompletion. Requires API configuration
    ### THIS WILL NEED TO BE ADJUSTED TO ACCOMIDATE MULTIPLE GUILDS
    if rsc._api_conf:
        log.debug(f"Guilds: {bot.guilds}")
        for guild in bot.guilds:
            log.debug(f"Preparing cache for {guild}")
            await rsc.franchises(guild)
            await rsc.tiers(guild)

    await bot.add_cog(rsc)
