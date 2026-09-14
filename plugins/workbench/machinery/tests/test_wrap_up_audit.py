from __future__ import annotations

import builtins
import subprocess
import sys
from pathlib import Path

SCRIPTS_DIR = Path(__file__).resolve().parent.parent / "engine"
sys.path.insert(0, str(SCRIPTS_DIR))

from wrap_up_audit import VERDICT_EXIT_CODES, collect, main  # noqa: E402


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


PERMISSIVE_GATE_POLICY = (
    "from graphmark.config import CheckPolicy\n\n"
    "POLICY = CheckPolicy(\n"
    "    max_unresolved_links=1000,\n"
    "    max_orphans=1000,\n"
    ")\n"
)


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


GATE_POLICY_3_0 = (
    "from graphmark.config import CheckPolicy\n\n"
    "POLICY = CheckPolicy(\n"
    "    max_unresolved_links=0,\n"
    "    max_orphans=3,\n"
    ")\n"
)

GATE_POLICY_NON_LITERAL = (
    "from graphmark.config import CheckPolicy\n\n"
    "_max = 3\n\n"
    "POLICY = CheckPolicy(\n"
    "    max_unresolved_links=0,\n"
    "    max_orphans=_max,\n"
    ")\n"
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
    # X9 (no git init at all)
    _write(tmp_path, "brain/A.md", _note("A"))

    report = collect(tmp_path, files=None, base="HEAD")

    assert report["verdict"] == "INCOMPLETE"


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
