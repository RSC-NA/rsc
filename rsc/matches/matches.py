import discord
import logging
from pydantic import parse_obj_as

from redbot.core import app_commands, checks

from rscapi import ApiClient, LeaguesApi
from rscapi.models.league import League

from rsc.embeds import ErrorEmbed

from typing import List

log = logging.getLogger("red.rsc.matches")


class MatchMixIn:
    # App Commands

    @app_commands.command(
        name="schedule", description="Display your entire schedule or a specific team"
    )
    @app_commands.guild_only()
    async def _schedule(self, interaction: discord.Interaction):
        leagues = await self.leagues()
        if leagues:
            output = "\n- ".join(f"{l.name}: {l.league_data.game_mode}" for l in l)
            interaction.response.send_message(
                discord.Embed(name="RSC Leagues", description=output)
            )

    # Functionality

    async def leagues(self) -> List[League]:
        async with ApiClient(self._api_conf) as client:
            leagues = LeaguesApi(client)
            resp = await leagues.leagues_list()
            log.debug(resp)
            # return parse_obj_as(List[League], resp)
