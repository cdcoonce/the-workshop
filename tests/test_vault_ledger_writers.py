"""Contract for the vault ledger writers (issue #1302, slice 2 of #752).

Every skill that writes `brain/Key Decisions.md` or `perf/Brag Doc.md` states
the same scope test and the same two caps (800 and 700 characters), which the
vault gate `ci/ledger_cap.py` enforces. Assertions pin meaningful phrases, not
whole paragraphs. Numbers match on word boundaries, and the scope test, the cap
phrasing and the nesting ban each accept a small set of equivalent wordings, so
a reword that keeps the rule passes and one that drops it fails. The teeth spec
holds reword controls that prove it.
"""

import re
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parents[1]
WORKBENCH = REPO_ROOT / "plugins" / "workbench"
SKILLS = WORKBENCH / "skills"
WRAP_UP = SKILLS / "vault-wrap-up" / "references" / "command.md"
GRILL = SKILLS / "vault-grill" / "references" / "command.md"
STANDUP = SKILLS / "vault-standup" / "references" / "command.md"
DUMP = SKILLS / "vault-dump" / "references" / "command.md"
RECALL = SKILLS / "vault-recall" / "references" / "command.md"
SPOTTER = WORKBENCH / "agents" / "brag-spotter" / "AGENT.md"

KD_CAP = 800
BRAG_CAP = 700
SCOPE_RE = r"(more than one project|two or more projects) or the vault itself"
NO_NEST_RE = r"(no|without) nested sub-bullets"


def _cap(n: int) -> str:
    return rf"(at most|no more than|up to) \b{n}\b characters"


BRAG_WRITERS = {
    "wrap-up": WRAP_UP,
    "standup": STANDUP,
    "dump": DUMP,
    "recall": RECALL,
}


def _flat(path: Path) -> str:
    """Whitespace-collapsed text so phrase pins survive re-wrapping."""
    return " ".join(path.read_text().split())


def _step(text: str, number: int) -> str:
    """The wrap-up numbered step `number`, up to the next numbered step."""
    start = re.search(rf"(?m)^{number}\. \*\*", text)
    assert start, f"step {number} not found"
    end = re.search(rf"(?m)^{number + 1}\. \*\*", text[start.end() :])
    return text[start.start() : start.end() + end.start()] if end else text[start.start() :]


def _decision_row(text: str) -> str:
    row = re.search(r"\|\s*\*\*Decision\*\*[^\n]*", text)
    assert row, "Decision routing row not found"
    return row.group(0)


def test_wrap_up_key_decisions_scope_is_cross_project_only():
    raw = WRAP_UP.read_text()
    step = " ".join(_step(raw, 6).split())
    assert re.search(SCOPE_RE, step)
    assert "`## Decisions` section on the project note" in step
    assert re.search(r"session status.{0,60}handoff and the project note", step, re.I)
    assert "significant decisions" not in step.lower()


def test_wrap_up_key_decisions_entry_is_capped_and_linked():
    step = " ".join(_step(WRAP_UP.read_text(), 6).split())
    assert re.search(_cap(KD_CAP) + r" including its heading", step)
    assert "one paragraph" in step
    assert re.search(r"wikilink to the full record", step)


def test_grill_routes_per_project_decisions_to_the_project_note():
    row = " ".join(_decision_row(GRILL.read_text()).split())
    assert re.search(SCOPE_RE, row)
    assert "`## Decisions` section on the project note" in row
    assert re.search(rf"\b{KD_CAP}\b", row)


def test_grill_decision_entry_requires_a_wikilink():
    row = " ".join(_decision_row(GRILL.read_text()).split())
    assert "wikilink to the full record" in row


@pytest.mark.parametrize("name", sorted(BRAG_WRITERS))
def test_brag_writers_state_the_one_bullet_shape_and_cap(name):
    text = _flat(BRAG_WRITERS[name])
    assert "one top-level `- **YYYY-MM-DD (...)**` bullet" in text
    assert re.search(NO_NEST_RE, text)
    assert re.search(_cap(BRAG_CAP), text)
    assert "wikilink to the full narrative" in text


@pytest.mark.parametrize("name", sorted(BRAG_WRITERS))
def test_brag_writers_link_rather_than_retell(name):
    assert "linked, not retold" in _flat(BRAG_WRITERS[name])


def test_brag_spotter_states_the_brag_shape_and_cap():
    text = _flat(SPOTTER)
    draft = re.search(r"Suggested Brag Doc entry \([^)]*\)", text)
    assert draft, "step 4 draft line not found"
    assert re.search(_cap(BRAG_CAP), draft.group(0))
    marker = text.find("in the Brag shape:")
    assert marker >= 0, "step 5 shape clause not found"
    shape = text[marker:]
    assert re.search(NO_NEST_RE, shape)
    assert re.search(_cap(BRAG_CAP), shape)
    assert "wikilink to the full narrative" in shape


def test_brag_spotter_never_writes_and_recall_writes_its_candidates():
    spotter = _flat(SPOTTER)
    recall = _flat(RECALL)
    assert "Do NOT modify the Brag Doc" in spotter
    assert re.search(r"proposes? candidates", spotter)
    assert "calling skill" in spotter
    assert "Brag shape" in spotter
    assert re.search(r"proposes? (candidates|Brag Doc entries)", recall)
    assert re.search(r"recall \(the calling skill\) writes", recall, re.I)
    assert "Brag shape" in recall
    # The old self-approval wording contradicted the agent file.
    assert "write the ones that meet its own bar" not in recall


def test_ledger_caps_agree_across_writers():
    files = [WRAP_UP, GRILL, STANDUP, DUMP, RECALL, SPOTTER]
    pattern = re.compile(r"(\d+) characters")
    seen: dict[str, set[int]] = {"Key Decisions": set(), "Brag Doc": set()}
    for path in files:
        text = _flat(path)
        for m in pattern.finditer(text):
            window = text[max(0, m.start() - 160) : m.end() + 30]
            kd = "Key Decisions" in window
            brag = "Brag" in window
            n = int(m.group(1))
            if kd and not brag:
                seen["Key Decisions"].add(n)
            elif brag and not kd:
                seen["Brag Doc"].add(n)
    assert seen["Key Decisions"] == {KD_CAP}
    assert seen["Brag Doc"] == {BRAG_CAP}
    # The gate that enforces both is named wherever caps are stated.
    for path in [WRAP_UP, GRILL, STANDUP, DUMP, RECALL]:
        assert "ci/ledger_cap.py" in _flat(path), path.name
