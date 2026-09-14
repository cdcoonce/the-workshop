from __future__ import annotations

import builtins
import importlib.metadata
import os
import subprocess
import sys
import unicodedata
from pathlib import Path

import pytest

SCRIPTS_DIR = Path(__file__).resolve().parent.parent / "engine"
sys.path.insert(0, str(SCRIPTS_DIR))

from wrap_up_audit import VERDICT_EXIT_CODES, collect, main  # noqa: E402


def _graphmark_at_least_0_7() -> bool:
    try:
        ver = importlib.metadata.version("graphmark")
    except importlib.metadata.PackageNotFoundError:
        return False
    parts = ver.split(".")
    try:
        major, minor = int(parts[0]), int(parts[1])
    except (IndexError, ValueError):
        return False
    return (major, minor) >= (0, 7)


NEEDS_GRAPHMARK_07 = pytest.mark.skipif(
    not _graphmark_at_least_0_7(),
    reason="requires graphmark>=0.7 (see make test-wrap-up-gate-parity)",
)


def _write(root: Path, rel: str, text: str) -> Path:
    path = root / rel
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text, encoding="utf-8")
    return path


def _note(title: str, tags: str = "reference", body: str = "Short body.") -> str:
    return (
        "---\n"
        "date: 2026-07-08\n"
        f"description: \"{title}\"\n"
        "tags:\n"
        f"  - {tags}\n"
        "---\n\n"
        f"# {title}\n\n"
        f"{body}\n"
    )


def _gate_file(max_unresolved_links: int = 0, max_orphans: int = 3) -> str:
    """A gate file shaped like the real ci/vault_health.py: one module-level
    POLICY, applied via check=POLICY inside a function — not just a bare
    POLICY assignment with nothing ever reading it.
    """
    return (
        "from graphmark.config import CheckPolicy\n\n"
        "POLICY = CheckPolicy(\n"
        f"    max_unresolved_links={max_unresolved_links},\n"
        f"    max_orphans={max_orphans},\n"
        ")\n\n"
        "def main():\n"
        "    config = dict(check=POLICY)\n"
        "    return config\n"
    )


PERMISSIVE_GATE_POLICY = _gate_file(max_unresolved_links=1000, max_orphans=1000)


def _git_init(repo: Path) -> None:
    """git init, plus a permissive gate file and a minimal handoff.

    Most fixtures don't care about the `gate` or `handoff_sections` checks at
    all — but both now go INCOMPLETE when their file is missing (items 1 and
    6), so every baseline fixture needs SOME `ci/vault_health.py` and
    `.vault-context` + handoff to reach CLEAN/FINDINGS instead. Seeded here
    so ordinary tests don't have to think about it; tests that specifically
    exercise the missing-file/bad-policy paths overwrite or delete these
    afterward.
    """
    subprocess.run(["git", "init", "-q"], cwd=repo, check=True)
    subprocess.run(["git", "config", "user.email", "test@example.com"], cwd=repo, check=True)
    subprocess.run(["git", "config", "user.name", "Test"], cwd=repo, check=True)
    _write(repo, "ci/vault_health.py", PERMISSIVE_GATE_POLICY)
    _write(repo, ".vault-context", "personal")
    _write(repo, ".brain/handoff-personal.md", "## Resume From Here\nNothing yet.\n")


def _git_commit_all(repo: Path, message: str) -> None:
    subprocess.run(["git", "add", "-A"], cwd=repo, check=True)
    subprocess.run(["git", "commit", "-q", "-m", message], cwd=repo, check=True)


def _git_rev_parse(repo: Path, ref: str) -> str:
    result = subprocess.run(
        ["git", "rev-parse", ref], cwd=repo, check=True, capture_output=True, text=True
    )
    return result.stdout.strip()


def _handoff_text() -> str:
    return (
        "Preamble line.\n\n"
        "## Resume From Here\n"
        "Old resume text.\n\n"
        "## Open Threads\n"
        "Old open threads text.\n\n"
        "## Notes\n"
        "Old notes text.\n"
    )


GATE_POLICY_3_0 = _gate_file(max_unresolved_links=0, max_orphans=3)

GATE_POLICY_NON_LITERAL = (
    "from graphmark.config import CheckPolicy\n\n"
    "_max = 3\n\n"
    "POLICY = CheckPolicy(\n"
    "    max_unresolved_links=0,\n"
    "    max_orphans=_max,\n"
    ")\n\n"
    "def main():\n"
    "    config = dict(check=POLICY)\n"
    "    return config\n"
)

GATE_POLICY_BOOL_KEYWORD = (
    "from graphmark.config import CheckPolicy\n\n"
    "POLICY = CheckPolicy(\n"
    "    max_unresolved_links=True,\n"
    "    max_orphans=3,\n"
    ")\n\n"
    "def main():\n"
    "    config = dict(check=POLICY)\n"
    "    return config\n"
)

# MEDIUM-B variants: each currently gives a FALSE CLEAN — the naive parser
# grabs a policy that isn't the one actually applied at runtime. All must
# now be INCOMPLETE.

GATE_TWO_ASSIGNMENTS = (
    "from graphmark.config import CheckPolicy\n\n"
    "POLICY = CheckPolicy(max_unresolved_links=0, max_orphans=1000)\n"
    "POLICY = CheckPolicy(max_unresolved_links=0, max_orphans=3)\n\n"
    "def main():\n"
    "    config = dict(check=POLICY)\n"
    "    return config\n"
)

GATE_IF_BLOCK_POLICY = (
    "from graphmark.config import CheckPolicy\n\n"
    "POLICY = CheckPolicy(max_unresolved_links=0, max_orphans=1000)\n\n"
    "if True:\n"
    "    POLICY = CheckPolicy(max_unresolved_links=0, max_orphans=3)\n\n"
    "def main():\n"
    "    config = dict(check=POLICY)\n"
    "    return config\n"
)

GATE_UNUSED_POLICY = (
    "from graphmark.config import CheckPolicy\n\n"
    "POLICY = CheckPolicy(max_unresolved_links=0, max_orphans=3)\n\n"
    "def main():\n"
    "    config = dict(check=CheckPolicy(max_unresolved_links=0, max_orphans=1000))\n"
    "    return config\n"
)

GATE_REPLACE_POLICY = (
    "from graphmark.config import CheckPolicy\n"
    "import dataclasses\n\n"
    "POLICY = CheckPolicy(max_unresolved_links=0, max_orphans=3)\n\n"
    "def main():\n"
    "    config = dict(check=dataclasses.replace(POLICY, max_orphans=1000))\n"
    "    return config\n"
)

# round 4 — n4/n4b/n4c: minimal fixtures isolating each individual guard in
# _parse_gate_policy, one condition at a time (not bundled with the round-3
# multi-assignment scenarios, which trip a DIFFERENT guard first).

# n4: a single, valid, module-level POLICY — but check= is never used
# anywhere, not even as dict(check=POLICY). This is the shape that existed
# before round 3 and read as a valid policy despite nothing ever applying it.
GATE_POLICY_NO_CHECK_USAGE = (
    "from graphmark.config import CheckPolicy\n\n"
    "POLICY = CheckPolicy(\n"
    "    max_unresolved_links=0,\n"
    "    max_orphans=3,\n"
    ")\n"
)

# n4b: check=POLICY in one call, but ALSO check=CheckPolicy(...) with a
# different value in another — the file really can enforce a policy this
# parser never saw.
GATE_POLICY_CONFLICTING_CHECK_USAGE = (
    "from graphmark.config import CheckPolicy\n\n"
    "POLICY = CheckPolicy(max_unresolved_links=0, max_orphans=3)\n\n"
    "def main():\n"
    "    good = dict(check=POLICY)\n"
    "    bad = dict(check=CheckPolicy(max_orphans=99))\n"
    "    return good, bad\n"
)

# n4c: exactly one POLICY assignment — but it lives inside an `if` block,
# not at module level, with check=POLICY present so n4/n4b's guards pass.
GATE_POLICY_ONLY_IN_IF_BLOCK = (
    "from graphmark.config import CheckPolicy\n\n"
    "if True:\n"
    "    POLICY = CheckPolicy(max_unresolved_links=0, max_orphans=3)\n\n"
    "def main():\n"
    "    return dict(check=POLICY)\n"
)


OWNER_VAULT_SCOPE_WITH_SCHOOL = '''
from __future__ import annotations
from pathlib import Path

GOVERNED_NOTE_DIRS = ("brain", "work", "personal", "org", "perf", "reference", "school")
GRAPH_NOTE_DIRS = (*GOVERNED_NOTE_DIRS, "thinking")
GRAPH_EXCLUDED_DIRS = {".afk", ".brain", ".claude", ".codex", ".obsidian", ".pytest_cache", ".superpowers", ".venv", "session-logs", "templates"}
VALIDATION_EXCLUDED_DIRS = {*GRAPH_EXCLUDED_DIRS, "docs", "thinking"}
OPERATING_FILENAMES = {"AGENTS.md", "AGENTS.local.md", "CLAUDE.md", "CLAUDE.local.md"}
ROOT_EXCLUDED_FILENAMES = {"CHANGELOG.md", "CONTRIBUTING.md", "LICENSE", "README.md", "SETUP.md"}
TRANSIENT_PREFIXES = ("work/Tasks.md", "personal/tasks/", "personal/archive/tasks/", "work/tasks/", "work/archive/tasks/", "work/archive/2026/tasks/")


def rel_posix(path, vault_root):
    try:
        return path.relative_to(vault_root).as_posix()
    except ValueError:
        return None


def _rel_parts(path, vault_root):
    try:
        return path.relative_to(vault_root).parts
    except ValueError:
        return None


def is_operating_file(path):
    return path.name in OPERATING_FILENAMES


def is_root_excluded_file(path, vault_root):
    parts = _rel_parts(path, vault_root)
    return bool(parts and len(parts) == 1 and path.name in ROOT_EXCLUDED_FILENAMES)


def is_transient_note(path, vault_root):
    rel = rel_posix(path, vault_root)
    return bool(rel and rel.startswith(TRANSIENT_PREFIXES))


def is_under_excluded_dir(path, vault_root, excluded_dirs):
    parts = _rel_parts(path, vault_root)
    if not parts:
        return True
    return any(part in excluded_dirs or part.startswith(".") for part in parts[:-1])


def is_graph_excluded(path, vault_root):
    return (
        is_operating_file(path)
        or is_root_excluded_file(path, vault_root)
        or is_transient_note(path, vault_root)
        or is_under_excluded_dir(path, vault_root, GRAPH_EXCLUDED_DIRS)
    )


def is_governed_excluded(path, vault_root):
    return (
        is_operating_file(path)
        or is_root_excluded_file(path, vault_root)
        or is_under_excluded_dir(path, vault_root, VALIDATION_EXCLUDED_DIRS)
    )


def is_markdown_in_dirs(path, vault_root, dirs):
    if path.suffix.lower() != ".md":
        return False
    parts = _rel_parts(path, vault_root)
    return bool(parts and parts[0] in dirs)


def is_graph_markdown_note(path, vault_root):
    return is_markdown_in_dirs(path, vault_root, GRAPH_NOTE_DIRS) and not is_graph_excluded(path, vault_root)


def is_governed_markdown_note(path, vault_root):
    return is_markdown_in_dirs(path, vault_root, GOVERNED_NOTE_DIRS) and not is_governed_excluded(path, vault_root)


def iter_graph_markdown_notes(vault_root):
    notes = []
    for folder_name in GRAPH_NOTE_DIRS:
        folder = vault_root / folder_name
        if not folder.is_dir():
            continue
        notes.extend(p for p in folder.rglob("*.md") if is_graph_markdown_note(p, vault_root))
    return sorted(notes)


def iter_governed_markdown_notes(vault_root):
    notes = []
    for folder_name in GOVERNED_NOTE_DIRS:
        folder = vault_root / folder_name
        if not folder.is_dir():
            continue
        notes.extend(p for p in folder.rglob("*.md") if is_governed_markdown_note(p, vault_root))
    return sorted(notes)
'''


def _write_owner_scope_with_school(vault_root: Path) -> None:
    _write(vault_root, ".vault/vault.json", "{}\n")
    _write(vault_root, ".vault/config/vault_scope.py", OWNER_VAULT_SCOPE_WITH_SCHOOL)


# ===========================================================================
# baseline behavior (pre-adversarial-review coverage)
# ===========================================================================

def test_clean_in_scope_note_is_clean(tmp_path: Path) -> None:
    _git_init(tmp_path)
    _write(tmp_path, "brain/A.md", _note("A", body="See [[B]]."))
    _write(tmp_path, "brain/B.md", _note("B"))
    _git_commit_all(tmp_path, "init")

    report = collect(tmp_path, files=["brain/A.md"], base="HEAD")

    assert report["verdict"] == "CLEAN"
    assert report["checks"]["frontmatter"]["count"] == 0
    assert report["checks"]["no_wikilinks"]["count"] == 0
    assert report["checks"]["unresolved_links"]["count"] == 0
    assert report["checks"]["orphans"]["count"] == 0
    assert report["checks"]["index_membership"]["count"] == 0
    assert report["not_run"] == []

    exit_code = main([
        "--vault-root", str(tmp_path),
        "--files", "brain/A.md",
        "--base", "HEAD",
        "--json",
    ])
    assert exit_code == 0


def test_bad_frontmatter_reported_in_scope(tmp_path: Path) -> None:
    _git_init(tmp_path)
    _write(tmp_path, "brain/A.md", _note("A", body="See [[B]]."))
    _write(tmp_path, "brain/B.md", _note("B"))
    bad = (
        "---\n"
        "date: 2026-07-08\n"
        "tags:\n"
        "  - reference\n"
        "---\n\n"
        "# Bad\n\nMissing description field.\n"
    )
    _write(tmp_path, "brain/Bad.md", bad)
    _git_commit_all(tmp_path, "init")

    report = collect(tmp_path, files=["brain/Bad.md"], base="HEAD")

    assert report["verdict"] == "FINDINGS"
    files = {f["file"] for f in report["checks"]["frontmatter"]["findings"]}
    assert "brain/Bad.md" in files


def test_no_wikilinks_reported_in_scope(tmp_path: Path) -> None:
    _git_init(tmp_path)
    long_body = "word " * 100  # > 300 chars, no wikilinks
    _write(tmp_path, "brain/Long.md", _note("Long", body=long_body))
    _git_commit_all(tmp_path, "init")

    report = collect(tmp_path, files=["brain/Long.md"], base="HEAD")

    assert report["verdict"] == "FINDINGS"
    files = {f["file"] for f in report["checks"]["no_wikilinks"]["findings"]}
    assert "brain/Long.md" in files


def test_missing_from_personal_index_reported(tmp_path: Path) -> None:
    _git_init(tmp_path)
    _write(tmp_path, "personal/Index.md", _note("Personal Index", tags="index"))
    _write(
        tmp_path,
        "personal/projects/Proj.md",
        _note("Proj", body="Some project note, not linked from the index."),
    )
    _git_commit_all(tmp_path, "init")

    report = collect(tmp_path, files=["personal/projects/Proj.md"], base="HEAD")

    assert report["verdict"] == "FINDINGS"
    findings = report["checks"]["index_membership"]["findings"]
    assert any(
        f["file"] == "personal/projects/Proj.md" and "personal/Index.md" in f["detail"]
        for f in findings
    )


def test_broken_link_in_untouched_note_out_of_scope(tmp_path: Path) -> None:
    _git_init(tmp_path)
    _write(tmp_path, "brain/Old Name.md", _note("Old Name"))
    _write(tmp_path, "brain/Untouched.md", _note("Untouched", body="See [[Old Name]]."))
    _git_commit_all(tmp_path, "init")
    base_sha = _git_rev_parse(tmp_path, "HEAD")

    (tmp_path / "brain" / "Old Name.md").rename(tmp_path / "brain" / "New Name.md")
    _git_commit_all(tmp_path, "rename")

    report = collect(tmp_path, files=["brain/New Name.md"], base=base_sha)

    assert report["verdict"] == "FINDINGS"
    unresolved = report["checks"]["unresolved_links"]["findings"]
    match = [f for f in unresolved if f["file"] == "brain/Untouched.md"]
    assert match, unresolved
    assert match[0]["in_scope"] is False


def test_broken_note_not_in_files_scope_honored_but_unclaimed_dirty(tmp_path: Path) -> None:
    _git_init(tmp_path)
    _write(tmp_path, "brain/A.md", _note("A", body="See [[B]]."))
    _write(tmp_path, "brain/B.md", _note("B"))
    _git_commit_all(tmp_path, "init")

    bad = (
        "---\n"
        "date: 2026-07-08\n"
        "tags:\n"
        "  - reference\n"
        "---\n\n"
        "# Bad\n\nMissing description, left dirty/untracked.\n"
    )
    _write(tmp_path, "brain/Bad.md", bad)  # untracked, not claimed

    report = collect(tmp_path, files=["brain/A.md"], base="HEAD")

    frontmatter_files = {f["file"] for f in report["checks"]["frontmatter"]["findings"]}
    no_wikilinks_files = {f["file"] for f in report["checks"]["no_wikilinks"]["findings"]}
    index_files = {f["file"] for f in report["checks"]["index_membership"]["findings"]}
    assert "brain/Bad.md" not in frontmatter_files
    assert "brain/Bad.md" not in no_wikilinks_files
    assert "brain/Bad.md" not in index_files
    assert "brain/Bad.md" in report["scope"]["unclaimed_dirty"]


def test_orphans_in_scope_vs_out_of_scope(tmp_path: Path) -> None:
    _git_init(tmp_path)
    _write(tmp_path, "brain/OrphanInScope.md", _note("Orphan In Scope"))
    _write(tmp_path, "brain/OrphanOutOfScope.md", _note("Orphan Out Of Scope"))
    _git_commit_all(tmp_path, "init")

    report = collect(tmp_path, files=["brain/OrphanInScope.md"], base="HEAD")

    assert report["verdict"] == "FINDINGS"
    orphan_files = {f["file"] for f in report["checks"]["orphans"]["findings"]}
    assert "brain/OrphanInScope.md" in orphan_files
    assert "brain/OrphanOutOfScope.md" not in orphan_files
    assert report["checks"]["orphans"]["vault_wide_count"] == 2


def test_handoff_touched_sections_exact(tmp_path: Path) -> None:
    _git_init(tmp_path)
    _write(tmp_path, ".vault-context", "personal")
    _write(tmp_path, "brain/Anchor.md", _note("Anchor"))
    _write(tmp_path, ".brain/handoff-personal.md", _handoff_text())
    _git_commit_all(tmp_path, "init")
    base_sha = _git_rev_parse(tmp_path, "HEAD")

    new_text = _handoff_text().replace("Old resume text.", "New resume text.").replace(
        "Old notes text.", "New notes text."
    )
    _write(tmp_path, ".brain/handoff-personal.md", new_text)
    _git_commit_all(tmp_path, "update handoff")

    report = collect(tmp_path, files=["brain/Anchor.md"], base=base_sha)

    handoff = report["checks"]["handoff_sections"]
    assert handoff["present"] == ["Resume From Here", "Open Threads", "Notes"]
    assert handoff["touched"] == ["Resume From Here", "Notes"]


def test_graphmark_unavailable_is_incomplete_never_clean(tmp_path: Path, monkeypatch) -> None:
    _git_init(tmp_path)
    _write(tmp_path, "brain/A.md", _note("A", body="See [[B]]."))
    _write(tmp_path, "brain/B.md", _note("B"))
    _git_commit_all(tmp_path, "init")

    monkeypatch.delitem(sys.modules, "graph_cli", raising=False)
    monkeypatch.delitem(sys.modules, "graphmark", raising=False)

    real_import = builtins.__import__

    def fake_import(name, *args, **kwargs):
        if name == "graphmark" or name.startswith("graphmark."):
            raise ImportError("graphmark blocked for test")
        return real_import(name, *args, **kwargs)

    monkeypatch.setattr(builtins, "__import__", fake_import)

    report = collect(tmp_path, files=["brain/A.md"], base="HEAD")

    assert report["verdict"] == "INCOMPLETE"
    assert report["verdict"] != "CLEAN"
    not_run_checks = {nr["check"] for nr in report["not_run"]}
    assert "unresolved_links" in not_run_checks
    assert "orphans" in not_run_checks
    assert VERDICT_EXIT_CODES[report["verdict"]] == 2


def test_files_omitted_falls_back_to_git_scope(tmp_path: Path) -> None:
    _git_init(tmp_path)
    _write(tmp_path, "brain/A.md", _note("A", body="See [[B]]."))
    _write(tmp_path, "brain/B.md", _note("B"))
    _git_commit_all(tmp_path, "init")

    _write(tmp_path, "brain/A.md", _note("A", body="See [[B]]. Edited this session."))

    report = collect(tmp_path, files=None, base="HEAD")

    assert report["scope"]["source"] == "git"
    assert any("git" in w.lower() for w in report["scope"]["warnings"])
    assert "brain/A.md" in report["scope"]["files"]


# ===========================================================================
# HIGH item 1 — gate parity
# ===========================================================================

def _write_gate_fixture(tmp_path: Path, remove_b_link: bool) -> None:
    a_body = "See [[Hub]]." if remove_b_link else "See [[B]] and [[Hub]]."
    _write(tmp_path, "brain/A.md", _note("A", body=a_body))
    _write(
        tmp_path,
        "brain/B.md",
        _note("B", body="No links here, just body text long enough to clear the three "
                         "hundred character wikilink threshold on its own so this fixture "
                         "does not also trip the no_wikilinks check by accident here."),
    )
    _write(tmp_path, "brain/Hub.md", _note("Hub", body="See [[A]]."))
    for name in ("O1", "O2", "O3"):
        _write(tmp_path, f"brain/{name}.md", _note(name))
    _write(tmp_path, "ci/vault_health.py", GATE_POLICY_3_0)


def test_gate_check_findings_on_orphans_breach(tmp_path: Path) -> None:
    _git_init(tmp_path)
    _write_gate_fixture(tmp_path, remove_b_link=True)
    _git_commit_all(tmp_path, "init")

    report = collect(tmp_path, files=["brain/A.md"], base="HEAD")

    gate = report["checks"]["gate"]
    assert gate["not_run"] is None
    assert gate["pass"] is False
    assert report["verdict"] == "FINDINGS"


def test_gate_check_clean_when_gate_passes(tmp_path: Path) -> None:
    _git_init(tmp_path)
    _write_gate_fixture(tmp_path, remove_b_link=False)
    _git_commit_all(tmp_path, "init")

    report = collect(tmp_path, files=["brain/A.md"], base="HEAD")

    gate = report["checks"]["gate"]
    assert gate["not_run"] is None
    assert gate["pass"] is True
    assert report["verdict"] == "CLEAN"


def test_gate_missing_file_gives_incomplete(tmp_path: Path) -> None:
    _git_init(tmp_path)
    _write_gate_fixture(tmp_path, remove_b_link=False)
    (tmp_path / "ci" / "vault_health.py").unlink()
    _write(tmp_path, "ci/.keep", "")
    _git_commit_all(tmp_path, "init")

    report = collect(tmp_path, files=["brain/A.md"], base="HEAD")

    assert report["verdict"] == "INCOMPLETE"
    assert report["checks"]["gate"]["not_run"] is not None
    assert any(nr["check"] == "gate" for nr in report["not_run"])


def test_gate_non_literal_policy_gives_incomplete(tmp_path: Path) -> None:
    _git_init(tmp_path)
    _write_gate_fixture(tmp_path, remove_b_link=False)
    _write(tmp_path, "ci/vault_health.py", GATE_POLICY_NON_LITERAL)
    _git_commit_all(tmp_path, "init")

    report = collect(tmp_path, files=["brain/A.md"], base="HEAD")

    assert report["verdict"] == "INCOMPLETE"
    assert report["checks"]["gate"]["not_run"] is not None


# ===========================================================================
# HIGH item 2 — scope validation
# ===========================================================================

def test_scope_split_unquoted_space_gives_incomplete(tmp_path: Path) -> None:
    _git_init(tmp_path)
    _write(tmp_path, "brain/Lonely Two.md", _note("Lonely Two"))
    _git_commit_all(tmp_path, "init")

    report = collect(tmp_path, files=["brain/Lonely", "Two.md"], base="HEAD")

    assert report["verdict"] == "INCOMPLETE"
    offending = {e["file"] for e in report["scope"]["errors"]}
    assert "brain/Lonely" in offending
    assert "Two.md" in offending


def test_scope_typo_gives_incomplete(tmp_path: Path) -> None:
    _git_init(tmp_path)
    _write(tmp_path, "brain/Lonely Two.md", _note("Lonely Two"))
    _git_commit_all(tmp_path, "init")

    report = collect(tmp_path, files=["brain/Lonly Two.md"], base="HEAD")

    assert report["verdict"] == "INCOMPLETE"
    assert any(e["file"] == "brain/Lonly Two.md" for e in report["scope"]["errors"])


def test_scope_etc_hosts_gives_incomplete(tmp_path: Path) -> None:
    _git_init(tmp_path)
    _write(tmp_path, "brain/A.md", _note("A"))
    _git_commit_all(tmp_path, "init")

    report = collect(tmp_path, files=["/etc/hosts"], base="HEAD")

    assert report["verdict"] == "INCOMPLETE"
    assert any(e["file"] == "/etc/hosts" for e in report["scope"]["errors"])


def test_scope_empty_files_gives_incomplete(tmp_path: Path) -> None:
    _git_init(tmp_path)
    _write(tmp_path, "brain/A.md", _note("A"))
    _git_commit_all(tmp_path, "init")

    report = collect(tmp_path, files=[], base="HEAD")

    assert report["verdict"] == "INCOMPLETE"
    assert report["scope"]["errors"]


def test_scope_cwd_relative_gives_findings(tmp_path: Path, monkeypatch) -> None:
    _git_init(tmp_path)
    _write(tmp_path, "brain/Lonely Two.md", _note("Lonely Two"))
    _git_commit_all(tmp_path, "init")

    monkeypatch.chdir(tmp_path / "brain")

    report = collect(tmp_path, files=["Lonely Two.md"], base="HEAD")

    assert report["verdict"] == "FINDINGS"
    assert "brain/Lonely Two.md" in report["scope"]["files"]
    orphan_files = {f["file"] for f in report["checks"]["orphans"]["findings"]}
    assert "brain/Lonely Two.md" in orphan_files


def test_scope_dotdot_normalizes_gives_findings(tmp_path: Path) -> None:
    _git_init(tmp_path)
    _write(tmp_path, "brain/Lonely Two.md", _note("Lonely Two"))
    _git_commit_all(tmp_path, "init")

    report = collect(tmp_path, files=["brain/../brain/Lonely Two.md"], base="HEAD")

    assert report["verdict"] == "FINDINGS"
    assert "brain/Lonely Two.md" in report["scope"]["files"]


def test_scope_case_variant_gives_findings(tmp_path: Path) -> None:
    _git_init(tmp_path)
    _write(tmp_path, "brain/Lonely Two.md", _note("Lonely Two"))
    _git_commit_all(tmp_path, "init")

    report = collect(tmp_path, files=["brain/lonely two.md"], base="HEAD")

    assert report["verdict"] == "FINDINGS"
    assert "brain/Lonely Two.md" in report["scope"]["files"]


def test_scope_absolute_path_gives_findings(tmp_path: Path) -> None:
    _git_init(tmp_path)
    _write(tmp_path, "brain/Lonely Two.md", _note("Lonely Two"))
    _git_commit_all(tmp_path, "init")

    abs_path = str(tmp_path / "brain" / "Lonely Two.md")
    report = collect(tmp_path, files=[abs_path], base="HEAD")

    assert report["verdict"] == "FINDINGS"
    assert "brain/Lonely Two.md" in report["scope"]["files"]


def test_scope_git_deletion_goes_to_skipped(tmp_path: Path) -> None:
    _git_init(tmp_path)
    _write(tmp_path, "brain/A.md", _note("A", body="See [[B]]."))
    _write(tmp_path, "brain/B.md", _note("B"))
    _write(tmp_path, "brain/Gone.md", _note("Gone"))
    _git_commit_all(tmp_path, "init")
    base_sha = _git_rev_parse(tmp_path, "HEAD")

    (tmp_path / "brain" / "Gone.md").unlink()
    _git_commit_all(tmp_path, "delete Gone")

    report = collect(tmp_path, files=["brain/A.md", "brain/Gone.md"], base=base_sha)

    assert report["scope"]["errors"] == []
    assert any(s["file"] == "brain/Gone.md" for s in report["scope"]["skipped"])
    assert "brain/Gone.md" not in report["scope"]["files"]


# ===========================================================================
# HIGH item 3 — handoff semantics (deletion mapping, fenced headings)
# ===========================================================================

def _write_handoff(tmp_path: Path, text: str) -> None:
    _write(tmp_path, ".vault-context", "personal")
    _write(tmp_path, ".brain/handoff-personal.md", text)


def test_handoff_delete_whole_last_section(tmp_path: Path) -> None:
    _git_init(tmp_path)
    _write_handoff(tmp_path, _handoff_text())
    _git_commit_all(tmp_path, "init")
    base_sha = _git_rev_parse(tmp_path, "HEAD")

    new_text = (
        "Preamble line.\n\n"
        "## Resume From Here\n"
        "Old resume text.\n\n"
        "## Open Threads\n"
        "Old open threads text.\n"
    )
    _write(tmp_path, ".brain/handoff-personal.md", new_text)
    _git_commit_all(tmp_path, "delete last section")

    report = collect(tmp_path, files=None, base=base_sha)

    handoff = report["checks"]["handoff_sections"]
    assert handoff["touched"] == ["Notes"]


def test_handoff_delete_heading_line_only(tmp_path: Path) -> None:
    _git_init(tmp_path)
    _write_handoff(tmp_path, _handoff_text())
    _git_commit_all(tmp_path, "init")
    base_sha = _git_rev_parse(tmp_path, "HEAD")

    new_text = (
        "Preamble line.\n\n"
        "Old resume text.\n\n"
        "## Open Threads\n"
        "Old open threads text.\n\n"
        "## Notes\n"
        "Old notes text.\n"
    )
    _write(tmp_path, ".brain/handoff-personal.md", new_text)
    _git_commit_all(tmp_path, "delete heading line only")

    report = collect(tmp_path, files=None, base=base_sha)

    handoff = report["checks"]["handoff_sections"]
    assert handoff["touched"] == ["Resume From Here"]


def test_handoff_delete_whole_middle_section(tmp_path: Path) -> None:
    _git_init(tmp_path)
    _write_handoff(tmp_path, _handoff_text())
    _git_commit_all(tmp_path, "init")
    base_sha = _git_rev_parse(tmp_path, "HEAD")

    new_text = (
        "Preamble line.\n\n"
        "## Resume From Here\n"
        "Old resume text.\n\n"
        "## Notes\n"
        "Old notes text.\n"
    )
    _write(tmp_path, ".brain/handoff-personal.md", new_text)
    _git_commit_all(tmp_path, "delete middle section")

    report = collect(tmp_path, files=None, base=base_sha)

    handoff = report["checks"]["handoff_sections"]
    assert handoff["touched"] == ["Open Threads"]


def test_handoff_pure_deletion_inside_section(tmp_path: Path) -> None:
    text = (
        "Preamble line.\n\n"
        "## Resume From Here\n"
        "Line one.\n"
        "Line two.\n"
        "Line three.\n\n"
        "## Open Threads\n"
        "Old open threads text.\n"
    )
    _git_init(tmp_path)
    _write_handoff(tmp_path, text)
    _git_commit_all(tmp_path, "init")
    base_sha = _git_rev_parse(tmp_path, "HEAD")

    new_text = (
        "Preamble line.\n\n"
        "## Resume From Here\n"
        "Line one.\n"
        "Line three.\n\n"
        "## Open Threads\n"
        "Old open threads text.\n"
    )
    _write(tmp_path, ".brain/handoff-personal.md", new_text)
    _git_commit_all(tmp_path, "pure deletion inside section")

    report = collect(tmp_path, files=None, base=base_sha)

    handoff = report["checks"]["handoff_sections"]
    assert handoff["touched"] == ["Resume From Here"]


def test_handoff_multiline_hunk_spans_two_sections(tmp_path: Path) -> None:
    text = (
        "Preamble line.\n\n"
        "## Resume From Here\n"
        "Old resume line A.\n"
        "Old resume line B.\n\n"
        "## Open Threads\n"
        "Old open threads text.\n"
    )
    _git_init(tmp_path)
    _write_handoff(tmp_path, text)
    _git_commit_all(tmp_path, "init")
    base_sha = _git_rev_parse(tmp_path, "HEAD")

    new_text = (
        "Preamble line.\n\n"
        "## Resume From Here\n"
        "New resume line A.\n\n"
        "## Open Threads\n"
        "New open threads text.\n"
    )
    _write(tmp_path, ".brain/handoff-personal.md", new_text)
    _git_commit_all(tmp_path, "span two sections")

    report = collect(tmp_path, files=None, base=base_sha)

    handoff = report["checks"]["handoff_sections"]
    assert "Resume From Here" in handoff["touched"]
    assert "Open Threads" in handoff["touched"]


def test_handoff_fenced_heading_ignored(tmp_path: Path) -> None:
    text = (
        "Preamble line.\n\n"
        "## Resume From Here\n"
        "```md\n"
        "## Not A Heading\n"
        "```\n"
        "Real resume text.\n\n"
        "## Open Threads\n"
        "Old open threads text.\n"
    )
    _git_init(tmp_path)
    _write_handoff(tmp_path, text)
    _git_commit_all(tmp_path, "init")

    report = collect(tmp_path, files=None, base="HEAD")

    handoff = report["checks"]["handoff_sections"]
    assert handoff["present"] == ["Resume From Here", "Open Threads"]


# ===========================================================================
# MEDIUM item 4 — scope config follows --vault-root, not cwd
# ===========================================================================

def test_vault_root_pins_scope_config_not_cwd(tmp_path: Path, monkeypatch, tmp_path_factory) -> None:
    _git_init(tmp_path)
    _write_owner_scope_with_school(tmp_path)
    _write(tmp_path, "school/Lecture.md", _note("Lecture", body="See [[Nope Missing]]."))
    _git_commit_all(tmp_path, "init")

    outside = tmp_path_factory.mktemp("outside-cwd")
    monkeypatch.chdir(outside)

    report = collect(tmp_path, files=["school/Lecture.md"], base="HEAD")

    assert report["verdict"] == "FINDINGS"
    unresolved = report["checks"]["unresolved_links"]["findings"]
    assert any(f["file"] == "school/Lecture.md" for f in unresolved)
    assert "vault_scope.py" in report["scope_config_source"]


# ===========================================================================
# MEDIUM item 5 — git-mode scope
# ===========================================================================

def test_git_mode_new_directory_bad_note_gives_findings(tmp_path: Path) -> None:
    _git_init(tmp_path)
    _write(tmp_path, "brain/Anchor.md", _note("Anchor"))
    _git_commit_all(tmp_path, "init")

    bad = (
        "---\n"
        "date: 2026-07-08\n"
        "tags:\n"
        "  - reference\n"
        "---\n\n"
        "# Bad\n\nMissing description, new directory, untracked.\n"
    )
    _write(tmp_path, "work/active/NewProj/Plan.md", bad)

    report = collect(tmp_path, files=None, base="HEAD")

    assert "work/active/NewProj/Plan.md" in report["scope"]["files"]
    assert report["verdict"] == "FINDINGS"
    frontmatter_files = {f["file"] for f in report["checks"]["frontmatter"]["findings"]}
    assert "work/active/NewProj/Plan.md" in frontmatter_files


def test_git_mode_non_ascii_note_gives_findings(tmp_path: Path) -> None:
    _git_init(tmp_path)
    bad = (
        "---\n"
        "date: 2026-07-08\n"
        "tags:\n"
        "  - reference\n"
        "---\n\n"
        "# Cafe\n\nMissing description.\n"
    )
    _write(tmp_path, "brain/Café Note.md", bad)
    _git_commit_all(tmp_path, "init")

    _write(tmp_path, "brain/Café Note.md", bad + "\nedited\n")

    report = collect(tmp_path, files=None, base="HEAD")

    assert "brain/Café Note.md" in report["scope"]["files"]
    assert report["verdict"] == "FINDINGS"


def test_git_mode_handoff_file_goes_to_skipped(tmp_path: Path) -> None:
    _git_init(tmp_path)
    _write_handoff(tmp_path, _handoff_text())
    _write(tmp_path, "brain/Anchor.md", _note("Anchor"))
    _git_commit_all(tmp_path, "init")

    new_text = _handoff_text().replace("Old resume text.", "New resume text.")
    _write(tmp_path, ".brain/handoff-personal.md", new_text)

    report = collect(tmp_path, files=None, base="HEAD")

    assert ".brain/handoff-personal.md" not in report["scope"]["files"]
    assert any(s["file"] == ".brain/handoff-personal.md" for s in report["scope"]["skipped"])


# ===========================================================================
# MEDIUM item 6 — missing handoff is silent -> not_run/INCOMPLETE
# ===========================================================================

def test_missing_vault_context_gives_incomplete(tmp_path: Path) -> None:
    _git_init(tmp_path)
    (tmp_path / ".vault-context").unlink()
    (tmp_path / ".brain" / "handoff-personal.md").unlink()
    _write(tmp_path, "brain/A.md", _note("A", body="See [[B]]."))
    _write(tmp_path, "brain/B.md", _note("B"))
    _git_commit_all(tmp_path, "init")

    report = collect(tmp_path, files=["brain/A.md"], base="HEAD")

    assert report["verdict"] == "INCOMPLETE"
    assert report["checks"]["handoff_sections"]["not_run"] is not None
    assert any(nr["check"] == "handoff_sections" for nr in report["not_run"])


def test_missing_handoff_file_for_known_context_gives_incomplete(tmp_path: Path) -> None:
    _git_init(tmp_path)
    (tmp_path / ".brain" / "handoff-personal.md").unlink()  # .vault-context stays "personal"
    _write(tmp_path, "brain/A.md", _note("A", body="See [[B]]."))
    _write(tmp_path, "brain/B.md", _note("B"))
    _git_commit_all(tmp_path, "init")

    report = collect(tmp_path, files=["brain/A.md"], base="HEAD")

    assert report["verdict"] == "INCOMPLETE"
    assert report["checks"]["handoff_sections"]["not_run"] is not None


# ===========================================================================
# LOW item 7 — crash exit code
# ===========================================================================

def test_crash_exits_2_not_1(tmp_path: Path, monkeypatch) -> None:
    import wrap_up_audit

    def boom(*args, **kwargs):
        raise RuntimeError("forced internal failure")

    monkeypatch.setattr(wrap_up_audit, "collect", boom)

    exit_code = main(["--vault-root", str(tmp_path), "--files", "brain/A.md", "--json"])
    assert exit_code == 2


# ===========================================================================
# item 9 — survivors
# ===========================================================================

def test_embed_only_note_over_300_is_no_wikilinks(tmp_path: Path) -> None:
    # T3b: an embed (![[...]]) does not count as a wikilink for the rule.
    _git_init(tmp_path)
    long_body = "![[SomeImage.png]]\n\n" + ("word " * 100)
    _write(tmp_path, "brain/EmbedOnly.md", _note("EmbedOnly", body=long_body))
    _git_commit_all(tmp_path, "init")

    report = collect(tmp_path, files=["brain/EmbedOnly.md"], base="HEAD")

    files = {f["file"] for f in report["checks"]["no_wikilinks"]["findings"]}
    assert "brain/EmbedOnly.md" in files


def test_work_note_missing_from_work_index(tmp_path: Path) -> None:
    # T4b
    _git_init(tmp_path)
    _write(tmp_path, "work/Index.md", _note("Work Index", tags="index"))
    _write(
        tmp_path,
        "work/active/Project.md",
        (
            "---\n"
            "date: 2026-07-08\n"
            "description: \"A project\"\n"
            "tags:\n"
            "  - work-note\n"
            "status: active\n"
            "project: \"Project\"\n"
            "---\n\n"
            "# Project\n\nNot linked from the index.\n"
        ),
    )
    _git_commit_all(tmp_path, "init")

    report = collect(tmp_path, files=["work/active/Project.md"], base="HEAD")

    findings = report["checks"]["index_membership"]["findings"]
    assert any(
        f["file"] == "work/active/Project.md" and "work/Index.md" in f["detail"]
        for f in findings
    )


def test_in_scope_broken_link_has_in_scope_true(tmp_path: Path) -> None:
    # T5b
    _git_init(tmp_path)
    _write(tmp_path, "brain/Claimed.md", _note("Claimed", body="See [[Missing Target]]."))
    _git_commit_all(tmp_path, "init")

    report = collect(tmp_path, files=["brain/Claimed.md"], base="HEAD")

    unresolved = report["checks"]["unresolved_links"]["findings"]
    match = [f for f in unresolved if f["file"] == "brain/Claimed.md"]
    assert match
    assert match[0]["in_scope"] is True


def test_unresolved_links_alone_drives_findings_not_orphan(tmp_path: Path) -> None:
    # T5c: the broken-link note is linked FROM elsewhere, so it is not itself
    # an orphan — only unresolved_links should drive the verdict.
    _git_init(tmp_path)
    _write(tmp_path, "brain/Claimed.md", _note("Claimed", body="See [[Missing Target]]."))
    _write(tmp_path, "brain/Linker.md", _note("Linker", body="See [[Claimed]]."))
    _git_commit_all(tmp_path, "init")

    report = collect(tmp_path, files=["brain/Claimed.md"], base="HEAD")

    assert report["checks"]["orphans"]["findings"] == []
    unresolved_files = {f["file"] for f in report["checks"]["unresolved_links"]["findings"]}
    assert "brain/Claimed.md" in unresolved_files
    assert report["verdict"] == "FINDINGS"


def test_findings_exits_1(tmp_path: Path) -> None:
    # X6
    _git_init(tmp_path)
    bad = (
        "---\n"
        "date: 2026-07-08\n"
        "tags:\n"
        "  - reference\n"
        "---\n\n"
        "# Bad\n\nMissing description field.\n"
    )
    _write(tmp_path, "brain/Bad.md", bad)
    _git_commit_all(tmp_path, "init")

    exit_code = main(["--vault-root", str(tmp_path), "--files", "brain/Bad.md", "--base", "HEAD", "--json"])
    assert exit_code == 1


def test_limit_one_with_three_findings_elides_two(tmp_path: Path) -> None:
    # X7
    _git_init(tmp_path)
    bad_template = (
        "---\n"
        "date: 2026-07-08\n"
        "tags:\n"
        "  - reference\n"
        "---\n\n"
        "# {name}\n\nMissing description field.\n"
    )
    files = []
    for name in ("Bad1", "Bad2", "Bad3"):
        rel = f"brain/{name}.md"
        _write(tmp_path, rel, bad_template.format(name=name))
        files.append(rel)
    _git_commit_all(tmp_path, "init")

    report = collect(tmp_path, files=files, base="HEAD", limit=1)

    assert report["checks"]["frontmatter"]["count"] == 3
    assert len(report["checks"]["frontmatter"]["findings"]) == 1
    assert report["checks"]["frontmatter"]["elided"] == 2


def test_failing_handoff_git_diff_gives_incomplete(tmp_path: Path) -> None:
    # X8
    _git_init(tmp_path)
    _write_handoff(tmp_path, _handoff_text())
    _write(tmp_path, "brain/A.md", _note("A", body="See [[B]]."))
    _write(tmp_path, "brain/B.md", _note("B"))
    _git_commit_all(tmp_path, "init")

    report = collect(tmp_path, files=["brain/A.md"], base="not-a-real-ref-xyz")

    assert report["verdict"] == "INCOMPLETE"
    assert report["checks"]["handoff_sections"]["not_run"] is not None


def test_undetermined_git_scope_not_a_repo_gives_incomplete(tmp_path: Path) -> None:
    # X9 (no git init at all) — WITH a gate file and handoff (written directly,
    # no git needed) so git failure is the ONLY not_run reason, not an
    # incidental missing fixture.
    _write(tmp_path, "ci/vault_health.py", PERMISSIVE_GATE_POLICY)
    _write(tmp_path, ".vault-context", "personal")
    _write(tmp_path, ".brain/handoff-personal.md", "## Resume From Here\nNothing yet.\n")
    _write(tmp_path, "brain/A.md", _note("A"))

    report = collect(tmp_path, files=None, base="HEAD")

    assert report["verdict"] == "INCOMPLETE"
    not_run_checks = {nr["check"] for nr in report["not_run"]}
    assert not_run_checks == {"scope"}


def test_transient_note_in_files_skipped_for_index_checks(tmp_path: Path) -> None:
    # X12: work/archive/tasks/ is transient AND matches the work/archive/
    # index prefix — the transient rule must win.
    _git_init(tmp_path)
    task_note = (
        "---\n"
        "date: 2026-07-08\n"
        "description: \"Weekly tasks\"\n"
        "tags:\n"
        "  - tasks\n"
        "week: 2026-W27\n"
        "---\n\n"
        "- [ ] Task\n"
    )
    _write(tmp_path, "work/archive/tasks/2026-W27-tasks.md", task_note)
    _git_commit_all(tmp_path, "init")

    report = collect(tmp_path, files=["work/archive/tasks/2026-W27-tasks.md"], base="HEAD")

    findings = report["checks"]["index_membership"]["findings"]
    assert not any(f["file"] == "work/archive/tasks/2026-W27-tasks.md" for f in findings)


def test_operating_file_in_files_is_skipped(tmp_path: Path) -> None:
    # X13
    _git_init(tmp_path)
    _write(tmp_path, "work/AGENTS.md", "# policy, intentionally not a note\n")
    _git_commit_all(tmp_path, "init")

    report = collect(tmp_path, files=["work/AGENTS.md"], base="HEAD")

    assert "work/AGENTS.md" not in report["scope"]["files"]
    assert any(s["file"] == "work/AGENTS.md" and "operating" in s["reason"] for s in report["scope"]["skipped"])


def test_absolute_files_path_is_honored(tmp_path: Path) -> None:
    # X14
    _git_init(tmp_path)
    _write(tmp_path, "brain/A.md", _note("A", body="See [[B]]."))
    _write(tmp_path, "brain/B.md", _note("B"))
    _git_commit_all(tmp_path, "init")

    abs_path = str(tmp_path / "brain" / "A.md")
    report = collect(tmp_path, files=[abs_path], base="HEAD")

    assert "brain/A.md" in report["scope"]["files"]


# ===========================================================================
# round 3 — MEDIUM-A: order-dependent leak. collect() must restore process
# state (CLAUDE_PROJECT_DIR, sys.modules) it changed, on both success and
# exception, so it cannot poison an unrelated test/caller running later in
# the same process.
# ===========================================================================

def test_collect_restores_process_state_on_success(tmp_path: Path) -> None:
    prior_env = os.environ.get("CLAUDE_PROJECT_DIR")
    prior_objs = {
        name: sys.modules.get(name)
        for name in ("vault_scope_resolved", "vault_scope_defaults", "frontmatter_engine", "vault_audit")
    }

    _git_init(tmp_path)
    _write(tmp_path, "brain/A.md", _note("A", body="See [[B]]."))
    _write(tmp_path, "brain/B.md", _note("B"))
    _git_commit_all(tmp_path, "init")

    collect(tmp_path, files=["brain/A.md"], base="HEAD")

    assert os.environ.get("CLAUDE_PROJECT_DIR") == prior_env
    for name, obj in prior_objs.items():
        assert sys.modules.get(name) is obj, name


def test_collect_restores_process_state_on_exception(tmp_path: Path, monkeypatch) -> None:
    import wrap_up_audit  # noqa: PLC0415

    prior_env = os.environ.get("CLAUDE_PROJECT_DIR")
    prior_obj = sys.modules.get("vault_scope_resolved")

    def boom(*_a, **_k):
        raise RuntimeError("forced failure after pinning")

    monkeypatch.setattr(wrap_up_audit, "_compute_scope", boom)

    _git_init(tmp_path)
    _write(tmp_path, "brain/A.md", _note("A"))
    _git_commit_all(tmp_path, "init")

    with pytest.raises(RuntimeError):
        collect(tmp_path, files=["brain/A.md"], base="HEAD")

    assert os.environ.get("CLAUDE_PROJECT_DIR") == prior_env
    assert sys.modules.get("vault_scope_resolved") is prior_obj


def test_no_cross_test_leak_repro_in_one_process() -> None:
    """The exact repro from the adversarial review: running the wrap-up
    collector's test before a vault_utils test, in the SAME process, must
    not change the vault_utils test's result. Runs pytest in a subprocess
    (via sys.executable — the already-configured venv this suite itself
    runs under) to get a fresh-process baseline for the assertion.
    """
    machinery_dir = SCRIPTS_DIR.parent
    cmd = [
        sys.executable, "-m", "pytest", "-q",
        "tests/test_wrap_up_audit.py::test_clean_in_scope_note_is_clean",
        "tests/test_vault_utils.py::TestReadBatchModel::test_explicit_default_is_the_last_resort",
    ]
    result = subprocess.run(cmd, cwd=machinery_dir, capture_output=True, text=True, timeout=120)
    assert result.returncode == 0, result.stdout + result.stderr


# ===========================================================================
# round 3 — MEDIUM-B: POLICY parser must fail closed. Each variant below
# currently gives a FALSE CLEAN under the naive (pre-round-3) parser: it
# reads a policy that is not the one actually enforced at runtime.
# ===========================================================================

def test_gate_bool_keyword_gives_incomplete(tmp_path: Path) -> None:
    # kills mutation m8
    _git_init(tmp_path)
    _write_gate_fixture(tmp_path, remove_b_link=True)
    _write(tmp_path, "ci/vault_health.py", GATE_POLICY_BOOL_KEYWORD)
    _git_commit_all(tmp_path, "init")

    report = collect(tmp_path, files=["brain/A.md"], base="HEAD")

    assert report["verdict"] == "INCOMPLETE"
    assert report["checks"]["gate"]["not_run"] is not None


def test_gate_two_assignments_gives_incomplete(tmp_path: Path) -> None:
    # collector must not silently take "the first" (or "the last") — kills m9
    _git_init(tmp_path)
    _write_gate_fixture(tmp_path, remove_b_link=True)  # 4 orphans, over the real 3 limit
    _write(tmp_path, "ci/vault_health.py", GATE_TWO_ASSIGNMENTS)
    _git_commit_all(tmp_path, "init")

    report = collect(tmp_path, files=["brain/A.md"], base="HEAD")

    assert report["verdict"] == "INCOMPLETE"
    assert report["checks"]["gate"]["not_run"] is not None


def test_gate_if_block_policy_gives_incomplete(tmp_path: Path) -> None:
    _git_init(tmp_path)
    _write_gate_fixture(tmp_path, remove_b_link=True)
    _write(tmp_path, "ci/vault_health.py", GATE_IF_BLOCK_POLICY)
    _git_commit_all(tmp_path, "init")

    report = collect(tmp_path, files=["brain/A.md"], base="HEAD")

    assert report["verdict"] == "INCOMPLETE"
    assert report["checks"]["gate"]["not_run"] is not None


def test_gate_unused_policy_gives_incomplete(tmp_path: Path) -> None:
    _git_init(tmp_path)
    _write_gate_fixture(tmp_path, remove_b_link=True)
    _write(tmp_path, "ci/vault_health.py", GATE_UNUSED_POLICY)
    _git_commit_all(tmp_path, "init")

    report = collect(tmp_path, files=["brain/A.md"], base="HEAD")

    assert report["verdict"] == "INCOMPLETE"
    assert report["checks"]["gate"]["not_run"] is not None


def test_gate_replace_policy_gives_incomplete(tmp_path: Path) -> None:
    _git_init(tmp_path)
    _write_gate_fixture(tmp_path, remove_b_link=True)
    _write(tmp_path, "ci/vault_health.py", GATE_REPLACE_POLICY)
    _git_commit_all(tmp_path, "init")

    report = collect(tmp_path, files=["brain/A.md"], base="HEAD")

    assert report["verdict"] == "INCOMPLETE"
    assert report["checks"]["gate"]["not_run"] is not None


def test_gate_real_vault_shaped_file_still_parses(tmp_path: Path) -> None:
    _git_init(tmp_path)
    _write_gate_fixture(tmp_path, remove_b_link=True)  # 4 orphans, over limit 3
    _write(tmp_path, "ci/vault_health.py", _gate_file(max_unresolved_links=0, max_orphans=3))
    _git_commit_all(tmp_path, "init")

    report = collect(tmp_path, files=["brain/A.md"], base="HEAD")

    assert report["checks"]["gate"]["not_run"] is None
    assert report["checks"]["gate"]["pass"] is False


def test_gate_checks_breakdown_present_even_when_passing(tmp_path: Path) -> None:
    # LOW-4
    _git_init(tmp_path)
    _write_gate_fixture(tmp_path, remove_b_link=False)  # gate passes
    _git_commit_all(tmp_path, "init")

    report = collect(tmp_path, files=["brain/A.md"], base="HEAD")

    gate = report["checks"]["gate"]
    assert gate["pass"] is True
    names = {c["name"] for c in gate["checks"]}
    assert {"max_orphans", "max_unresolved_links"} <= names
    for c in gate["checks"]:
        assert "actual" in c and "limit" in c


def test_gate_orphans_breach_lists_vault_wide_orphan_paths(tmp_path: Path) -> None:
    # m4
    _git_init(tmp_path)
    _write_gate_fixture(tmp_path, remove_b_link=True)  # 4 orphans: B, O1, O2, O3
    _git_commit_all(tmp_path, "init")

    report = collect(tmp_path, files=["brain/A.md"], base="HEAD")

    gate = report["checks"]["gate"]
    assert gate["pass"] is False
    orphan_files = {o["file"] for o in gate["orphans"]}
    assert orphan_files == {"brain/B.md", "brain/O1.md", "brain/O2.md", "brain/O3.md"}
    in_scope_map = {o["file"]: o["in_scope"] for o in gate["orphans"]}
    assert in_scope_map["brain/B.md"] is False


def test_gate_checkpolicy_exception_reported_without_dropping_other_checks(tmp_path: Path) -> None:
    # LOW-3: CheckPolicy() with no thresholds set constructs fine but
    # run_check() raises ValueError on it — must be reported as "gate policy
    # rejected", never "graphmark unavailable", and must not drop the
    # already-computed unresolved_links/orphans results.
    _git_init(tmp_path)
    _write(tmp_path, "brain/A.md", _note("A", body="See [[Missing]]."))
    _write(
        tmp_path,
        "ci/vault_health.py",
        "from graphmark.config import CheckPolicy\n\n"
        "POLICY = CheckPolicy()\n\n"
        "def main():\n"
        "    return dict(check=POLICY)\n",
    )
    _git_commit_all(tmp_path, "init")

    report = collect(tmp_path, files=["brain/A.md"], base="HEAD")

    gate = report["checks"]["gate"]
    assert gate["not_run"] is not None
    assert "gate policy rejected" in gate["not_run"]
    assert "graphmark unavailable" not in gate["not_run"]
    unresolved_files = {f["file"] for f in report["checks"]["unresolved_links"]["findings"]}
    assert "brain/A.md" in unresolved_files
    assert not any(nr["check"] == "unresolved_links" for nr in report["not_run"])
    assert not any(nr["check"] == "orphans" for nr in report["not_run"])


# ===========================================================================
# round 3 — MEDIUM-C: new_orphans. `gate` alone only detects crossing the
# vault's orphan LIMIT — a regression that stays under it is invisible to
# gate but is still a regression this session caused.
# ===========================================================================

def test_new_orphans_findings_when_crossing_zero_to_one(tmp_path: Path) -> None:
    _git_init(tmp_path)
    # A stays linked to C throughout, so A itself never becomes an orphan —
    # only removing the [[B]] link is under test.
    _write(tmp_path, "brain/A.md", _note("A", body="See [[B]] and [[C]]."))
    _write(tmp_path, "brain/B.md", _note("B"))
    _write(tmp_path, "brain/C.md", _note("C"))
    _git_commit_all(tmp_path, "init")
    base_sha = _git_rev_parse(tmp_path, "HEAD")

    _write(tmp_path, "brain/A.md", _note("A", body="See [[C]]. No longer linking to B."))
    _git_commit_all(tmp_path, "remove link to B")

    report = collect(tmp_path, files=["brain/A.md"], base=base_sha)

    assert report["verdict"] == "FINDINGS"
    new_orphan_files = {f["file"] for f in report["checks"]["new_orphans"]["findings"]}
    assert "brain/B.md" in new_orphan_files
    assert report["checks"]["orphans"]["vault_wide_count"] == 1
    # The permissive gate seeded by _git_init (limit 1000) passes at 1 — the
    # exact hole new_orphans exists to cover.
    assert report["checks"]["gate"]["pass"] is True


def test_new_orphans_excludes_pre_existing_orphan(tmp_path: Path) -> None:
    _git_init(tmp_path)
    _write(tmp_path, "brain/AlreadyOrphan.md", _note("Already Orphan"))
    _write(tmp_path, "brain/A.md", _note("A", body="See [[B]]."))
    _write(tmp_path, "brain/B.md", _note("B"))
    _git_commit_all(tmp_path, "init")
    base_sha = _git_rev_parse(tmp_path, "HEAD")

    _write(tmp_path, "brain/A.md", _note("A", body="No longer linking to B, unrelated edit."))
    _git_commit_all(tmp_path, "remove link to B")

    report = collect(tmp_path, files=["brain/A.md"], base=base_sha)

    new_orphan_files = {f["file"] for f in report["checks"]["new_orphans"]["findings"]}
    assert "brain/AlreadyOrphan.md" not in new_orphan_files
    assert "brain/B.md" in new_orphan_files


# ===========================================================================
# round 3 — item 4: restored round-1 guard tests deleted by round 2's
# handoff rewrite (T9, T10)
# ===========================================================================

def test_handoff_preamble_edit_maps_to_preamble(tmp_path: Path) -> None:
    _git_init(tmp_path)
    _write(tmp_path, "brain/Anchor.md", _note("Anchor"))
    _write(tmp_path, ".brain/handoff-personal.md", _handoff_text())
    _git_commit_all(tmp_path, "init")
    base_sha = _git_rev_parse(tmp_path, "HEAD")

    new_text = _handoff_text().replace("Preamble line.", "New preamble line.")
    _write(tmp_path, ".brain/handoff-personal.md", new_text)
    _git_commit_all(tmp_path, "update handoff preamble")

    report = collect(tmp_path, files=["brain/Anchor.md"], base=base_sha)

    handoff = report["checks"]["handoff_sections"]
    assert handoff["touched"] == ["(preamble)"]


def test_handoff_untracked_file_all_sections_touched(tmp_path: Path) -> None:
    _git_init(tmp_path)
    _write(tmp_path, "brain/Anchor.md", _note("Anchor"))
    (tmp_path / ".brain" / "handoff-personal.md").unlink()  # no handoff at base
    _git_commit_all(tmp_path, "init")

    _write(tmp_path, ".brain/handoff-personal.md", _handoff_text())
    # left untracked deliberately

    report = collect(tmp_path, files=["brain/Anchor.md"], base="HEAD")

    handoff = report["checks"]["handoff_sections"]
    assert handoff["present"] == ["Resume From Here", "Open Threads", "Notes"]
    assert handoff["touched"] == handoff["present"]


# ===========================================================================
# round 3 — item 6 (T8b): a single hunk whose range crosses a heading
# boundary must report every heading it touches, not just the one at its
# first line. Kills a mutation that anchors only on new_start.
# ===========================================================================

def test_handoff_single_hunk_spans_two_sections_via_range(tmp_path: Path) -> None:
    text = (
        "Preamble line.\n\n"
        "## Resume From Here\n"
        "Old resume text.\n\n"
        "## Open Threads\n"
        "Old open threads text.\n"
    )
    _git_init(tmp_path)
    _write(tmp_path, ".brain/handoff-personal.md", text)
    _write(tmp_path, "brain/Anchor.md", _note("Anchor"))
    _git_commit_all(tmp_path, "init")
    base_sha = _git_rev_parse(tmp_path, "HEAD")

    new_text = (
        "Preamble line.\n\n"
        "## Resume From Here\n"
        "Old resume text.\n"
        "More resume content.\n\n"
        "## Followups\n"
        "Followup content.\n\n"
        "## Open Threads\n"
        "Old open threads text.\n"
    )
    _write(tmp_path, ".brain/handoff-personal.md", new_text)
    _git_commit_all(tmp_path, "insert a new section in one hunk")

    report = collect(tmp_path, files=["brain/Anchor.md"], base=base_sha)

    handoff = report["checks"]["handoff_sections"]
    assert "Resume From Here" in handoff["touched"]
    assert "Followups" in handoff["touched"]


# ===========================================================================
# round 3 — item 8 (m7): git-mode rename puts the new path in scope
# ===========================================================================

def test_git_mode_rename_new_path_in_scope(tmp_path: Path) -> None:
    _git_init(tmp_path)
    _write(tmp_path, "brain/Old Name.md", _note("Old Name", body="See [[Hub]]."))
    _write(tmp_path, "brain/Hub.md", _note("Hub", body="See [[Old Name]]."))
    _git_commit_all(tmp_path, "init")
    base_sha = _git_rev_parse(tmp_path, "HEAD")

    subprocess.run(["git", "mv", "brain/Old Name.md", "brain/New Name.md"], cwd=tmp_path, check=True)
    _git_commit_all(tmp_path, "rename")

    report = collect(tmp_path, files=None, base=base_sha)

    assert "brain/New Name.md" in report["scope"]["files"]


# ===========================================================================
# round 3 — item 10 (j3): a committed non-ASCII filename in git mode
# ===========================================================================

def test_git_mode_committed_non_ascii_note_gives_findings(tmp_path: Path) -> None:
    _git_init(tmp_path)
    _write(tmp_path, "brain/Anchor.md", _note("Anchor"))
    _git_commit_all(tmp_path, "init")
    base_sha = _git_rev_parse(tmp_path, "HEAD")

    bad = (
        "---\n"
        "date: 2026-07-08\n"
        "tags:\n"
        "  - reference\n"
        "---\n\n"
        "# Cafe\n\nMissing description.\n"
    )
    _write(tmp_path, "brain/Café Note.md", bad)
    _git_commit_all(tmp_path, "add cafe note")

    report = collect(tmp_path, files=None, base=base_sha)

    assert "brain/Café Note.md" in report["scope"]["files"]
    assert report["verdict"] == "FINDINGS"
    frontmatter_files = {f["file"] for f in report["checks"]["frontmatter"]["findings"]}
    assert "brain/Café Note.md" in frontmatter_files


# ===========================================================================
# round 3 — item 11: graphmark 0.7 parity fixtures. Each has a CONFIRMED
# different result under graphmark 0.6 (verified directly against both
# installed versions; see the round-3 report) — skipped under 0.6 rather
# than asserting the wrong 0.6 behavior.
# ===========================================================================

@NEEDS_GRAPHMARK_07
def test_graphmark_07_numeric_only_suffix_is_a_real_broken_link(tmp_path: Path) -> None:
    # 0.6's _targets_non_note_file regex treats a numeric-only suffix like
    # ".5" as a plausible file extension and suppresses the broken link;
    # 0.7 requires at least one letter and correctly reports it.
    _git_init(tmp_path)
    _write(tmp_path, "ci/vault_health.py", _gate_file(max_unresolved_links=0, max_orphans=3))
    _write(tmp_path, "brain/A.md", _note("A", body="See [[Meeting 3.5]]."))
    _git_commit_all(tmp_path, "init")

    report = collect(tmp_path, files=["brain/A.md"], base="HEAD")

    assert report["checks"]["unresolved_links"]["count"] == 1
    assert report["checks"]["gate"]["pass"] is False


@NEEDS_GRAPHMARK_07
def test_graphmark_07_path_suffix_needs_component_boundary(tmp_path: Path) -> None:
    # 0.6 matches [[work/Tasks]] against homework/Tasks.md (raw endswith);
    # 0.7 requires the match to land on a path-component boundary and
    # correctly leaves the link unresolved.
    _git_init(tmp_path)
    _write(tmp_path, "ci/vault_health.py", _gate_file(max_unresolved_links=0, max_orphans=3))
    _write(tmp_path, "brain/A.md", _note("A", body="See [[work/Tasks]]."))
    _write(tmp_path, "homework/Tasks.md", _note("Tasks"))
    _git_commit_all(tmp_path, "init")

    report = collect(tmp_path, files=["brain/A.md"], base="HEAD")

    assert report["checks"]["unresolved_links"]["count"] == 1
    assert report["checks"]["gate"]["pass"] is False


@NEEDS_GRAPHMARK_07
def test_graphmark_07_nfd_filename_resolves_nfc_link(tmp_path: Path) -> None:
    # 0.6 compares raw strings, so an NFD-normalized on-disk filename (as
    # macOS/APFS stores it) never matches an NFC-typed [[Café]] link; 0.7
    # composes both sides to NFC first and resolves it.
    _git_init(tmp_path)
    _write(tmp_path, "ci/vault_health.py", _gate_file(max_unresolved_links=0, max_orphans=3))
    nfd_name = unicodedata.normalize("NFD", "Café") + ".md"
    nfc_display = unicodedata.normalize("NFC", "Café")
    _write(tmp_path, "brain/A.md", _note("A", body=f"See [[{nfc_display}]]."))
    _write(tmp_path, f"brain/{nfd_name}", _note("Cafe note"))
    _git_commit_all(tmp_path, "init")

    report = collect(tmp_path, files=["brain/A.md"], base="HEAD")

    assert report["checks"]["unresolved_links"]["count"] == 0
    assert report["checks"]["gate"]["pass"] is True


# ===========================================================================
# round 3 — LOW-1: explicit --files yielding zero claimed notes must not
# read as CLEAN (nothing was actually audited)
# ===========================================================================

def test_files_only_directory_gives_incomplete(tmp_path: Path) -> None:
    _git_init(tmp_path)
    _write(tmp_path, "brain/A.md", _note("A"))
    _git_commit_all(tmp_path, "init")

    report = collect(tmp_path, files=["brain"], base="HEAD")

    assert report["verdict"] == "INCOMPLETE"
    assert any("no claimed notes" in e["reason"] for e in report["scope"]["errors"])


def test_files_only_non_note_gives_incomplete(tmp_path: Path) -> None:
    _git_init(tmp_path)
    _write(tmp_path, "brain/A.md", _note("A"))
    _git_commit_all(tmp_path, "init")

    report = collect(tmp_path, files=[".brain/handoff-personal.md"], base="HEAD")

    assert report["verdict"] == "INCOMPLETE"
    assert any("no claimed notes" in e["reason"] for e in report["scope"]["errors"])


# ===========================================================================
# round 4 — n2: a failing base-graph build must never read as CLEAN
# ===========================================================================

def test_new_orphans_build_failure_never_reads_as_clean(tmp_path: Path) -> None:
    # n2. A tracked absolute symlink makes `git archive | tarfile.extractall
    # (..., filter="data")` raise AbsoluteLinkError (Python 3.12+ PEP 706),
    # so _build_base_orphans fails while everything else (including the
    # handoff diff, also git-backed) still succeeds. The session's only
    # other edit (dropping A's link to B) is left UNCOMMITTED, so without
    # new_orphans catching it, nothing else would flag it either.
    _git_init(tmp_path)
    # A stays linked to C throughout, so A itself never becomes an orphan —
    # dropping the [[B]] link must be the ONLY thing new_orphans could catch.
    _write(tmp_path, "brain/A.md", _note("A", body="See [[B]] and [[C]]."))
    _write(tmp_path, "brain/B.md", _note("B"))
    _write(tmp_path, "brain/C.md", _note("C"))
    (tmp_path / "brain" / "link").symlink_to("/etc/hosts")
    _git_commit_all(tmp_path, "init")
    base_sha = _git_rev_parse(tmp_path, "HEAD")

    _write(tmp_path, "brain/A.md", _note("A", body="See [[C]]. No longer linking to B."))
    # left uncommitted deliberately

    report = collect(tmp_path, files=["brain/A.md"], base=base_sha)

    assert report["verdict"] == "INCOMPLETE"
    not_run_checks = {nr["check"] for nr in report["not_run"]}
    assert "new_orphans" in not_run_checks
    assert report["checks"]["handoff_sections"]["not_run"] is None


# ===========================================================================
# round 4 — n4/n4b/n4c: individual _parse_gate_policy guards, isolated
# ===========================================================================

def test_gate_no_check_usage_gives_incomplete(tmp_path: Path) -> None:
    # n4: `if not policy_refs:` guard
    _git_init(tmp_path)
    _write_gate_fixture(tmp_path, remove_b_link=True)  # 4 orphans, over limit 3
    _write(tmp_path, "ci/vault_health.py", GATE_POLICY_NO_CHECK_USAGE)
    _git_commit_all(tmp_path, "init")

    report = collect(tmp_path, files=["brain/A.md"], base="HEAD")

    assert report["verdict"] == "INCOMPLETE"
    assert report["checks"]["gate"]["not_run"] is not None


def test_gate_conflicting_check_usage_gives_incomplete(tmp_path: Path) -> None:
    # n4b: `if other_refs:` guard
    _git_init(tmp_path)
    _write_gate_fixture(tmp_path, remove_b_link=True)
    _write(tmp_path, "ci/vault_health.py", GATE_POLICY_CONFLICTING_CHECK_USAGE)
    _git_commit_all(tmp_path, "init")

    report = collect(tmp_path, files=["brain/A.md"], base="HEAD")

    assert report["verdict"] == "INCOMPLETE"
    assert report["checks"]["gate"]["not_run"] is not None


def test_gate_policy_only_inside_if_block_gives_incomplete(tmp_path: Path) -> None:
    # n4c: `if policy_node not in tree.body:` guard
    _git_init(tmp_path)
    _write_gate_fixture(tmp_path, remove_b_link=True)
    _write(tmp_path, "ci/vault_health.py", GATE_POLICY_ONLY_IN_IF_BLOCK)
    _git_commit_all(tmp_path, "init")

    report = collect(tmp_path, files=["brain/A.md"], base="HEAD")

    assert report["verdict"] == "INCOMPLETE"
    assert report["checks"]["gate"]["not_run"] is not None


# ===========================================================================
# round 4 — n10: new_orphans' in_scope flag must reflect claimed_set, not
# always be True
# ===========================================================================

def test_new_orphans_in_scope_flag_false_when_unclaimed(tmp_path: Path) -> None:
    # n10: the existing 0->1 orphan case, where B is unclaimed.
    _git_init(tmp_path)
    _write(tmp_path, "brain/A.md", _note("A", body="See [[B]] and [[C]]."))
    _write(tmp_path, "brain/B.md", _note("B"))
    _write(tmp_path, "brain/C.md", _note("C"))
    _git_commit_all(tmp_path, "init")
    base_sha = _git_rev_parse(tmp_path, "HEAD")

    _write(tmp_path, "brain/A.md", _note("A", body="See [[C]]. No longer linking to B."))
    _git_commit_all(tmp_path, "remove link to B")

    report = collect(tmp_path, files=["brain/A.md"], base=base_sha)

    new_orphans = report["checks"]["new_orphans"]["findings"]
    b_entry = next(f for f in new_orphans if f["file"] == "brain/B.md")
    assert b_entry["in_scope"] is False


def test_new_orphans_in_scope_flag_true_when_claimed(tmp_path: Path) -> None:
    # n10 counterpart: same regression, but B itself is also claimed.
    _git_init(tmp_path)
    _write(tmp_path, "brain/A.md", _note("A", body="See [[B]] and [[C]]."))
    _write(tmp_path, "brain/B.md", _note("B"))
    _write(tmp_path, "brain/C.md", _note("C"))
    _git_commit_all(tmp_path, "init")
    base_sha = _git_rev_parse(tmp_path, "HEAD")

    _write(tmp_path, "brain/A.md", _note("A", body="See [[C]]. No longer linking to B."))
    _git_commit_all(tmp_path, "remove link to B")

    report = collect(tmp_path, files=["brain/A.md", "brain/B.md"], base=base_sha)

    new_orphans = report["checks"]["new_orphans"]["findings"]
    b_entry = next(f for f in new_orphans if f["file"] == "brain/B.md")
    assert b_entry["in_scope"] is True
