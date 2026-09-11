"""Contract tests for the shared agent-laws doc and its `scripts/stamp.py`
cross-plugin distribution (issue #852).

Written as teeth-checks, matching `test_stamp.py`'s style: for each guarantee
(pointer presence in every AGENT.md, byte-identical cross-plugin copy, drift
detection on both the pointer and the copy), the test introduces the defect
the guarantee exists to catch and asserts the stamper notices it — by name,
non-zero exit. A drift gate that has never been observed failing is not
evidence of anything.
"""

from __future__ import annotations

from pathlib import Path

import pytest

from scripts import stamp

REPO_ROOT = Path(__file__).resolve().parents[1]

# The seed set from issue #852 — the complete law list, not to be mined for
# more at build time.
_SEED_LAWS = (
    "Write the failing test first",
    "Pass `model` explicitly on any nested dispatch",
    "Conventional commits; stage explicitly; never `git add .`",
    "Branch from freshly fetched `origin/main`",
    "Report status honestly",
)

_REAL_AGENT_MD = sorted(
    {
        str(p.relative_to(REPO_ROOT))
        for p in (REPO_ROOT / "plugins/workbench/agents").glob("*/AGENT.md")
    }
    | {
        str(p.relative_to(REPO_ROOT))
        for p in (REPO_ROOT / "plugins/workshop-maintainer/agents").glob("*/AGENT.md")
    }
)


# --------------------------------------------------------------------------
# The real tree
# --------------------------------------------------------------------------


def test_exactly_19_agent_md_files_exist() -> None:
    """Guards the fixture itself: 13 workbench + 6 workshop-maintainer."""
    assert len(_REAL_AGENT_MD) == 19, (
        f"expected exactly 19 AGENT.md files across workbench + "
        f"workshop-maintainer, found {len(_REAL_AGENT_MD)}: {_REAL_AGENT_MD}"
    )


def test_the_source_laws_doc_exists_with_the_seed_set() -> None:
    path = REPO_ROOT / "plugins/workbench/docs/agent-laws.md"
    assert path.exists(), f"{path} is missing"
    text = path.read_text()
    missing = [law for law in _SEED_LAWS if law not in text]
    assert not missing, f"agent-laws.md is missing seed law(s): {missing}"


def test_the_workshop_maintainer_copy_is_byte_identical_to_the_source() -> None:
    copy_path = REPO_ROOT / "plugins/workshop-maintainer/docs/agent-laws.md"
    assert copy_path.exists(), f"{copy_path} is missing"
    assert copy_path.read_text() == stamp.render_agent_laws(REPO_ROOT)


def test_every_real_agent_md_carries_its_own_plugins_laws_pointer() -> None:
    """AC: every AGENT.md (both plugins) points at its own plugin's copy.

    This is the test that must go red when a teeth-check removes the pointer
    line from a real AGENT.md file.
    """
    missing = []
    for relative_path in _REAL_AGENT_MD:
        plugin = relative_path.split("/")[1]  # plugins/<plugin>/agents/.../AGENT.md
        expected = f"plugins/{plugin}/docs/agent-laws.md"
        text = (REPO_ROOT / relative_path).read_text()
        if expected not in text:
            missing.append(relative_path)
    assert not missing, f"these AGENT.md files lack their laws pointer: {missing}"


# --------------------------------------------------------------------------
# Synthetic teeth-checks against the stamp.py mechanism
# --------------------------------------------------------------------------


def _pointer_line(plugin: str) -> str:
    return (
        f"Read `plugins/{plugin}/docs/agent-laws.md` for the fleet's "
        "operational laws and follow them.\n"
    )


def _agent_body_with_pointer(plugin: str) -> str:
    return (
        "---\nname: demo-agent\ndescription: Test agent.\nrole: builder\n---\n\n"
        "# Demo Agent\n\nDoes a thing.\n\n" + _pointer_line(plugin)
    )


def _wire_agent_laws_fixture(root: Path, make_plugin) -> tuple[Path, Path]:
    """A workbench (source) + workshop-maintainer (copy consumer) pair.

    Each ships one agent whose body already carries the correct pointer, so
    this fixture represents the post-fix, green state — individual tests
    mutate it to force red.
    """
    workbench = make_plugin(root, "workbench", agents=["demo-agent"])
    (workbench / "docs").mkdir(parents=True, exist_ok=True)
    (workbench / "docs" / "agent-laws.md").write_text(
        "# Agent Laws\n\n- Write the failing test first.\n"
    )
    (workbench / "agents" / "demo-agent" / "AGENT.md").write_text(
        _agent_body_with_pointer("workbench")
    )

    maintainer = make_plugin(root, "workshop-maintainer", agents=["other-agent"])
    (maintainer / "agents" / "other-agent" / "AGENT.md").write_text(
        _agent_body_with_pointer("workshop-maintainer")
    )
    return workbench, maintainer


def test_the_copy_is_rendered_for_the_non_source_agent_bearing_plugin(
    flat_repo: Path, make_plugin
):
    _, maintainer = _wire_agent_laws_fixture(flat_repo, make_plugin)
    stamp.stamp(flat_repo)
    copy = maintainer / "docs" / "agent-laws.md"
    assert copy.exists()
    assert "Write the failing test first." in copy.read_text()
    assert stamp.GENERATED_MARKER in copy.read_text()


def test_the_source_plugins_own_copy_is_never_owned_by_the_stamper(
    flat_repo: Path, make_plugin
):
    """workbench's agent-laws.md is hand-written; the stamper must not own it.

    Mirrors `test_the_claude_manifest_is_never_owned` in test_stamp.py: the
    canonical source and its generated mirror must never be the same path.
    """
    _wire_agent_laws_fixture(flat_repo, make_plugin)
    owned = {p.relative_to(flat_repo).as_posix() for p in stamp.owned_paths(flat_repo)}
    assert "plugins/workbench/docs/agent-laws.md" not in owned


def test_a_missing_pointer_fails_the_stamp_naming_the_file(flat_repo: Path, make_plugin):
    workbench, _ = _wire_agent_laws_fixture(flat_repo, make_plugin)
    agent_md = workbench / "agents" / "demo-agent" / "AGENT.md"
    agent_md.write_text(agent_md.read_text().replace(_pointer_line("workbench"), ""))

    with pytest.raises(stamp.StampError) as excinfo:
        stamp.stamp(flat_repo)

    assert "demo-agent/AGENT.md" in str(excinfo.value)


def test_a_drifted_copy_is_named_by_check(flat_repo: Path, make_plugin, capsys):
    _, maintainer = _wire_agent_laws_fixture(flat_repo, make_plugin)
    stamp.stamp(flat_repo)
    copy = maintainer / "docs" / "agent-laws.md"
    copy.write_text(copy.read_text() + "\nhand-edited drift\n")

    exit_code = stamp.main(["--check"], root=flat_repo)
    captured = capsys.readouterr()

    assert exit_code == 1, "a hand-edited agent-laws copy did not fail the gate"
    assert "workshop-maintainer/docs/agent-laws.md" in (
        captured.err + captured.out
    ), "the drift was not reported by name"


def test_restamping_after_a_drifted_copy_fixes_it(flat_repo: Path, make_plugin):
    _, maintainer = _wire_agent_laws_fixture(flat_repo, make_plugin)
    stamp.stamp(flat_repo)
    copy = maintainer / "docs" / "agent-laws.md"
    copy.write_text(copy.read_text() + "\nhand-edited drift\n")

    stamp.stamp(flat_repo)

    assert "hand-edited drift" not in copy.read_text()
    assert stamp.main(["--check"], root=flat_repo) == 0


def test_missing_canonical_is_a_loud_failure_when_a_copy_is_needed(
    flat_repo: Path, make_plugin
):
    """No workbench plugin at all: the copy consumer's agents cannot resolve
    a canonical to render from, and that must fail loudly rather than ship a
    silently-missing copy.
    """
    maintainer = make_plugin(flat_repo, "workshop-maintainer", agents=["other-agent"])
    (maintainer / "agents" / "other-agent" / "AGENT.md").write_text(
        _agent_body_with_pointer("workshop-maintainer")
    )

    with pytest.raises(stamp.StampError) as excinfo:
        stamp.stamp(flat_repo)

    assert "agent-laws.md" in str(excinfo.value)


def test_stamping_the_agent_laws_copy_twice_changes_nothing(flat_repo: Path, make_plugin):
    """Rendering must be deterministic, or the gate flaps against itself."""
    _, maintainer = _wire_agent_laws_fixture(flat_repo, make_plugin)
    stamp.stamp(flat_repo)
    copy = maintainer / "docs" / "agent-laws.md"
    first = copy.read_bytes()
    stamp.stamp(flat_repo)
    assert copy.read_bytes() == first
