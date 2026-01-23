import logging
from collections.abc import AsyncIterator, Iterator

from langchain_core.document_loaders import BaseLoader
from langchain_core.documents import Document
from rscapi.models.league_player import LeaguePlayer

from rsc.enums import Status

log = logging.getLogger("red.rsc.llm.loaders.playerloader")


PLAYER_INPUT = """
{name} is a player in RSC (Rocket Soccar Confederation) and plays for the team "{team}".

{team} is part of the franchise "{franchise}" and the general manager, also known as GM, of {franchise} is {gm}.

{name} is currently in the {tier} tier.
"""

IR_INPUT = """
{name} is a player in RSC (Rocket Soccar Confederation) and is currently on Inactive Reserve for the team "{team}".

{team} is part of the franchise "{franchise}" and the general manager, also known as GM, of {franchise} is {gm}.

{name} is currently in the {tier} tier.
"""

FA_INPUT = """
{name} is a player in RSC (Rocket Soccar Confederation) and is currently a Free Agent. Free Agent means he is not currently rostered on a team. However, {name} is available to be signed by a team!

{name} is currently in the {tier} tier.
"""  # noqa: E501

PERMFA_INPUT = """
{name} is a player in RSC (Rocket Soccar Confederation) and is currently a Permanent Free Agent (PermFA).

Permanent Free Agent means that {name} can not be rostered on a team but is available to sub in on match nights.

{name} is currently in the {tier} tier.
"""

DE_INPUT = """
{name} is a player in RSC (Rocket Soccar Confederation) and is currently Draft Eligible.

Draft Eligible means he is able to be drafted in the RSC Draft.

{tier}
"""


class PlayerDocumentLoader(BaseLoader):
    """RSC Player Document loader"""

    def __init__(self, players: list[LeaguePlayer], chunk_index: int = 0) -> None:
        self.players: list[LeaguePlayer] = players
        self.chunk_index = chunk_index
        log.debug("Initialized PlayerDocumentLoader with %d players", len(players))

    def _has_roster_info(self, p: LeaguePlayer) -> bool:
        """Check if player has full roster information."""
        return bool(
            p.id
            and p.player.name
            and p.team
            and p.team.name
            and p.team.franchise
            and p.team.franchise.name
            and p.team.franchise.gm
            and p.team.franchise.gm.rsc_name
            and p.tier
            and p.tier.name
        )

    def _get_roster_data(self, p: LeaguePlayer) -> dict:
        """Extract roster data from player."""
        return {
            "name": p.player.name,
            "team": p.team.name,
            "franchise": p.team.franchise.name,
            "gm": p.team.franchise.gm.rsc_name,
            "tier": p.tier.name,
        }

    def _process_players(self) -> Iterator[Document]:
        """Process all players and yield Documents with chunk_index."""
        for p in self.players:
            doc = self._process_player(p)
            if doc is not None:
                log.debug(
                    "Processing player: %s - Metadata: %s",
                    p.player.name,
                    doc.metadata,
                )
                yield doc
                self.chunk_index += 1
        log.debug("Total documents processed: %d", self.chunk_index)

    def _process_player(self, p: LeaguePlayer) -> Document | None:
        """Process a single player and return a Document or None."""
        match p.status:
            case Status.ROSTERED | Status.RENEWED:
                if not self._has_roster_info(p):
                    log.warning(f"Skipping player {p.id}. Missing required data for LLM input.")
                    return None
                return Document(
                    page_content=PLAYER_INPUT.format(**self._get_roster_data(p)),
                    metadata={"source": "Rostered Player API", "id": str(p.id), "chunk_index": self.chunk_index},
                )

            case Status.AGMIR | Status.IR:
                if not self._has_roster_info(p):
                    log.warning(f"Skipping player {p.id}. Missing required data for LLM input.")
                    return None
                return Document(
                    page_content=IR_INPUT.format(**self._get_roster_data(p)),
                    metadata={"source": "IR Player API", "id": str(p.id), "chunk_index": self.chunk_index},
                )

            case Status.FREE_AGENT:
                if not (p.id and p.player.name and p.tier and p.tier.name):
                    log.warning(f"Skipping player {p.id}. Missing required data for LLM input.")
                    return None
                return Document(
                    page_content=FA_INPUT.format(name=p.player.name, tier=p.tier.name),
                    metadata={"source": "Free Agent API", "id": str(p.id), "chunk_index": self.chunk_index},
                )

            case Status.PERM_FA:
                if not (p.player.name and p.tier and p.tier.name):
                    log.warning(f"Skipping player {p.id}. Missing required data for LLM input.")
                    return None
                return Document(
                    page_content=PERMFA_INPUT.format(name=p.player.name, tier=p.tier.name),
                    metadata={"source": "PermFA API", "id": str(p.id), "chunk_index": self.chunk_index},
                )

            case Status.DRAFT_ELIGIBLE:
                if not (p.id and p.player.name):
                    log.warning(f"Skipping player {p.id}. Missing required data for LLM input.")
                    return None
                tier_fmt = (
                    f"{p.player.name} is currently in the {p.tier.name} tier."
                    if p.tier and p.tier.name
                    else f"{p.player.name} has not been assigned a tier yet."
                )
                return Document(
                    page_content=DE_INPUT.format(name=p.player.name, tier=tier_fmt),
                    metadata={"source": "Draft Eligible API", "id": str(p.id), "chunk_index": self.chunk_index},
                )

        return None

    def lazy_load(self) -> Iterator[Document]:
        """A lazy loader that reads RSC player documents."""
        yield from self._process_players()

    async def alazy_load(self) -> AsyncIterator[Document]:
        """An async lazy loader for RSC player documents."""
        for doc in self._process_players():
            yield doc
