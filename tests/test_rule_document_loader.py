from pathlib import Path

from rsc.llm.loaders.ruleloader import RuleDocumentLoader


def write_rulebook(tmp_path: Path, content: str) -> Path:
    file_path = tmp_path / "RSC Rules.md"
    file_path.write_text(content, encoding="utf-8")
    return file_path


def test_glossary_entries_are_split_into_stable_documents(tmp_path: Path) -> None:
    file_path = write_rulebook(
        tmp_path,
        """
# **Rocket Soccar Confederation Rules**

# **General Glossary**

"General Manager", "GM" - The leader of one and only one franchise.

"Permanent Free Agent", "PermFa" - A player who is not contracted to any team.

### 1. Introduction
"This is not a glossary entry" - because it appears after the rules start.
""",
    )

    docs = list(RuleDocumentLoader(str(file_path)).lazy_load_glossary())

    assert [doc.metadata["id"] for doc in docs] == ["glossary:general-manager", "glossary:permanent-free-agent"]
    assert docs[0].metadata["term"] == "General Manager"
    assert docs[0].metadata["aliases"] == "GM"
    assert docs[0].metadata["source"] == "RSC Rules: Glossary: General Manager"
    assert "Glossary Term: General Manager" in docs[0].page_content
    assert "Aliases: GM" in docs[0].page_content


def test_rule_documents_include_tree_metadata_and_child_context(tmp_path: Path) -> None:
    file_path = write_rulebook(
        tmp_path,
        """
# **General Glossary**

"Tier" - A defined skill range.

## 2. League Format

### 2.4. Regular season

- 2.4.3. If 3 or more teams have the same regular season win percentage, ties use these tiebreakers.
  - 2.4.3.1. Break any in-division ties before figuring out the rest of the tiebreaker.
    This continuation should stay attached to rule 2.4.3.1.
  - 2.4.3.2. Head to head win percentage.

### **DISCLAIMER**
This should not be appended to the final rule.
""",
    )

    docs = {doc.metadata["id"]: doc for doc in RuleDocumentLoader(str(file_path)).lazy_load()}

    assert set(docs) == {"2", "2.4", "2.4.3", "2.4.3.1", "2.4.3.2"}
    assert docs["2.4.3.1"].metadata["parent_rule_number"] == "2.4.3"
    assert docs["2.4.3.1"].metadata["ancestor_rule_numbers"] == "2|2.4|2.4.3"
    assert docs["2.4.3.1"].metadata["depth"] == 4
    assert "2 League Format > 2.4 Regular season > 2.4.3" in docs["2.4.3.1"].metadata["rule_path"]
    assert "Parent Rule: 2.4.3" in docs["2.4.3.1"].page_content
    assert "This continuation should stay attached" in docs["2.4.3.1"].page_content
    assert "Direct Subrules:\n- 2.4.3.1" in docs["2.4.3"].page_content
    assert "DISCLAIMER" not in docs["2.4.3.2"].page_content


def test_old_zero_width_rule_markers_are_normalized(tmp_path: Path) -> None:
    file_path = write_rulebook(
        tmp_path,
        """
## 1.​ Introduction

#### 1.1.​ Signing-up for RSC

1.1.1.​ Players must have their own discord account.
""",
    )

    docs = list(RuleDocumentLoader(str(file_path)).lazy_load())

    assert [doc.metadata["id"] for doc in docs] == ["1", "1.1", "1.1.1"]
    assert docs[1].metadata["source"] == "RSC Rules: 1.1"
    assert "\u200b" not in docs[2].page_content


def test_current_rulebook_extracts_rules_and_glossary_without_unsourced_documents() -> None:
    file_path = Path(__file__).parent.parent / "rsc" / "resources" / "rules" / "RSC Rules.md"
    loader = RuleDocumentLoader(str(file_path))

    rule_docs = list(loader.lazy_load())
    glossary_docs = list(loader.lazy_load_glossary())
    rule_ids = [str(doc.metadata["id"]) for doc in rule_docs]
    glossary_ids = {doc.metadata["id"] for doc in glossary_docs}
    leaf = next(doc for doc in rule_docs if doc.metadata["id"] == "2.4.3.1")

    assert rule_docs
    assert glossary_docs
    assert len(rule_ids) == len(set(rule_ids))
    assert all(doc.metadata.get("source") and doc.metadata.get("rule_number") for doc in rule_docs)
    assert leaf.metadata["parent_rule_number"] == "2.4.3"
    assert leaf.metadata["ancestor_rule_numbers"] == "2|2.4|2.4.3"
    assert "glossary:general-manager" in glossary_ids
    assert "glossary:permanent-free-agent" in glossary_ids
    assert "glossary:waivers" in glossary_ids
