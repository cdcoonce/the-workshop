"""Tests for the unpromoted-memory write-time check.

The check answers one narrow question about a note that was just written: does it
wikilink an auto-memory slug that has *no* vault note behind it? That is the
promote-before-citing rule failing, and it is worth a distinct warning because it
has a specific repair (promote the memory) that generic "broken link" does not.

The two conditions are both load-bearing and the tests pin each independently:

  1. The target must name a file in machine-local auto-memory.
  2. The link must actually be unresolved *per graphmark*.

Dropping (2) is the tempting simplification and it is wrong: a promoted memory
keeps its auto-memory file, so slug-matching alone fires on every already-fixed
case. Dropping (1) makes this a duplicate of the ordinary broken-link lane.
"""

from __future__ import annotations

import sys
from pathlib import Path

import pytest

ENGINE_DIR = Path(__file__).resolve().parent.parent / "engine"
sys.path.insert(0, str(ENGINE_DIR))

from unpromoted_memory import (  # noqa: E402
    has_candidate_memory_link,
    unpromoted_memory_links,
)


@pytest.fixture
def vault(tmp_path: Path) -> Path:
    root = tmp_path / "vault"
    (root / "reference").mkdir(parents=True)
    (root / "brain").mkdir()
    (root / "CLAUDE.md").write_text("# Vault", encoding="utf-8")
    return root


@pytest.fixture
def mem_base(tmp_path: Path, vault: Path) -> Path:
    """Auto-memory laid out the way Claude Code encodes a project path."""
    base = tmp_path / "projects"
    mem = base / str(vault).replace("/", "-") / "memory"
    mem.mkdir(parents=True)
    (mem / "MEMORY.md").write_text("# Memory Index\n", encoding="utf-8")
    (mem / "absent-rows-cannot-prove-a-detector-fires.md").write_text(
        "a durable lesson", encoding="utf-8"
    )
    (mem / "a-probe-can-measure-itself.md").write_text("promoted already", encoding="utf-8")
    return base


def _write(vault: Path, rel: str, body: str) -> Path:
    p = vault / rel
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text(body, encoding="utf-8")
    return p


class TestUnpromotedMemoryLinks:
    def test_flags_link_to_unpromoted_memory(self, vault: Path, mem_base: Path) -> None:
        _write(
            vault,
            "brain/Key Decisions.md",
            "See [[absent-rows-cannot-prove-a-detector-fires]] for why.\n",
        )

        found = unpromoted_memory_links(
            vault,
            "brain/Key Decisions.md",
            broken={"brain/Key Decisions.md": ["absent-rows-cannot-prove-a-detector-fires"]},
            mem_base=mem_base,
        )

        assert found == [
            (
                "absent-rows-cannot-prove-a-detector-fires",
                "absent-rows-cannot-prove-a-detector-fires.md",
            )
        ]

    def test_promoted_memory_is_not_flagged(self, vault: Path, mem_base: Path) -> None:
        """The regression that makes slug-matching alone unusable.

        ``a-probe-can-measure-itself`` still exists in auto-memory *and* has a vault
        note, so graphmark reports nothing broken. Warning here would fire on ~20
        already-correct links in the live vault and train the user to ignore the hook.
        """
        _write(vault, "reference/a-probe-can-measure-itself.md", "# note")
        _write(vault, "brain/Key Decisions.md", "See [[a-probe-can-measure-itself]].\n")

        found = unpromoted_memory_links(
            vault,
            "brain/Key Decisions.md",
            broken={},  # graphmark resolved it
            mem_base=mem_base,
        )

        assert found == []

    def test_broken_link_with_no_memory_is_not_flagged(
        self, vault: Path, mem_base: Path
    ) -> None:
        """An ordinary missing note belongs to the existing broken-link lane."""
        _write(vault, "brain/Key Decisions.md", "See [[some-note-nobody-wrote]].\n")

        found = unpromoted_memory_links(
            vault,
            "brain/Key Decisions.md",
            broken={"brain/Key Decisions.md": ["some-note-nobody-wrote"]},
            mem_base=mem_base,
        )

        assert found == []

    def test_matches_across_normalization(self, vault: Path, mem_base: Path) -> None:
        """Display text differing only by case/punctuation still names the memory."""
        found = unpromoted_memory_links(
            vault,
            "brain/Key Decisions.md",
            broken={"brain/Key Decisions.md": ["Absent Rows Cannot Prove A Detector Fires"]},
            mem_base=mem_base,
        )

        assert len(found) == 1
        assert found[0][1] == "absent-rows-cannot-prove-a-detector-fires.md"

    def test_only_reports_links_from_the_written_note(
        self, vault: Path, mem_base: Path
    ) -> None:
        """Vault-wide breaks are noise at write time; only the delta is actionable."""
        found = unpromoted_memory_links(
            vault,
            "brain/Key Decisions.md",
            broken={
                "brain/Key Decisions.md": [],
                "personal/other.md": ["absent-rows-cannot-prove-a-detector-fires"],
            },
            mem_base=mem_base,
        )

        assert found == []

    def test_memory_index_is_never_a_target(self, vault: Path, mem_base: Path) -> None:
        """MEMORY.md is the index, not a durable fact; it is not promotable."""
        found = unpromoted_memory_links(
            vault,
            "brain/Key Decisions.md",
            broken={"brain/Key Decisions.md": ["MEMORY"]},
            mem_base=mem_base,
        )

        assert found == []

    def test_absent_auto_memory_is_not_an_error(self, vault: Path, tmp_path: Path) -> None:
        """A fresh machine has no auto-memory; self-sufficiency must hold."""
        found = unpromoted_memory_links(
            vault,
            "brain/Key Decisions.md",
            broken={"brain/Key Decisions.md": ["anything"]},
            mem_base=tmp_path / "does-not-exist",
        )

        assert found == []

    def test_live_scan_finds_the_unpromoted_link(
        self, vault: Path, mem_base: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """With ``broken=None`` the module runs the real scan and reads its shape.

        Paired with the failed-scan test below: together they distinguish "the
        resolver said nothing was broken" from "the resolver never ran". Either
        test alone passes vacuously, since a tmp vault has no ``graph_cli.py`` and
        the scan returns ``None`` regardless of the code under test.
        """
        import unpromoted_memory as um

        monkeypatch.setattr(
            um,
            "_graphmark_broken",
            lambda _root: {
                "brain/Key Decisions.md": [
                    {
                        "display": "absent-rows-cannot-prove-a-detector-fires",
                        "reason": "missing",
                        "candidates": [],
                    }
                ]
            },
        )

        found = unpromoted_memory_links(
            vault, "brain/Key Decisions.md", broken=None, mem_base=mem_base
        )

        assert found == [
            (
                "absent-rows-cannot-prove-a-detector-fires",
                "absent-rows-cannot-prove-a-detector-fires.md",
            )
        ]

    def test_failed_scan_reports_nothing(
        self, vault: Path, mem_base: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """``None`` means the scan failed — never treat that as 'nothing is broken'.

        Same distinction ``broken_links_by_note`` draws. Note the honest limit of this
        test: coercing the failure to an empty dict is currently *equivalent*, because
        the function never falls back to slug-matching. It bites only if someone later
        adds that fallback — which is exactly the change that would fabricate findings,
        so the test is worth keeping as a tripwire rather than as present-tense proof.
        """
        import unpromoted_memory as um

        monkeypatch.setattr(um, "_graphmark_broken", lambda _root: None)

        found = unpromoted_memory_links(
            vault, "brain/Key Decisions.md", broken=None, mem_base=mem_base
        )

        assert found == []

    def test_duplicate_links_report_once(self, vault: Path, mem_base: Path) -> None:
        found = unpromoted_memory_links(
            vault,
            "brain/Key Decisions.md",
            broken={
                "brain/Key Decisions.md": [
                    "absent-rows-cannot-prove-a-detector-fires",
                    "absent-rows-cannot-prove-a-detector-fires",
                ]
            },
            mem_base=mem_base,
        )

        assert len(found) == 1


class TestCandidatePrefilter:
    """The cheap gate that decides whether the resolver subprocess runs at all.

    Correctness never depends on it — it may over-approximate — but it must never
    under-approximate, or the check silently stops firing.
    """

    def test_true_when_a_memory_slug_is_linked(self, vault: Path, mem_base: Path) -> None:
        note = _write(
            vault,
            "brain/Key Decisions.md",
            "See [[absent-rows-cannot-prove-a-detector-fires]].\n",
        )

        assert has_candidate_memory_link(note, vault, mem_base=mem_base) is True

    def test_false_when_no_wikilinks_at_all(self, vault: Path, mem_base: Path) -> None:
        note = _write(vault, "brain/Key Decisions.md", "Plain prose, no links.\n")

        assert has_candidate_memory_link(note, vault, mem_base=mem_base) is False

    def test_false_when_links_name_no_memory(self, vault: Path, mem_base: Path) -> None:
        note = _write(vault, "brain/Key Decisions.md", "See [[Some Other Note]].\n")

        assert has_candidate_memory_link(note, vault, mem_base=mem_base) is False

    def test_true_for_promoted_memory_link(self, vault: Path, mem_base: Path) -> None:
        """Over-approximation is fine here — the resolver settles it in the next step."""
        note = _write(vault, "brain/Key Decisions.md", "See [[a-probe-can-measure-itself]].\n")

        assert has_candidate_memory_link(note, vault, mem_base=mem_base) is True

    def test_alias_pipe_display_is_matched_on_target(
        self, vault: Path, mem_base: Path
    ) -> None:
        """``[[target|shown text]]`` links the target, not the display."""
        note = _write(
            vault,
            "brain/Key Decisions.md",
            "See [[absent-rows-cannot-prove-a-detector-fires|the lesson]].\n",
        )

        assert has_candidate_memory_link(note, vault, mem_base=mem_base) is True

    def test_unreadable_file_is_false_not_an_exception(
        self, vault: Path, mem_base: Path
    ) -> None:
        assert has_candidate_memory_link(vault / "nope.md", vault, mem_base=mem_base) is False
