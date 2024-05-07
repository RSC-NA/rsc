import logging
from typing import Iterator

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
"""

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
    """RSC Rule Document style loader"""

    def __init__(self, players: list[LeaguePlayer]) -> None:
        self.players: list[LeaguePlayer] = players

    def lazy_load(self) -> Iterator[Document]:
        """A lazy loader that reads RSC Rule style documents."""

        for p in self.players:
            match p.status:
                case Status.ROSTERED | Status.RENEWED:
                    if not (
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
                        metadata={"source": "Rostered Player API", "id": str(p.id)},
                    )
                case Status.AGMIR | Status.IR:
                    if not (
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
                        metadata={"source": "IR Player API", "id": str(p.id)},
                    )
                case Status.FREE_AGENT:
                    if not (p.id and p.player.name and p.tier and p.tier.name):
                        log.warning(
                            f"Skipping player {p.id}. Missing required data for LLM input."
                        )
                        continue

                    input = FA_INPUT.format(
                        name=p.player.name,
                        tier=p.tier.name,
                    )
                    yield Document(
                        page_content=input,
                        metadata={"source": "Free Agent API", "id": str(p.id)},
                    )
                case Status.PERM_FA:
                    if not (p.player.name and p.tier and p.tier.name):
                        log.warning(
                            f"Skipping player {p.id}. Missing required data for LLM input."
                        )
                        continue

                    input = PERMFA_INPUT.format(
                        name=p.player.name,
                        tier=p.tier.name,
                    )
                    yield Document(
                        page_content=input,
                        metadata={"source": "PermFA API"},
                    )
                case Status.DRAFT_ELIGIBLE:
                    if not (p.id and p.player.name):
                        log.warning(
                            f"Skipping player {p.id}. Missing required data for LLM input."
                        )
                        continue

                    if p.tier and p.tier.name:
                        tier_fmt = (
                            f"{p.player.name} is currently in the {p.tier.name} tier."
                        )
                    else:
                        tier_fmt = f"{p.player.name} has not been assigned a tier yet."

                    input = DE_INPUT.format(
                        name=p.player.name,
                        tier=tier_fmt,
                    )
                    yield Document(
                        page_content=input,
                        metadata={"source": "Free Agent API", "id": str(p.id)},
                    )
