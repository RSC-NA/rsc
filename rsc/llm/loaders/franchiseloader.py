import logging
from collections.abc import AsyncIterator, Iterator

from langchain_core.document_loaders import BaseLoader
from langchain_core.documents import Document
from rscapi.models.franchise_list import FranchiseList
from rscapi.models.franchise_standings import FranchiseStandings

log = logging.getLogger("red.rsc.llm.loaders.franchiseloader")


FRANCHISE_INPUT = """
{name} is an RSC (Rocket Soccar Confederation) franchise and has the prefix or tag "{prefix}". The General Manager, also known as GM, of {name} is {gm}.

{name} has the following teams in their franchise: {teams}

{name} has the following tiers in their franchise: {tiers}

{name} has the following season record.
{record}
"""  # noqa: E501


class FranchiseDocumentLoader(BaseLoader):
    """RSC Franchise Document style loader"""

    def __init__(self, franchises: list[FranchiseList], standings: list[FranchiseStandings] | None = None) -> None:
        self.franchises: list[FranchiseList] = franchises
        self.standings = standings

    def _process_franchises(self) -> Iterator[Document]:
        """Process franchises and yield Documents."""
        for idx, f in enumerate(self.franchises):
            if not (f.name and f.prefix and f.gm and f.gm.rsc_name and f.tiers and f.teams):
                log.warning(f"Skipping franchise {f.id}. Missing required data for LLM input.")
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

            # Get record if available
            record = "No standings or record available"
            if self.standings:
                for s in self.standings:
                    if s.franchise.lower() == f.name.lower():
                        record = f"Wins: {s.wins}\nLosses: {s.losses}"

            content = FRANCHISE_INPUT.format(
                name=f.name,
                prefix=f.prefix,
                gm=f.gm.rsc_name,
                teams=", ".join(teams),
                tiers=", ".join(tiers),
                record=record,
            )

            yield Document(
                page_content=content,
                metadata={"source": "Franchises API", "id": str(f.id), "chunk_index": idx},
            )

    def lazy_load(self) -> Iterator[Document]:
        """A lazy loader that reads RSC Franchise style documents."""
        yield from self._process_franchises()

    async def alazy_load(self) -> AsyncIterator[Document]:
        """An async lazy loader for RSC Franchise documents."""
        for doc in self._process_franchises():
            yield doc
