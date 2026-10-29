"""What combines lobbies do differently. `rsc.lobbies.runner.LobbyRunner` does the rest."""

import logging

import discord
from redbot.core.config import Group

from rsc import const
from rsc.combines import api, models
from rsc.combines.lobby import LobbyMessages
from rsc.combines.views import LobbyKind, LobbyScore
from rsc.exceptions import SiteUnavailable
from rsc.lobbies.channels import Side
from rsc.lobbies.runner import LobbyLeague, Overwrites

log = logging.getLogger("red.rsc.combines.runner")

ANNOUNCE_CHANNEL = "combines-announcements"


class CombinesLeague(LobbyLeague):
    kind = LobbyKind.COMBINE
    name = "Combines"
    label = "combine lobby"
    noun = "lobby"
    nouns = "lobbies"

    def store(self, guild: discord.Guild) -> Group:
        return self.cog.config.custom("Combines", str(guild.id))

    async def active(self, guild: discord.Guild) -> bool:
        return await self.cog._get_combines_active(guild)

    async def category(self, guild: discord.Guild) -> discord.CategoryChannel | None:
        return await self.cog._get_combines_category(guild)

    async def announce_channel(self, guild: discord.Guild) -> discord.TextChannel | None:
        channel = discord.utils.get(guild.channels, name=ANNOUNCE_CHANNEL)
        return channel if isinstance(channel, discord.TextChannel) else None

    def channel_name(self, lobby: models.CombinesLobby, side: Side) -> str:
        return f"{lobby.tier}-{lobby.id}-{side}"

    def match_url(self, lobby: models.CombinesLobby) -> str:
        return f"https://devleague.rscna.com/combine/{lobby.id}"

    def extra_overwrites(self, guild: discord.Guild) -> Overwrites:
        # The Muted role is optional. Without it the lobby just has no muted overwrite.
        muted = discord.utils.get(guild.roles, name=const.MUTED_ROLE)
        if not muted:
            return {}
        return {muted: discord.PermissionOverwrite(view_channel=True, connect=False, speak=False)}

    async def final_score(self, guild: discord.Guild, entry: LobbyMessages) -> LobbyScore | None:
        """The series score from the combines API, or None when it can't be read."""
        url = await self.cog._get_combines_api(guild)
        executor = guild.get_member(entry.executor_id) if entry.executor_id else None
        if not (url and executor):
            return None
        try:
            result = await api.combines_lobby(url, executor=executor, lobby_id=entry.card.lobby_id)
        except SiteUnavailable as exc:
            log.warning(f"Unable to fetch the final score for combine {entry.card.lobby_id}: {exc}")
            return None
        if not isinstance(result, models.CombinesLobby) or result.cancelled:
            return None
        return LobbyScore(home_wins=result.home_wins, away_wins=result.away_wins)
