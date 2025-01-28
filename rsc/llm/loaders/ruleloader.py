import logging
import re
from collections.abc import AsyncIterator, Iterator
from pathlib import Path

import aiofiles
from langchain_core.document_loaders import BaseLoader
from langchain_core.documents import Document

log = logging.getLogger("red.rsc.llm.loaders.ruleloader")


class RuleDocumentLoader(BaseLoader):
    """RSC Rule Document style loader"""

    def __init__(self, file_path: str) -> None:
        self.file_path = file_path
        self.file_name = Path(file_path).stem.replace("-", " ")

    def lazy_load(self) -> Iterator[Document]:
        """A lazy loader that reads RSC Rule style documents."""
        with Path(self.file_path).open(encoding="utf-8") as fd:
            data = fd.read()

            source = None
            rule_group: list[str] = []
            for line in data.splitlines():
                if len(line) == 0:
                    continue

                if m := re.match(r"^#{2,10}\s+(?P<rulenum>(\d\.)+)", line):
                    log.debug(f"Found header: {m}")
                    if rule_group:
                        if source:
                            yield Document(
                                page_content="\n".join(rule_group),
                                metadata={"source": source},
                            )
                        else:
                            yield Document(page_content="\n".join(rule_group))

                        # reset for next group
                        source = None
                        rule_group = []

                    source = f"{self.file_name}: {m.group('rulenum').removesuffix('.')}".strip()
                    rule_group.append(line)
                else:
                    rule_group.append(line)

            # Get final group
            if rule_group:
                if source:
                    yield Document(page_content="\n".join(rule_group), metadata={"source": source})
                else:
                    yield Document(page_content="\n".join(rule_group))

    async def alazy_load(
        self,
    ) -> AsyncIterator[Document]:
        """An async lazy loader for RSC Rule document style files."""
        async with aiofiles.open(self.file_path, encoding="utf-8") as fd:
            data = await fd.read()

            source = None
            rule_group: list[str] = []
            for line in data.splitlines():
                if len(line) == 0:
                    continue

                if m := re.match(r"^#{2,10}\s+(?P<rulenum>(\d\.)+)", line):
                    log.debug(f"Found header: {m}")
                    if rule_group:
                        if source:
                            yield Document(
                                page_content="\n".join(rule_group),
                                metadata={"source": source},
                            )
                        else:
                            yield Document(page_content="\n".join(rule_group))

                        # reset for next group
                        source = None
                        rule_group = []

                    source = f"{self.file_name}: {m.group('rulenum').removesuffix('.')}".strip()
                    rule_group.append(line.strip())
                else:
                    rule_group.append(line.strip())

            # Get final group
            if rule_group:
                if source:
                    yield Document(page_content="\n".join(rule_group), metadata={"source": source})
                else:
                    yield Document(page_content="\n".join(rule_group))
