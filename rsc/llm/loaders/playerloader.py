import logging
from typing import Iterator

from langchain_core.document_loaders import BaseLoader
from langchain_core.documents import Document
from rscapi.models.league_player import LeaguePlayer

from rsc.enums import Status

log = logging.getLogger("red.rsc.llm.loaders.playerloader")


PLAYER_INPUT = """
{name} is a player in RSC and plays for the team "{team}". {team} is part of the franchise "{franchise}" and the general manager, also known as GM, of {franchise} is {gm}.

{name} is currently in the {tier} tier.
"""

IR_INPUT = """
{name} is a player in RSC and is currently on Inactive Reserve for the team "{team}". {team} is part of the franchise "{franchise}" and the general manager, also known as GM, of {franchise} is {gm}.

{name} is currently in the {tier} tier.
"""

FA_INPUT = """
{name} is a player in RSC and is currently a Free Agent. Free Agent means he is not currently rostered on a team. However, {name} is available to be signed by a team!

{name} is currently in the {tier} tier.
"""


class PlayerDocumentLoader(BaseLoader):
    """RSC Rule Document style loader"""

    def __init__(self, players: list[LeaguePlayer]) -> None:
        self.players: list[LeaguePlayer] = players

    def lazy_load(self) -> Iterator[Document]:
        """A lazy loader that reads RSC Rule style documents."""

        for p in self.players:
            match p.status:
                case Status.ROSTERED | Status.RENEWED:
                    if not (
                        p.player.name
                        and p.team
                        and p.team.name
                        and p.team.franchise
                        and p.team.franchise.name
                        and p.team.franchise.gm
                        and p.team.franchise.gm.rsc_name
                        and p.tier
                        and p.tier.name
                    ):
                        log.warning(
                            f"Skipping player {p.id}. Missing required data for LLM input."
                        )
                        continue

                    input = PLAYER_INPUT.format(
                        name=p.player.name,
                        team=p.team.name,
                        franchise=p.team.franchise.name,
                        gm=p.team.franchise.gm.rsc_name,
                        tier=p.tier.name,
                    )

                    yield Document(
                        page_content=input,
                        metadata={"source": "LeaguePlayers API"},
                    )
                case Status.AGMIR | Status.IR:
                    if not (
                        p.player.name
                        and p.team
                        and p.team.name
                        and p.team.franchise
                        and p.team.franchise.name
                        and p.team.franchise.gm
                        and p.team.franchise.gm.rsc_name
                        and p.tier
                        and p.tier.name
                    ):
                        log.warning(
                            f"Skipping player {p.id}. Missing required data for LLM input."
                        )
                        continue

                    input = IR_INPUT.format(
                        name=p.player.name,
                        team=p.team.name,
                        franchise=p.team.franchise.name,
                        gm=p.team.franchise.gm.rsc_name,
                        tier=p.tier.name,
                    )

                    yield Document(
                        page_content=input,
                        metadata={"source": "LeaguePlayers API"},
                    )
                case Status.FREE_AGENT | Status.PERM_FA:
                    if not (p.player.name and p.tier and p.tier.name):
                        log.warning(
                            f"Skipping player {p.id}. Missing required data for LLM input."
                        )
                        continue

                    input = FA_INPUT.format(
                        name=p.player.name,
                        tier=p.tier.name,
                    )
