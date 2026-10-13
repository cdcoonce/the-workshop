from __future__ import annotations

import sys
from datetime import date
from pathlib import Path

import pytest

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


def test_audit_reports_a_date_inversion_in_an_accumulating_hub_file(tmp_path: Path) -> None:
    _write(tmp_path, "CLAUDE.md", "# Vault")
    _write(
        tmp_path,
        "brain/Key Decisions.md",
        _note(
            "Key Decisions",
            tags="index",
            body=(
                "## Recent\n\n"
                "### 2026-08-01 — newest, correctly on top\n\nBody.\n\n"
                "### 2026-09-01 — appended at the bottom instead\n\nBody.\n"
            ),
        ),
    )

    report = audit(tmp_path)

    inversions = report["issues"]["entry_order"]
    assert len(inversions) == 1
    assert inversions[0]["file"] == "brain/Key Decisions.md"
    assert "2026-09-01" in inversions[0]["detail"]
    assert "2026-08-01" in inversions[0]["detail"]


def test_audit_reports_a_date_inversion_in_a_bulleted_hub_file(tmp_path: Path) -> None:
    """The Brag Doc accumulates "- **YYYY-MM-DD" bullets, not "###" headings."""
    _write(tmp_path, "CLAUDE.md", "# Vault")
    _write(
        tmp_path,
        "perf/Brag Doc.md",
        _note(
            "Brag Doc",
            tags="index",
            body=(
                "- **2026-08-01 — a win, correctly on top**\n\n"
                "- **2026-09-01 — appended at the bottom instead**\n"
            ),
        ),
    )

    report = audit(tmp_path)

    inversions = report["issues"]["entry_order"]
    assert len(inversions) == 1
    assert inversions[0]["file"] == "perf/Brag Doc.md"


def test_audit_accepts_newest_first_entries_including_same_day_runs(tmp_path: Path) -> None:
    """Several sessions can close on one day, so equal adjacent dates are legal."""
    _write(tmp_path, "CLAUDE.md", "# Vault")
    _write(
        tmp_path,
        "brain/Key Decisions.md",
        _note(
            "Key Decisions",
            tags="index",
            body=(
                "## Recent\n\n"
                "### 2026-09-02 — newest\n\nBody.\n\n"
                "### 2026-09-01 — same day as the next\n\nBody.\n\n"
                "### 2026-09-01 — second entry that day\n\nBody.\n\n"
                "### 2026-08-30 — oldest\n\nBody.\n"
            ),
        ),
    )

    report = audit(tmp_path)

    assert report["issues"]["entry_order"] == []


def test_audit_reports_every_inversion_not_only_the_first(tmp_path: Path) -> None:
    _write(tmp_path, "CLAUDE.md", "# Vault")
    _write(
        tmp_path,
        "brain/Key Decisions.md",
        _note(
            "Key Decisions",
            tags="index",
            body=(
                "## Recent\n\n"
                "### 2026-08-01 — oldest\n\nBody.\n\n"
                "### 2026-08-02 — appended\n\nBody.\n\n"
                "### 2026-08-03 — appended\n\nBody.\n\n"
                "### 2026-08-04 — appended\n\nBody.\n"
            ),
        ),
    )

    report = audit(tmp_path)

    assert len(report["issues"]["entry_order"]) == 3


def test_audit_ignores_a_hub_file_with_no_dated_entries(tmp_path: Path) -> None:
    _write(tmp_path, "CLAUDE.md", "# Vault")
    _write(
        tmp_path,
        "brain/Patterns.md",
        _note("Patterns", tags="index", body="## Recent\n\nProse with no dated entries.\n"),
    )

    report = audit(tmp_path)

    assert report["issues"]["entry_order"] == []


# --- the entry grammar is the vault-sync entry replay's (entry_replay.py) ---


def _gotchas(body: str) -> str:
    return _note("Gotchas", tags="index", body=body)


def _order_details(tmp_path: Path, rel: str, body: str) -> list[str]:
    _write(tmp_path, "CLAUDE.md", "# Vault")
    _write(tmp_path, rel, _note(Path(rel).stem, tags="index", body=body))
    return [issue["detail"] for issue in audit(tmp_path)["issues"]["entry_order"]]


def test_audit_reads_a_gotchas_heading_dated_at_its_end(tmp_path: Path) -> None:
    """Gotchas date an entry in a trailing ``(YYYY-MM-DD)``, not a leading one."""
    details = _order_details(
        tmp_path,
        "brain/Gotchas.md",
        "## Technical\n\n"
        "### A trap found first (2026-08-01)\n\nBody.\n\n"
        "### A trap appended below it (2026-09-01)\n\nBody.\n",
    )

    assert len(details) == 1
    assert "2026-09-01" in details[0] and "2026-08-01" in details[0]


def test_audit_reads_a_qualified_gotchas_date_by_its_first_date(tmp_path: Path) -> None:
    """``(DATE, qualifier)`` and ``(DATE onward, qualifier)`` date the entry by DATE."""
    details = _order_details(
        tmp_path,
        "brain/Gotchas.md",
        "## Technical\n\n"
        "### Older, with a project (2026-08-01, [[apipulse]])\n\nBody.\n\n"
        "### Newer, with a span (2026-09-01 onward, [[skywatch]])\n\nBody.\n\n"
        "### Corrected later (2026-07-01, corrected 2026-10-01)\n\nBody.\n",
    )

    assert len(details) == 1
    assert "2026-09-01" in details[0] and "2026-08-01" in details[0]


def test_audit_does_not_read_a_dated_bullet_in_a_heading_entry_body(tmp_path: Path) -> None:
    """A heading entry quoting a dated bullet is one entry, not two."""
    details = _order_details(
        tmp_path,
        "brain/Key Decisions.md",
        "## Recent\n\n"
        "### 2026-09-02 — newest\n\n"
        "- **2026-09-30 — a bullet the decision quotes**\n\n"
        "### 2026-09-01 — older\n\nBody.\n",
    )

    assert details == []


def test_audit_still_reads_dated_bullets_in_a_block_without_dated_headings(
    tmp_path: Path,
) -> None:
    details = _order_details(
        tmp_path,
        "perf/Brag Doc.md",
        "## Q3 2026\n\n### Wins\n\n"
        "- **2026-08-01 — a win**\n\n"
        "- **2026-09-01 — appended below it**\n",
    )

    assert len(details) == 1


def test_audit_ignores_dated_lines_inside_a_code_fence(tmp_path: Path) -> None:
    """A fenced example is not an entry, even a four-backtick fence holding a three-backtick line."""
    details = _order_details(
        tmp_path,
        "brain/Gotchas.md",
        "## Technical\n\n"
        "### A trap with an example (2026-09-02)\n\n"
        "````markdown\n"
        "```\n"
        "### Quoted heading (2026-09-30)\n"
        "- **2026-09-30 — quoted bullet**\n"
        "````\n\n"
        "### An older trap (2026-09-01)\n\nBody.\n",
    )

    assert details == []


def test_audit_treats_a_dated_level_two_heading_as_an_anchor_not_an_entry(
    tmp_path: Path,
) -> None:
    details = _order_details(
        tmp_path,
        "brain/Key Decisions.md",
        "## 2026-01-01 archive\n\n"
        "### 2026-09-02 — newest\n\nBody.\n\n"
        "### 2026-09-01 — older\n\nBody.\n",
    )

    assert details == []


def test_audit_reads_dated_headings_below_level_four(tmp_path: Path) -> None:
    details = _order_details(
        tmp_path,
        "brain/Key Decisions.md",
        "## Recent\n\n"
        "##### 2026-08-01 — oldest\n\nBody.\n\n"
        "##### 2026-09-01 — appended\n\nBody.\n",
    )

    assert len(details) == 1


@pytest.mark.parametrize(
    ("rel", "body"),
    [
        (
            "perf/Brag Doc.md",
            "## Q3 2026\n\n### Wins\n\n"
            "- **2026-09-01 — real**\n\n"
            "- **2026-13-45 — not a date**\n\n"
            "- **2026-08-01 — older**\n",
        ),
        (
            "brain/Key Decisions.md",
            "## Recent\n\n"
            "### 2026-09-01 — real\n\n"
            "#### 2026-13-45 — not a date\n\n"
            "### 2026-08-01 — older\n",
        ),
        (
            "brain/Gotchas.md",
            "## Technical\n\n"
            "### Real (2026-09-01)\n\n"
            "#### Not a date (2026-13-45)\n\n"
            "### Older (2026-08-01)\n",
        ),
    ],
    ids=["bullet", "leading", "trailing"],
)
def test_audit_skips_a_date_that_is_not_a_calendar_date(
    tmp_path: Path, rel: str, body: str
) -> None:
    assert _order_details(tmp_path, rel, body) == []


def test_audit_compares_entries_only_within_one_anchor_block(tmp_path: Path) -> None:
    """Wins and Growth are separate newest-first runs; the boundary is not an inversion."""
    details = _order_details(
        tmp_path,
        "perf/Brag Doc.md",
        "## Q3 2026\n\n"
        "### Wins\n\n"
        "- **2026-09-02 — newest win**\n\n"
        "- **2026-07-01 — oldest win**\n\n"
        "### Growth\n\n"
        "- **2026-08-12 — newest growth**\n\n"
        "- **2026-07-02 — oldest growth**\n\n"
        "- **2026-07-30 — appended growth**\n",
    )

    assert len(details) == 1
    assert "2026-07-30" in details[0] and "2026-07-02" in details[0]


def test_audit_reads_entries_outside_any_anchor_block_as_their_own_run(
    tmp_path: Path,
) -> None:
    """Dated bullets straight under the title still form a run and still invert."""
    details = _order_details(
        tmp_path,
        "perf/Brag Doc.md",
        "- **2026-08-01 — a win**\n\n"
        "- **2026-09-01 — appended below it**\n\n"
        "## Q3 2026\n\n### Wins\n\n"
        "- **2026-07-01 — inside the block, older than the run above**\n",
    )

    assert len(details) == 1
    assert "2026-09-01" in details[0] and "2026-08-01" in details[0]


def test_audit_reads_dated_headings_outside_any_anchor_block_as_one_run(
    tmp_path: Path,
) -> None:
    details = _order_details(
        tmp_path,
        "brain/Key Decisions.md",
        "### 2026-08-01 — straight under the title\n\nBody.\n\n"
        "### 2026-09-01 — appended below it\n\nBody.\n",
    )

    assert len(details) == 1


def test_audit_splits_unanchored_entries_at_a_non_entry_heading(tmp_path: Path) -> None:
    """``## Q3 2026`` holds ``### Wins``, so it is no anchor, but it still ends the run above."""
    details = _order_details(
        tmp_path,
        "perf/Brag Doc.md",
        "- **2026-09-01 — under the title**\n\n"
        "## Q3 2026\n\n"
        "- **2026-10-01 — in the quarter's preamble**\n\n"
        "### Wins\n\n- **2026-08-01 — a win**\n",
    )

    assert details == []


def test_audit_does_not_read_dated_bullets_under_an_entrys_subheading(
    tmp_path: Path,
) -> None:
    details = _order_details(
        tmp_path,
        "brain/Key Decisions.md",
        "## Recent\n\n"
        "### 2026-09-02 — newest\n\n"
        "#### Timeline\n\n"
        "- **2026-08-01 — first step**\n\n"
        "- **2026-08-15 — second step**\n\n"
        "### 2026-09-01 — older\n\nBody.\n",
    )

    assert details == []


def test_audit_reports_inversions_in_file_order(tmp_path: Path) -> None:
    details = _order_details(
        tmp_path,
        "perf/Brag Doc.md",
        "- **2026-08-01 — under the title**\n\n"
        "- **2026-09-01 — appended**\n\n"
        "## Q3 2026\n\n### Wins\n\n"
        "- **2026-07-01 — a win**\n\n"
        "- **2026-07-30 — appended**\n",
    )

    assert [detail.split(" ", 1)[0] for detail in details] == ["2026-09-01", "2026-07-30"]


def test_audit_reports_the_inverted_entry_at_its_file_line(tmp_path: Path) -> None:
    details = _order_details(
        tmp_path,
        "brain/Gotchas.md",
        "## Technical\n\n"
        "### First (2026-08-01)\n\nBody.\n\n"
        "### Second (2026-09-01)\n\nBody.\n",
    )
    text = (tmp_path / "brain/Gotchas.md").read_text(encoding="utf-8").splitlines()
    first = text.index("### First (2026-08-01)") + 1
    second = text.index("### Second (2026-09-01)") + 1

    assert details == [
        f"2026-09-01 (line {second}) follows the older 2026-08-01 (line {first})"
        " — entries run newest-first"
    ]


def test_entry_order_reads_entries_through_the_shared_vault_utils_grammar() -> None:
    """The grammar the vault-sync parity test pins is the one the detector runs."""
    import vault_audit
    import vault_utils

    assert vault_audit.entry_runs is vault_utils.entry_runs


# --- #1077: no module-level name shadows the shared vault_utils pattern ---


def test_vault_audit_does_not_shadow_the_shared_wikilink_pattern() -> None:
    import vault_audit
    import vault_utils

    shadow = getattr(vault_audit, "WIKILINK_RE", vault_utils.WIKILINK_RE)
    assert shadow is vault_utils.WIKILINK_RE
    # The embed-aware pattern keeps its two groups under its own name.
    assert vault_audit.WIKILINK_WITH_EMBED_RE.groups == 2


# --- #730: one shared code-span detector that knows ~~~ fences ---


def test_audit_ignores_wikilinks_inside_tilde_fences(tmp_path: Path) -> None:
    _write(tmp_path, "CLAUDE.md", "# Vault")
    _write(
        tmp_path,
        "brain/Pattern.md",
        _note("Pattern", body="Example:\n\n~~~md\n[[Nowhere Target]]\n~~~\n"),
    )

    report = audit(tmp_path)

    assert report["issues"]["broken_links"] == []
    assert report["issues"]["ambiguous_links"] == []


def test_audit_still_reports_a_real_link_after_a_tilde_fence(tmp_path: Path) -> None:
    _write(tmp_path, "CLAUDE.md", "# Vault")
    _write(
        tmp_path,
        "brain/Pattern.md",
        _note("Pattern", body="~~~\n[[Fenced]]\n~~~\n\nReal: [[Really Missing]]\n"),
    )

    report = audit(tmp_path)

    details = [i["detail"] for i in report["issues"]["broken_links"]]
    assert details == ["broken [[Really Missing]]"]


def test_code_span_detection_is_the_shared_vault_utils_function() -> None:
    import vault_audit
    import vault_utils

    assert vault_audit._code_spans is vault_utils.code_spans
    text = "a `x` b\n~~~\nfenced\n~~~\n"
    kinds = vault_utils.code_spans(text)
    assert (text.index("`x`"), text.index("`x`") + 3) in kinds
    assert any(start == text.index("~~~") for start, _ in kinds)


# --- #725 / #810 / #811: the link catalog and resolver ---


def _issues(report: dict, group: str) -> list[str]:
    return [i["detail"] for i in report["issues"][group]]


def test_self_alias_colliding_with_stem_is_not_ambiguous(tmp_path: Path) -> None:
    """#725: stem and alias normalizing to one key must not double-count the note."""
    _write(tmp_path, "CLAUDE.md", "# Vault")
    _write(
        tmp_path,
        "org/people/Charles-Coonce.md",
        "---\ndate: 2026-07-08\ndescription: \"Charles\"\ntags:\n  - person\n"
        "aliases:\n  - \"Charles Coonce\"\n---\n\n# Charles\n\nBody.\n",
    )
    _write(tmp_path, "brain/Pattern.md", _note("Pattern", body="Ask [[charles coonce]]."))

    report = audit(tmp_path)

    assert _issues(report, "ambiguous_links") == []
    assert _issues(report, "broken_links") == []


def _two_notes_fixture(root: Path) -> None:
    _write(root, "CLAUDE.md", "# Vault")
    _write(root, "personal/projects/alpha/NOTES.md", _note("Alpha notes"))
    _write(root, "personal/projects/beta/NOTES.md", _note("Beta notes"))


def test_path_qualified_link_with_unique_suffix_resolves(tmp_path: Path) -> None:
    """#810 case A: only one file ends in alpha/NOTES, so it is not ambiguous."""
    _two_notes_fixture(tmp_path)
    _write(tmp_path, "personal/Index.md", _note("Index", body="See [[alpha/NOTES]]."))

    report = audit(tmp_path)

    assert _issues(report, "ambiguous_links") == []
    assert _issues(report, "broken_links") == []


def test_fully_qualified_link_still_resolves(tmp_path: Path) -> None:
    """#810 case B: no regression for the vault-relative path form."""
    _two_notes_fixture(tmp_path)
    _write(
        tmp_path,
        "personal/Index.md",
        _note("Index", body="See [[personal/projects/alpha/NOTES]]."),
    )

    report = audit(tmp_path)

    assert _issues(report, "ambiguous_links") == []
    assert _issues(report, "broken_links") == []


def test_bare_name_matching_two_notes_is_reported_ambiguous(tmp_path: Path) -> None:
    """#810 case C: a colliding bare target must not silently pick a winner."""
    _two_notes_fixture(tmp_path)
    _write(tmp_path, "personal/Index.md", _note("Index", body="See [[NOTES]]."))

    report = audit(tmp_path)

    ambiguous = _issues(report, "ambiguous_links")
    assert len(ambiguous) == 1
    assert "alpha/NOTES.md" in ambiguous[0] and "beta/NOTES.md" in ambiguous[0]


def test_path_link_disambiguates_a_colliding_basename(tmp_path: Path) -> None:
    _two_notes_fixture(tmp_path)
    _write(
        tmp_path,
        "personal/Index.md",
        _note("Index", body="See [[projects/beta/NOTES]]. Also [[gamma/NOTES]]."),
    )

    report = audit(tmp_path)

    assert _issues(report, "ambiguous_links") == []
    assert _issues(report, "broken_links") == ["broken [[gamma/NOTES]]"]


def _stem_vs_alias_fixture(root: Path) -> None:
    _write(root, "CLAUDE.md", "# Vault")
    long_body = "Body text. " * 40
    _write(root, "reference/repo-crash-course.md", _note("Crash course", body=long_body))
    _write(
        root,
        "reference/skills/repo-crash-course/SKILL.md",
        "---\ndate: 2026-07-08\ndescription: \"Skill\"\ntags:\n  - reference\n"
        "aliases:\n  - repo-crash-course\n---\n\n# Skill\n\n" + long_body + "\n",
    )
    _write(root, "brain/Linker.md", _note("Linker", body="Use [[repo-crash-course]]."))


def _audit_under_seed(root: Path, seed: str) -> dict:
    """Run ``audit`` in a fresh interpreter pinned to one PYTHONHASHSEED."""
    import json
    import os
    import subprocess
    import sys as _sys

    code = (
        "import json, sys\n"
        f"sys.path.insert(0, {str(SCRIPTS_DIR)!r})\n"
        "from pathlib import Path\n"
        "from vault_audit import audit\n"
        "r = audit(Path(sys.argv[1]))\n"
        "print(json.dumps({'issues': r['issues'], 'queue': r['thinking_promotion_queue']},"
        " sort_keys=True))\n"
    )
    done = subprocess.run(
        [_sys.executable, "-c", code, str(root)],
        capture_output=True, text=True, check=True,
        env={**os.environ, "PYTHONHASHSEED": seed},
    )
    return json.loads(done.stdout)


def test_exact_filename_beats_another_notes_alias(tmp_path: Path) -> None:
    """#810: the file literally named after the target wins over an alias."""
    _stem_vs_alias_fixture(tmp_path)

    for seed in ("1", "2", "3", "4", "5"):
        orphans = {i["file"] for i in _audit_under_seed(tmp_path, seed)["issues"]["orphans"]}
        assert "reference/repo-crash-course.md" not in orphans, seed
        assert "reference/skills/repo-crash-course/SKILL.md" in orphans, seed


def test_resolution_is_identical_across_hash_seeds(tmp_path: Path) -> None:
    """#810: the backlink graph must not depend on set iteration order."""
    _stem_vs_alias_fixture(tmp_path)
    _two_notes_fixture(tmp_path)
    _write(tmp_path, "personal/Index.md", _note("Index", body="[[NOTES]] [[alpha/NOTES]]"))

    runs = [_audit_under_seed(tmp_path, seed) for seed in ("1", "2", "3", "4", "5")]

    assert all(run == runs[0] for run in runs)


def _decoy_manuals(root: Path) -> None:
    for rel in (
        ".claude/worktrees/agent-1/AGENTS.md",
        ".venv/lib/site-packages/somepkg/AGENTS.md",
        "node_modules/leftpad/CLAUDE.md",
        "templates/AGENTS.md",
    ):
        _write(root, rel, "# decoy")


def test_operating_files_in_excluded_dirs_are_not_link_targets(tmp_path: Path) -> None:
    """#811: decoy manuals under excluded directories never enter the catalog."""
    _write(tmp_path, "brain/Pattern.md", _note("Pattern", body="See [[AGENTS]] and [[CLAUDE]]."))
    _decoy_manuals(tmp_path)

    report = audit(tmp_path)

    assert sorted(_issues(report, "broken_links")) == ["broken [[AGENTS]]", "broken [[CLAUDE]]"]


def test_audit_does_not_depend_on_a_transient_agent_worktree(tmp_path: Path) -> None:
    """#811: the same vault audits the same with or without a worktree checkout."""
    _write(tmp_path, "brain/Pattern.md", _note("Pattern", body="See [[AGENTS]]."))
    before = audit(tmp_path)["issues"]
    _write(tmp_path, ".claude/worktrees/agent-1/AGENTS.md", "# transient checkout")
    after = audit(tmp_path)["issues"]

    assert before == after


def test_root_operating_manual_resolves_beside_excluded_decoys(tmp_path: Path) -> None:
    """#811: a directory-only filter keeps the vault's own manual resolvable."""
    _write(tmp_path, "AGENTS.md", "# Vault")
    _write(tmp_path, "brain/Pattern.md", _note("Pattern", body="See [[AGENTS]]."))
    _decoy_manuals(tmp_path)

    report = audit(tmp_path)

    assert _issues(report, "broken_links") == []
    assert _issues(report, "ambiguous_links") == []


def test_nested_readme_is_not_a_link_target(tmp_path: Path) -> None:
    """#811: root-excluded files stay bounded to depth one."""
    _write(tmp_path, "tools/README.md", "# nested")
    _write(tmp_path, "brain/Pattern.md", _note("Pattern", body="See [[README]]."))

    report = audit(tmp_path)

    assert _issues(report, "broken_links") == ["broken [[README]]"]


def test_manuals_in_note_directories_still_resolve(tmp_path: Path) -> None:
    """#811: only excluded directories are filtered; nested manuals stay targets."""
    _write(tmp_path, "CLAUDE.md", "# Vault")
    _write(tmp_path, "brain/p/CLAUDE.md", "# Project manual")
    _write(tmp_path, "brain/Pattern.md", _note("Pattern", body="See [[p/CLAUDE]]."))

    report = audit(tmp_path)

    assert _issues(report, "broken_links") == []
    assert _issues(report, "ambiguous_links") == []


def test_full_path_link_resolves_before_suffix_matching(tmp_path: Path) -> None:
    """#810: an exact vault-relative path wins over a longer path ending the same way."""
    _write(tmp_path, "brain/a/b.md", _note("B"))
    _write(tmp_path, "brain/x/brain/a/b.md", _note("B2"))
    _write(tmp_path, "brain/P1.md", _note("P1", body="See [[brain/a/b]]."))
    _write(tmp_path, "brain/P2.md", _note("P2", body="See [[brain/a/b.md]]."))

    report = audit(tmp_path)

    assert _issues(report, "broken_links") == []
    assert _issues(report, "ambiguous_links") == []


def test_path_suffix_matching_two_notes_lists_both(tmp_path: Path) -> None:
    """#810: an ambiguous suffix reports every candidate, not just the first."""
    _write(tmp_path, "brain/a/x/N.md", _note("N1"))
    _write(tmp_path, "brain/b/x/N.md", _note("N2"))
    _write(tmp_path, "brain/Pattern.md", _note("Pattern", body="See [[x/N]]."))

    report = audit(tmp_path)

    ambiguous = _issues(report, "ambiguous_links")
    assert len(ambiguous) == 1
    assert "brain/a/x/N.md" in ambiguous[0]
    assert "brain/b/x/N.md" in ambiguous[0]


def _alias_note(title: str, extra_fm: str) -> str:
    return (
        "---\ndate: 2026-07-08\ndescription: \"" + title + "\"\ntags:\n  - reference\n"
        + extra_fm + "---\n\n# " + title + "\n\nBody.\n"
    )


def test_exact_stem_beats_normalized_equal_stem(tmp_path: Path) -> None:
    """#810: titles that normalize equal still resolve to the exactly named file."""
    _write(tmp_path, "brain/Foo-Bar.md", _note("FB1"))
    _write(tmp_path, "brain/FooBar.md", _note("FB2"))
    _write(tmp_path, "brain/Pattern.md", _note("Pattern", body="See [[Foo-Bar]]."))

    report = audit(tmp_path)

    assert _issues(report, "broken_links") == []
    assert _issues(report, "ambiguous_links") == []


def test_exact_alias_beats_normalized_equal_stem(tmp_path: Path) -> None:
    """#810: an exact alias resolves even when another stem normalizes equal."""
    _write(tmp_path, "brain/FooBar.md", _note("FB1"))
    _write(tmp_path, "brain/Other.md", _alias_note("Other", "aliases:\n  - \"Foo Bar\"\n"))
    _write(tmp_path, "brain/Pattern.md", _note("Pattern", body="See [[Foo Bar]]."))

    report = audit(tmp_path)

    assert _issues(report, "broken_links") == []
    assert _issues(report, "ambiguous_links") == []


def test_exact_frontmatter_name_beats_normalized_equal_stem(tmp_path: Path) -> None:
    """#810: an exact frontmatter name resolves despite a normalized-equal stem."""
    _write(tmp_path, "brain/FooBar.md", _note("FB1"))
    _write(tmp_path, "brain/Other.md", _alias_note("Other", "name: Foo Bar\n"))
    _write(tmp_path, "brain/Pattern.md", _note("Pattern", body="See [[Foo Bar]]."))

    report = audit(tmp_path)

    assert _issues(report, "broken_links") == []
    assert _issues(report, "ambiguous_links") == []


def test_name_equal_to_alias_is_not_ambiguous(tmp_path: Path) -> None:
    """#725: one note listing the same string as name and alias is a single target."""
    _write(tmp_path, "brain/Thing.md", _alias_note("Thing", "name: Foo\naliases:\n  - Foo\n  - Foo\n"))
    _write(tmp_path, "brain/Pattern.md", _note("Pattern", body="See [[Foo]]."))

    report = audit(tmp_path)

    assert _issues(report, "ambiguous_links") == []
    assert _issues(report, "broken_links") == []


def test_audit_ignores_wikilinks_inside_indented_fences(tmp_path: Path) -> None:
    """#730: an indented fence still hides its example links."""
    body = "- item\n\n  ```\n  [[ghost one]]\n  ```\n\n  ~~~\n  [[ghost two]]\n  ~~~\n"
    _write(tmp_path, "brain/Pattern.md", _note("Pattern", body=body))

    report = audit(tmp_path)

    assert _issues(report, "broken_links") == []


def test_note_and_base_sharing_a_stem_make_a_bare_link_ambiguous(tmp_path: Path) -> None:
    """#810: the extensionless stem is indexed, so a bare name sees both files."""
    _write(tmp_path, "brain/Foo.md", _note("Foo"))
    _write(tmp_path, "bases/Foo.base", "filters: {}\n")
    _write(tmp_path, "brain/Pattern.md", _note("Pattern", body="See [[Foo]]."))

    report = audit(tmp_path)

    ambiguous = _issues(report, "ambiguous_links")
    assert len(ambiguous) == 1
    assert "brain/Foo.md" in ambiguous[0]
    assert "bases/Foo.base" in ambiguous[0]

