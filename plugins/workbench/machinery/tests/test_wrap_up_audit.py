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


def _git_init(repo: Path) -> None:
    subprocess.run(["git", "init", "-q"], cwd=repo, check=True)
    subprocess.run(["git", "config", "user.email", "test@example.com"], cwd=repo, check=True)
    subprocess.run(["git", "config", "user.name", "Test"], cwd=repo, check=True)


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


# ---------------------------------------------------------------------------
# clean scope
# ---------------------------------------------------------------------------

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


# ---------------------------------------------------------------------------
# in-scope findings, one per check
# ---------------------------------------------------------------------------

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


# ---------------------------------------------------------------------------
# scope honoring
# ---------------------------------------------------------------------------

def test_broken_link_in_untouched_note_out_of_scope(tmp_path: Path) -> None:
    _git_init(tmp_path)
    _write(tmp_path, "brain/Old Name.md", _note("Old Name"))
    _write(tmp_path, "brain/Untouched.md", _note("Untouched", body="See [[Old Name]]."))
    _git_commit_all(tmp_path, "init")
    base_sha = _git_rev_parse(tmp_path, "HEAD")

    # Session renames the link target; Untouched.md itself is not edited.
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


# ---------------------------------------------------------------------------
# orphans
# ---------------------------------------------------------------------------

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


# ---------------------------------------------------------------------------
# handoff sections
# ---------------------------------------------------------------------------

def test_handoff_touched_sections_exact(tmp_path: Path) -> None:
    _git_init(tmp_path)
    _write(tmp_path, ".vault-context", "personal")
    _write(tmp_path, ".brain/handoff-personal.md", _handoff_text())
    _git_commit_all(tmp_path, "init")
    base_sha = _git_rev_parse(tmp_path, "HEAD")

    new_text = _handoff_text().replace("Old resume text.", "New resume text.").replace(
        "Old notes text.", "New notes text."
    )
    _write(tmp_path, ".brain/handoff-personal.md", new_text)
    _git_commit_all(tmp_path, "update handoff")

    report = collect(tmp_path, files=[], base=base_sha)

    handoff = report["checks"]["handoff_sections"]
    assert handoff["present"] == ["Resume From Here", "Open Threads", "Notes"]
    assert handoff["touched"] == ["Resume From Here", "Notes"]


def test_handoff_preamble_edit_maps_to_preamble(tmp_path: Path) -> None:
    _git_init(tmp_path)
    _write(tmp_path, ".vault-context", "personal")
    _write(tmp_path, ".brain/handoff-personal.md", _handoff_text())
    _git_commit_all(tmp_path, "init")
    base_sha = _git_rev_parse(tmp_path, "HEAD")

    new_text = _handoff_text().replace("Preamble line.", "New preamble line.")
    _write(tmp_path, ".brain/handoff-personal.md", new_text)
    _git_commit_all(tmp_path, "update handoff preamble")

    report = collect(tmp_path, files=[], base=base_sha)

    handoff = report["checks"]["handoff_sections"]
    assert handoff["touched"] == ["(preamble)"]


def test_handoff_untracked_file_all_sections_touched(tmp_path: Path) -> None:
    _git_init(tmp_path)
    _write(tmp_path, ".vault-context", "personal")
    _git_commit_all(tmp_path, "init")  # no handoff file yet at base

    _write(tmp_path, ".brain/handoff-personal.md", _handoff_text())
    # left untracked deliberately

    report = collect(tmp_path, files=[], base="HEAD")

    handoff = report["checks"]["handoff_sections"]
    assert handoff["present"] == ["Resume From Here", "Open Threads", "Notes"]
    assert handoff["touched"] == handoff["present"]


# ---------------------------------------------------------------------------
# graphmark unavailable
# ---------------------------------------------------------------------------

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


# ---------------------------------------------------------------------------
# scope fallback
# ---------------------------------------------------------------------------

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
