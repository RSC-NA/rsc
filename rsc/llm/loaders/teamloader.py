import logging
from collections.abc import AsyncIterator, Iterator

from langchain_core.document_loaders import BaseLoader
from langchain_core.documents import Document
from rscapi.models.team import Team

log = logging.getLogger("red.rsc.llm.loaders.teamloader")


TEAM_INPUT = """
{name} is a team in the {tier} tier. {name} is a team within the franchise "{franchise}"

{name} has the following players on their roster:
{players}

{captain}
"""


class TeamDocumentLoader(BaseLoader):
    """RSC Rule Document style loader"""

    def __init__(self, teams: list[Team]) -> None:
        self.teams: list[Team] = teams

    def _process_teams(self) -> Iterator[Document]:
        """Process teams and yield Documents."""
        for idx, t in enumerate(self.teams):
            if not (t.id and t.name and t.players):
                continue

            log.debug(f"Processing team: {t.name} ({t.id})")
            team_name: str = t.name
            franchise: str = t.franchise
            tier: str = t.tier

            captain: str | None = None
            players: list[str] = []
            for p in t.players:
                if p.captain:
                    captain = f"The current captain of {team_name} is {p.name}."
                players.append(p.name)

            if players:  # noqa: SIM108
                players_fmt = "\n".join([f"- {pname}" for pname in players])
            else:
                players_fmt = f"No players currently rostered on {team_name}."

            if not captain:
                captain = f"Currently there is no designated captain for {team_name}."

            yield Document(
                page_content=TEAM_INPUT.format(
                    name=team_name,
                    franchise=franchise,
                    tier=tier,
                    players=players_fmt,
                    captain=captain,
                ),
                metadata={"source": "Teams API", "id": str(t.id), "chunk_index": idx},
            )

    def lazy_load(self) -> Iterator[Document]:
        """A lazy loader that reads RSC Rule style documents."""
        yield from self._process_teams()

    async def alazy_load(self) -> AsyncIterator[Document]:
        """An async lazy loader for RSC team documents."""
        for doc in self._process_teams():
            yield doc
