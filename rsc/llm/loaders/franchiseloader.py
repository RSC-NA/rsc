import logging
from typing import Iterator

from langchain_core.document_loaders import BaseLoader
from langchain_core.documents import Document
from rscapi.models.franchise_list import FranchiseList

log = logging.getLogger("red.rsc.llm.loaders.franchiseloader")


FRANCHISE_INPUT = """
{name} is an RSC (Rocket Soccar Confederation) franchise and has the prefix or tag "{prefix}". The General Manager, also known as GM, of {name} is {gm}.

{name} has the following teams in their franchise: {teams}

{name} has the following tiers in their franchise: {tiers}
"""


class FranchiseDocumentLoader(BaseLoader):
    """RSC Rule Document style loader"""

    def __init__(self, franchises: list[FranchiseList]) -> None:
        self.franchises: list[FranchiseList] = franchises

    def lazy_load(self) -> Iterator[Document]:
        """A lazy loader that reads RSC Rule style documents."""

        final = []
        for f in self.franchises:
            if not (
                f.name and f.prefix and f.gm and f.gm.rsc_name and f.tiers and f.teams
            ):
                log.warning(
                    f"Skipping franchise {f.id}. Missing required data for LLM input."
                )
                continue

            # Gather tiers
            tiers: list[str] = []
            for tier in f.tiers:
                if not tier.name:
                    log.warning(f"Franchise {f.id} has a tier with no name.")
                    continue
                tiers.append(tier.name)

            # Gather teams
            teams: list[str] = []
            for team in f.teams:
                if not team.name:
                    log.warning(f"Franchise {f.id} has a team with no name.")
                    continue
                teams.append(team.name)

            input = FRANCHISE_INPUT.format(
                name=f.name,
                prefix=f.prefix,
                gm=f.gm.rsc_name,
                teams=", ".join(teams),
                tiers=", ".join(tiers),
            )

            final.append(input)

        yield Document(
            page_content="\n".join(final),
            metadata={"source": "Franchises API"},
        )
