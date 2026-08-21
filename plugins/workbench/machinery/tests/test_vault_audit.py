from __future__ import annotations

import sys
from datetime import date
from pathlib import Path

SCRIPTS_DIR = Path(__file__).resolve().parent.parent / "engine"
sys.path.insert(0, str(SCRIPTS_DIR))

from vault_audit import audit  # noqa: E402


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


def test_audit_uses_shared_scope_and_ignores_docs_and_manuals(tmp_path: Path) -> None:
    _write(tmp_path, "CLAUDE.md", "# Vault")
    _write(tmp_path, "brain/North Star.md", _note("North Star", body="See [[Draft Thought]]."))
    _write(tmp_path, "thinking/Draft Thought.md", "# Draft\n\n" + ("body " * 100))
    _write(tmp_path, "docs/plan.md", "# no frontmatter, intentionally ignored")
    _write(tmp_path, "work/AGENTS.md", "# policy, intentionally ignored")

    report = audit(tmp_path)

    assert report["summary"]["governed_notes"] == 1
    assert report["summary"]["graph_notes"] == 2
    assert report["issues"]["frontmatter"] == []
    assert report["thinking_promotion_queue"] == []


def test_audit_reports_broken_links_and_index_drift(tmp_path: Path) -> None:
    _write(tmp_path, "CLAUDE.md", "# Vault")
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
            "# Project\n\n"
            "See [[Missing Target]].\n"
        ),
    )

    report = audit(tmp_path)

    assert any("Missing Target" in issue["detail"] for issue in report["issues"]["broken_links"])
    assert any(issue["file"] == "work/active/Project.md" for issue in report["issues"]["work_index"])


def test_thinking_queue_counts_incoming_links(tmp_path: Path) -> None:
    _write(tmp_path, "CLAUDE.md", "# Vault")
    _write(tmp_path, "thinking/System Map.md", "# System Map\n\n" + ("body " * 100))
    _write(tmp_path, "brain/A.md", _note("A", body="See [[System Map]]."))
    _write(tmp_path, "brain/B.md", _note("B", body="See [[System Map]]."))

    report = audit(tmp_path)

    assert report["thinking_promotion_queue"] == [
        {"file": "thinking/System Map.md", "incoming": 2}
    ]


def test_audit_excludes_task_ledgers_from_graph_and_duplicate_description_noise(tmp_path: Path) -> None:
    _write(tmp_path, "CLAUDE.md", "# Vault")
    body = "- [ ] Task\n" * 60
    task_note = (
        "---\n"
        "date: 2026-07-08\n"
        "description: \"Weekly tasks\"\n"
        "tags:\n"
        "  - tasks\n"
        "week: 2026-W28\n"
        "---\n\n"
        f"{body}"
    )
    _write(tmp_path, "work/Tasks.md", task_note)
    _write(tmp_path, "work/archive/tasks/2026-W27-tasks.md", task_note)

    report = audit(tmp_path)

    assert report["summary"]["governed_notes"] == 2
    assert report["summary"]["graph_notes"] == 0
    assert report["issues"]["frontmatter"] == []
    assert report["issues"]["duplicate_descriptions"] == []


def test_transient_task_ledgers_are_resolvable_link_targets(tmp_path: Path) -> None:
    _write(tmp_path, "CLAUDE.md", "# Vault")
    _write(
        tmp_path,
        "brain/Decision.md",
        _note("Decision", body="Follow up in [[Tasks]]."),
    )
    _write(
        tmp_path,
        "work/Tasks.md",
        (
            "---\n"
            "date: 2026-07-08\n"
            "description: \"Work task ledger\"\n"
            "tags:\n"
            "  - tasks\n"
            "week: 2026-W28\n"
            "---\n\n"
            "- [ ] Task\n"
        ),
    )

    report = audit(tmp_path)

    assert report["summary"]["graph_notes"] == 1
    assert not any("Tasks" in issue["detail"] for issue in report["issues"]["broken_links"])


def test_frontmatter_aliases_resolve_wikilinks(tmp_path: Path) -> None:
    _write(tmp_path, "CLAUDE.md", "# Vault")
    _write(
        tmp_path,
        "work/active/Asset Management Reporting Tool.md",
        (
            "---\n"
            "date: 2026-07-08\n"
            "description: \"AMRT project\"\n"
            "aliases:\n"
            "  - AMRT\n"
            "tags:\n"
            "  - work-note\n"
            "status: active\n"
            "project: \"Asset Management Reporting Tool\"\n"
            "---\n\n"
            "# Asset Management Reporting Tool\n\n"
            "See [[Work Index]].\n"
        ),
    )
    _write(tmp_path, "brain/Decision.md", _note("Decision", body="Use [[AMRT]]."))

    report = audit(tmp_path)

    assert not any("AMRT" in issue["detail"] for issue in report["issues"]["broken_links"])


def test_audit_ignores_wikilinks_inside_code_examples(tmp_path: Path) -> None:
    _write(tmp_path, "CLAUDE.md", "# Vault")
    _write(
        tmp_path,
        "brain/Pattern.md",
        _note(
            "Pattern",
            body="Use `[[folder/note]]` as syntax.\n\n```md\n[[Target]]\n```\n",
        ),
    )

    report = audit(tmp_path)

    assert report["issues"]["broken_links"] == []


def test_operating_files_are_resolvable_link_targets(tmp_path: Path) -> None:
    _write(tmp_path, "CLAUDE.md", "# Vault")
    _write(tmp_path, "brain/Pattern.md", _note("Pattern", body="See [[CLAUDE]]."))

    report = audit(tmp_path)

    assert report["issues"]["broken_links"] == []


def test_existing_pdf_attachment_link_is_not_broken(tmp_path: Path) -> None:
    _write(tmp_path, "CLAUDE.md", "# Vault")
    pdf = tmp_path / "assets" / "Corp Org Chart 2026-04-21.pdf"
    pdf.parent.mkdir(parents=True, exist_ok=True)
    pdf.write_bytes(b"%PDF-1.4 stub")
    _write(
        tmp_path,
        "org/Org Chart.md",
        _note("Org Chart", body="See [[assets/Corp Org Chart 2026-04-21.pdf]]."),
    )

    report = audit(tmp_path)

    assert report["issues"]["broken_links"] == []


def test_missing_pdf_attachment_link_is_still_broken(tmp_path: Path) -> None:
    _write(tmp_path, "CLAUDE.md", "# Vault")
    _write(
        tmp_path,
        "org/Org Chart.md",
        _note("Org Chart", body="See [[assets/Nonexistent Chart.pdf]]."),
    )

    report = audit(tmp_path)

    assert any(
        "Nonexistent Chart.pdf" in issue["detail"]
        for issue in report["issues"]["broken_links"]
    )


def test_bare_pdf_attachment_name_resolves_via_assets_dir(tmp_path: Path) -> None:
    _write(tmp_path, "CLAUDE.md", "# Vault")
    pdf = tmp_path / "assets" / "Corp Org Chart 2026-04-21.pdf"
    pdf.parent.mkdir(parents=True, exist_ok=True)
    pdf.write_bytes(b"%PDF-1.4 stub")
    _write(
        tmp_path,
        "org/Org Chart.md",
        _note("Org Chart", body="See [[Corp Org Chart 2026-04-21.pdf]]."),
    )

    report = audit(tmp_path)

    assert report["issues"]["broken_links"] == []


def test_skill_name_frontmatter_resolves_wikilinks(tmp_path: Path) -> None:
    _write(tmp_path, "CLAUDE.md", "# Vault")
    _write(
        tmp_path,
        "reference/skills/drafts/afk-drive/SKILL.md",
        (
            "---\n"
            "name: afk-drive\n"
            "date: 2026-07-08\n"
            "description: \"Draft skill\"\n"
            "tags:\n"
            "  - skill-draft\n"
            "---\n\n"
            "# afk-drive\n\n"
            "See [[Capabilities]].\n"
        ),
    )
    _write(tmp_path, "brain/Decision.md", _note("Decision", body="Use [[afk-drive]]."))

    report = audit(tmp_path)

    assert not any("afk-drive" in issue["detail"] for issue in report["issues"]["broken_links"])


def test_stale_active_uses_updated_or_mtime_not_creation_date(tmp_path: Path) -> None:
    _write(tmp_path, "CLAUDE.md", "# Vault")
    _write(
        tmp_path,
        "work/active/Long Running Project.md",
        (
            "---\n"
            "date: 2026-01-01\n"
            "description: \"Long-running but recently touched project\"\n"
            "tags:\n"
            "  - work-note\n"
            "status: active\n"
            "project: \"Long Running Project\"\n"
            "---\n\n"
            "# Long Running Project\n\n"
            "See [[Work Index]].\n"
        ),
    )
    _write(
        tmp_path,
        "work/active/Explicitly Stale Project.md",
        (
            "---\n"
            "date: 2026-07-01\n"
            "updated: 2026-01-01\n"
            "description: \"Project with old explicit updated date\"\n"
            "tags:\n"
            "  - work-note\n"
            "status: active\n"
            "project: \"Explicitly Stale Project\"\n"
            "---\n\n"
            "# Explicitly Stale Project\n\n"
            "See [[Work Index]].\n"
        ),
    )

    report = audit(tmp_path, today=date(2026, 7, 8))

    stale_files = {issue["file"] for issue in report["issues"]["stale_active"]}
    assert "work/active/Long Running Project.md" not in stale_files
    assert "work/active/Explicitly Stale Project.md" in stale_files
