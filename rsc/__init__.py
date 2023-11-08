from rsc.core import RSC


async def setup(bot):
    rsc = RSC(bot)
    await rsc.prepare_api()
    await bot.add_cog(rsc)
