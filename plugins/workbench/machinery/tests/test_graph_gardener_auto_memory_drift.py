"""Tests for the auto-memory drift detector lane of the Graph Gardener.

Red-Green-Refactor: these tests were written BEFORE the implementation.
They cover detect_auto_memory_drift(), proposal_signature("memdrift", ...), and
the write_queue() ### Auto-memory drift rendering.
"""

from __future__ import annotations

import importlib.util
from pathlib import Path

# ---------------------------------------------------------------------------
# Module bootstrap — load graph_gardener without adding it to the package
# ---------------------------------------------------------------------------

SCRIPTS_DIR = Path(__file__).resolve().parent.parent / "engine"

_spec = importlib.util.spec_from_file_location(
    "graph_gardener", SCRIPTS_DIR / "graph_gardener.py"
)
gg = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(gg)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _make_broken_proposal(note_rel: str, display: str) -> str:
    """Build a broken-link proposal string matching the real gardener format."""
    sig = gg.proposal_signature("broken", note_rel, display)
    return (
        f"`{note_rel}`: broken `[[{display}]]` — no matching note "
        f"(consider creating or removing)"
        f" <!-- gsig: {sig} -->"
    )


def _make_memory_dir(mem_base: Path, vault_root: Path) -> Path:
    """Create the expected auto-memory directory under mem_base."""
    slug = str(vault_root).replace("/", "-")
    mem_dir = mem_base / slug / "memory"
    mem_dir.mkdir(parents=True, exist_ok=True)
    return mem_dir


# ---------------------------------------------------------------------------
# detect_auto_memory_drift tests
# ---------------------------------------------------------------------------

def test_detect_drift_returns_slug_and_filename(tmp_path):
    """A *.md file in memory/ appears in the drift dict with correct keys."""
    vault_root = tmp_path / "vault"
    vault_root.mkdir()
    mem_base = tmp_path / "claude-projects"
    mem_dir = _make_memory_dir(mem_base, vault_root)
    (mem_dir / "afk-dogfood-to-build-data.md").write_text("# memory fact")

    drift = gg.detect_auto_memory_drift(vault_root, _mem_base=mem_base)

    assert "afk dogfood to build data" in drift
    assert drift["afk dogfood to build data"] == "afk-dogfood-to-build-data.md"


def test_detect_drift_excludes_memory_index(tmp_path):
    """MEMORY.md is not a memory fact — it must be excluded from drift detection."""
    vault_root = tmp_path / "vault"
    vault_root.mkdir()
    mem_base = tmp_path / "claude-projects"
    mem_dir = _make_memory_dir(mem_base, vault_root)
    (mem_dir / "MEMORY.md").write_text("# index")

    drift = gg.detect_auto_memory_drift(vault_root, _mem_base=mem_base)

    assert drift == {}


def test_detect_drift_absent_dir_returns_empty_no_exception(tmp_path):
    """Auto-memory dir absent → empty dict, no exception (self-sufficiency held)."""
    vault_root = tmp_path / "vault"
    vault_root.mkdir()
    mem_base = tmp_path / "nonexistent-claude"  # dir never created

    drift = gg.detect_auto_memory_drift(vault_root, _mem_base=mem_base)

    assert drift == {}


def test_detect_drift_multiple_files(tmp_path):
    """Multiple memory files all appear in the dict."""
    vault_root = tmp_path / "vault"
    vault_root.mkdir()
    mem_base = tmp_path / "claude-projects"
    mem_dir = _make_memory_dir(mem_base, vault_root)
    (mem_dir / "afk-dogfood-to-build-data.md").write_text("# fact 1")
    (mem_dir / "charles-prefers-autonomous-momentum.md").write_text("# fact 2")

    drift = gg.detect_auto_memory_drift(vault_root, _mem_base=mem_base)

    assert "afk dogfood to build data" in drift
    assert "charles prefers autonomous momentum" in drift
    assert len(drift) == 2


# ---------------------------------------------------------------------------
# proposal_signature for memdrift
# ---------------------------------------------------------------------------

def test_proposal_signature_memdrift():
    """memdrift signatures use 'memdrift|<normalized-slug>' format."""
    sig = gg.proposal_signature("memdrift", "", "afk dogfood to build data")
    assert sig == "memdrift|afk dogfood to build data"


# ---------------------------------------------------------------------------
# write_queue: drift section rendered, drift removed from broken
# ---------------------------------------------------------------------------

def test_write_queue_drift_entry_in_drift_section(tmp_path):
    """Broken proposal matching auto-memory → appears in Auto-memory drift section."""
    proposal = _make_broken_proposal("brain/Note.md", "afk-dogfood-to-build-data")
    lane_a = gg.LaneAResult()
    lane_a.proposals.append(proposal)
    memdrift = {"afk dogfood to build data": "afk-dogfood-to-build-data.md"}

    queue_path = gg.write_queue(
        tmp_path, "personal",
        lane_a, {},
        dry_run=False, dismissed=set(),
        memdrift=memdrift,
    )
    content = queue_path.read_text()

    assert "### Auto-memory drift (promote to vault)" in content
    drift_section = content.split("### Auto-memory drift (promote to vault)")[1].split("###")[0]
    assert "afk-dogfood-to-build-data.md" in drift_section
    assert "gsig: memdrift|afk dogfood to build data" in drift_section


def test_write_queue_drift_entry_not_in_broken_section(tmp_path):
    """Broken proposal matching auto-memory → removed from plain Broken links section."""
    proposal = _make_broken_proposal("brain/Note.md", "afk-dogfood-to-build-data")
    lane_a = gg.LaneAResult()
    lane_a.proposals.append(proposal)
    memdrift = {"afk dogfood to build data": "afk-dogfood-to-build-data.md"}

    queue_path = gg.write_queue(
        tmp_path, "personal",
        lane_a, {},
        dry_run=False, dismissed=set(),
        memdrift=memdrift,
    )
    content = queue_path.read_text()

    broken_section = content.split("### Broken links (unresolved)")[1].split("###")[0]
    assert "afk-dogfood-to-build-data" not in broken_section
    assert "_(none)_" in broken_section


def test_write_queue_non_drift_broken_stays_in_broken_section(tmp_path):
    """Broken proposal not matching auto-memory → stays in plain Broken links."""
    proposal = _make_broken_proposal("brain/Note.md", "truly-missing-note")
    lane_a = gg.LaneAResult()
    lane_a.proposals.append(proposal)
    memdrift = {"afk dogfood to build data": "afk-dogfood-to-build-data.md"}

    queue_path = gg.write_queue(
        tmp_path, "personal",
        lane_a, {},
        dry_run=False, dismissed=set(),
        memdrift=memdrift,
    )
    content = queue_path.read_text()

    broken_section = content.split("### Broken links (unresolved)")[1].split("###")[0]
    assert "truly-missing-note" in broken_section
    # And it must not appear in the drift section
    drift_section = content.split("### Auto-memory drift (promote to vault)")[1].split("###")[0]
    assert "truly-missing-note" not in drift_section


def test_write_queue_drift_count_reflects_multiple_source_notes(tmp_path):
    """Multiple broken proposals for the same slug → drift shows the vault-link count."""
    proposals = [
        _make_broken_proposal("brain/Note1.md", "afk-dogfood-to-build-data"),
        _make_broken_proposal("brain/Note2.md", "afk-dogfood-to-build-data"),
        _make_broken_proposal("personal/Note3.md", "afk-dogfood-to-build-data"),
    ]
    lane_a = gg.LaneAResult()
    lane_a.proposals.extend(proposals)
    memdrift = {"afk dogfood to build data": "afk-dogfood-to-build-data.md"}

    queue_path = gg.write_queue(
        tmp_path, "personal",
        lane_a, {},
        dry_run=False, dismissed=set(),
        memdrift=memdrift,
    )
    content = queue_path.read_text()

    drift_section = content.split("### Auto-memory drift (promote to vault)")[1].split("###")[0]
    assert "3" in drift_section


def test_write_queue_dismissed_memdrift_suppressed(tmp_path):
    """Dismissed memdrift|<slug> → suppressed from drift section."""
    proposal = _make_broken_proposal("brain/Note.md", "afk-dogfood-to-build-data")
    lane_a = gg.LaneAResult()
    lane_a.proposals.append(proposal)
    memdrift = {"afk dogfood to build data": "afk-dogfood-to-build-data.md"}
    dismissed = {"memdrift|afk dogfood to build data"}

    queue_path = gg.write_queue(
        tmp_path, "personal",
        lane_a, {},
        dry_run=False, dismissed=dismissed,
        memdrift=memdrift,
    )
    content = queue_path.read_text()

    drift_section = content.split("### Auto-memory drift (promote to vault)")[1].split("###")[0]
    assert "afk-dogfood-to-build-data.md" not in drift_section
    assert "_(none)_" in drift_section


def test_write_queue_renders_none_when_no_drift(tmp_path):
    """Empty memdrift → ### Auto-memory drift section with _(none)_."""
    queue_path = gg.write_queue(
        tmp_path, "personal",
        gg.LaneAResult(), {},
        dry_run=False, dismissed=set(),
        memdrift={},
    )
    content = queue_path.read_text()

    assert "### Auto-memory drift (promote to vault)" in content
    drift_section = content.split("### Auto-memory drift (promote to vault)")[1].split("###")[0]
    assert "_(none)_" in drift_section


def test_write_queue_normalization_case_insensitive_match(tmp_path):
    """Slug matching is normalization-insensitive: [[AFk-DogFood]] matches afk-dogfood.md."""
    proposal = _make_broken_proposal("brain/Note.md", "AFk-DogFood-To-Build-Data")
    lane_a = gg.LaneAResult()
    lane_a.proposals.append(proposal)
    # drift dict key must match the normalized form of the broken display
    memdrift = {gg._normalize("afk-dogfood-to-build-data"): "afk-dogfood-to-build-data.md"}

    queue_path = gg.write_queue(
        tmp_path, "personal",
        lane_a, {},
        dry_run=False, dismissed=set(),
        memdrift=memdrift,
    )
    content = queue_path.read_text()

    drift_section = content.split("### Auto-memory drift (promote to vault)")[1].split("###")[0]
    assert "afk-dogfood-to-build-data.md" in drift_section
    broken_section = content.split("### Broken links (unresolved)")[1].split("###")[0]
    assert "AFk-DogFood-To-Build-Data" not in broken_section


def test_write_queue_memdrift_none_default_behaves_as_empty(tmp_path):
    """write_queue with no memdrift kwarg → drift section still present with _(none)_."""
    proposal = _make_broken_proposal("brain/Note.md", "some-broken-link")
    lane_a = gg.LaneAResult()
    lane_a.proposals.append(proposal)

    # No memdrift kwarg — uses default
    queue_path = gg.write_queue(
        tmp_path, "personal",
        lane_a, {},
        dry_run=False, dismissed=set(),
    )
    content = queue_path.read_text()

    assert "### Auto-memory drift (promote to vault)" in content
    drift_section = content.split("### Auto-memory drift (promote to vault)")[1].split("###")[0]
    assert "_(none)_" in drift_section
    # Broken proposal stays in broken section
    broken_section = content.split("### Broken links (unresolved)")[1].split("###")[0]
    assert "some-broken-link" in broken_section
