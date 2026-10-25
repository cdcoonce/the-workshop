"""Tests for ledger_rollover: quarterly rollover of Key Decisions and the Brag Doc (#1303)."""

from __future__ import annotations

import sys
from datetime import date
from pathlib import Path

import pytest

ENGINE_DIR = Path(__file__).resolve().parent.parent / "engine"
sys.path.insert(0, str(ENGINE_DIR))

import ledger_rollover as lr  # noqa: E402
import vault_utils  # noqa: E402

KD = "brain/Key Decisions.md"
BRAG = "perf/Brag Doc.md"
KD_Q2 = "brain/archive/key-decisions/2026-Q2.md"
KD_Q3 = "brain/archive/key-decisions/2026-Q3.md"
KD_Q1 = "brain/archive/key-decisions/2026-Q1.md"
BRAG_Q2 = "perf/archive/brag-2026-Q2.md"
BRAG_Q3 = "perf/archive/brag-2026-Q3.md"
TODAY = date(2026, 10, 24)  # Q4 2026; the quarter starts 2026-10-01

KD_HEAD = (
    "---\ndate: 2026-01-01\ndescription: \"Decisions.\"\ntags:\n  - brain\n---\n"
    "# Key Decisions\n\nIntro paragraph with [[Constitution]].\n\n"
    "## Recent\n\nRule paragraph: newest first.\n\n"
)


def _kd_entry(day: str, title: str, body: str = "Body text.") -> str:
    return f"### {day} (context) - {title}\n\n{body}\n\n"


# Newest first, spanning Q1..Q4 with boundary days.
KD_ENTRIES = [
    _kd_entry("2026-10-24", "today"),
    _kd_entry("2026-10-01", "first day of the current quarter"),
    _kd_entry("2026-09-30", "last day of Q3"),
    _kd_entry("2026-07-01", "first day of Q3", "Body with `code`.\n\n#### nested heading\n\nmore."),
    _kd_entry("2026-06-30", "last day of Q2"),
    _kd_entry("2026-04-01", "first day of Q2"),
    _kd_entry("2026-03-31", "last day of Q1"),
    _kd_entry("2026-01-02", "early Q1"),
]
KD_TEXT = KD_HEAD + "".join(KD_ENTRIES)


def _brag_section(label: str, bullets: list[str]) -> str:
    body = "".join(f"- **{b} (ctx) win**\n  - nested detail\n" for b in bullets)
    return f"## {label}\n\n### Wins\n\n{body}\n### Impact\n\n- impact\n\n### Growth\n\n- **2026-01-05 (x) old**\n- **2026-01-06 (x) newer**\n\n"


BRAG_HEAD = "---\ndate: 2026-01-01\ndescription: \"Brag.\"\ntags:\n  - brag-doc\n---\n# Brag Doc\n\nIntro [[Constitution]].\n\n"
BRAG_Q4 = _brag_section("Q4 2026", ["2026-10-20", "2026-10-02"])
BRAG_Q3_SEC = _brag_section("Q3 2026", ["2026-09-30", "2026-07-01"])
BRAG_Q2_SEC = _brag_section("Q2 2026", ["2026-06-30"])
BRAG_TEXT = BRAG_HEAD + BRAG_Q4 + BRAG_Q3_SEC + BRAG_Q2_SEC


def _entry_chunks(text: str) -> list[str]:
    """Entry texts as the grammar sees them: start line to the next entry start or run end."""
    lines = lr.split_keepends(text)
    plain = [l.rstrip("\r\n") for l in lines]
    out: list[str] = []
    for _anchor, entries in vault_utils.entry_runs(plain):
        idxs = [i for i, _d in entries]
        for k, i in enumerate(idxs):
            end = idxs[k + 1] if k + 1 < len(idxs) else len(lines)
            out.append("".join(lines[i:end]))
    return out


# ---------------------------------------------------------------------------
# quarter arithmetic
# ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    "day,expected",
    [
        (date(2026, 1, 1), date(2026, 1, 1)),
        (date(2026, 3, 31), date(2026, 1, 1)),
        (date(2026, 4, 1), date(2026, 4, 1)),
        (date(2026, 6, 30), date(2026, 4, 1)),
        (date(2026, 7, 1), date(2026, 7, 1)),
        (date(2026, 12, 31), date(2026, 10, 1)),
    ],
)
def test_quarter_start_is_first_day_of_calendar_quarter(day: date, expected: date) -> None:
    assert lr.quarter_start(day) == expected


@pytest.mark.parametrize(
    "day,label",
    [
        (date(2026, 3, 31), "2026-Q1"),
        (date(2026, 4, 1), "2026-Q2"),
        (date(2026, 6, 30), "2026-Q2"),
        (date(2026, 7, 1), "2026-Q3"),
        (date(2026, 10, 1), "2026-Q4"),
    ],
)
def test_quarter_label_buckets_boundary_days(day: date, label: str) -> None:
    assert lr.quarter_label(day) == label


# ---------------------------------------------------------------------------
# Key Decisions
# ---------------------------------------------------------------------------


def test_key_decisions_entries_land_in_their_own_quarter_file() -> None:
    plan = lr.plan_rollover({KD: KD_TEXT}, TODAY)
    assert set(plan.files) == {KD, KD_Q1, KD_Q2, KD_Q3}
    q3 = _entry_chunks(plan.files[KD_Q3])
    q2 = _entry_chunks(plan.files[KD_Q2])
    q1 = _entry_chunks(plan.files[KD_Q1])
    assert [c.splitlines()[0][:14] for c in q3][:2] == ["### 2026-09-30", "### 2026-07-01"]
    assert [c.splitlines()[0][:14] for c in q2] == ["### 2026-06-30", "### 2026-04-01"]
    assert [c.splitlines()[0][:14] for c in q1] == ["### 2026-03-31", "### 2026-01-02"]


def test_key_decisions_boundary_days_bucket_by_calendar_quarter() -> None:
    plan = lr.plan_rollover({KD: KD_TEXT}, TODAY)
    assert "### 2026-04-01" in plan.files[KD_Q2] and "### 2026-04-01" not in plan.files[KD_Q1]
    assert "### 2026-03-31" in plan.files[KD_Q1] and "### 2026-03-31" not in plan.files[KD_Q2]
    assert "### 2026-07-01" in plan.files[KD_Q3] and "### 2026-07-01" not in plan.files[KD_Q2]
    assert "### 2026-06-30" in plan.files[KD_Q2] and "### 2026-06-30" not in plan.files[KD_Q3]


def test_key_decisions_entry_dated_first_day_of_current_quarter_stays_live() -> None:
    plan = lr.plan_rollover({KD: KD_TEXT}, TODAY)
    live = plan.files[KD]
    assert "### 2026-10-01 (context) - first day of the current quarter" in live
    assert "### 2026-10-24" in live
    assert "### 2026-09-30" not in live


def test_key_decisions_conservation_is_byte_for_byte() -> None:
    before = _entry_chunks(KD_TEXT)
    plan = lr.plan_rollover({KD: KD_TEXT}, TODAY)
    after: list[str] = []
    for path in (KD, KD_Q3, KD_Q2, KD_Q1):
        after.extend(_entry_chunks(plan.files[path]))
    assert sorted(after) == sorted(before)
    assert len(after) == len(before)


def test_key_decisions_conservation_keeps_whitespace_blank_runs_and_unterminated_tail() -> None:
    # Trailing spaces and tabs, a double blank line inside an entry, and a last
    # entry with no final newline must all survive the move byte for byte.
    entries = [
        _kd_entry("2026-10-24", "today"),
        "### 2026-09-30 (ctx) - spaced   \n\nline with trailing spaces   \nline with tab\t\n\n\nafter a double blank line  \n\n",
        "### 2026-06-30 (ctx) - mid\n\nbody\t \n\n",
        "### 2026-01-02 (ctx) - tail  \t\n\nlast line, no final newline  \t",
    ]
    text = KD_HEAD + "".join(entries)
    before = _entry_chunks(text)
    plan = lr.plan_rollover({KD: text}, TODAY)
    after: list[str] = []
    for path in (KD, KD_Q3, KD_Q2, KD_Q1):
        after.extend(_entry_chunks(plan.files[path]))
    assert sorted(after) == sorted(before)
    assert entries[1] in plan.files[KD_Q3]
    assert plan.files[KD_Q1].endswith("last line, no final newline  \t")


def test_key_decisions_keeps_recent_heading_and_rule_paragraph() -> None:
    plan = lr.plan_rollover({KD: KD_TEXT}, TODAY)
    live = plan.files[KD]
    assert live.startswith(KD_HEAD.split("## Recent")[0])
    assert "## Recent\n\nRule paragraph: newest first.\n\n" in live
    assert live.count("## Recent") == 1


def test_key_decisions_live_file_keeps_original_order_of_remaining_entries() -> None:
    plan = lr.plan_rollover({KD: KD_TEXT}, TODAY)
    assert _entry_chunks(plan.files[KD]) == KD_ENTRIES[:2]


def test_key_decisions_second_run_changes_nothing() -> None:
    first = lr.plan_rollover({KD: KD_TEXT}, TODAY)
    files = {path: text for path, text in first.files.items()}
    second = lr.plan_rollover(files, TODAY)
    assert second.files == {}
    assert second.moved == {}


def test_key_decisions_second_run_with_existing_archive_changes_nothing() -> None:
    existing = (
        "---\ndate: 2026-07-05\ndescription: \"x\"\ntags:\n  - key-decisions-archive\n---\n"
        "# Key Decisions 2026-Q3\n\nBack to [[Key Decisions]].\n\n" + KD_ENTRIES[2]
    )
    first = lr.plan_rollover({KD: KD_TEXT, KD_Q3: existing}, TODAY)
    # Finished state: feed every output file back (plus the untouched archive).
    settled = {KD_Q3: existing, **first.files}
    again = lr.plan_rollover(settled, TODAY)
    assert again.files == {}
    assert again.moved == {}
    # Half-finished state: the archives were written but the live file was not.
    # The re-run must drop the entries from live without archiving them twice.
    half = {path: text for path, text in first.files.items() if path != KD}
    half[KD] = KD_TEXT
    rerun = lr.plan_rollover(half, TODAY)
    for path in (KD_Q3, KD_Q2, KD_Q1):
        assert rerun.files.get(path, first.files[path]) == first.files[path]
        assert rerun.files.get(path, first.files[path]).count("### 2026-09-30") <= 1
    assert rerun.files[KD] == first.files[KD]


def test_nothing_to_move_changes_nothing() -> None:
    text = KD_HEAD + KD_ENTRIES[0] + KD_ENTRIES[1]
    plan = lr.plan_rollover({KD: text, BRAG: BRAG_HEAD + BRAG_Q4}, TODAY)
    assert plan.files == {}
    assert plan.moved == {}


def test_missing_live_files_change_nothing() -> None:
    assert lr.plan_rollover({}, TODAY).files == {}


def test_key_decisions_append_into_existing_archive_stays_newest_first() -> None:
    existing = (
        "---\ndate: 2026-07-05\ndescription: \"x\"\ntags:\n  - key-decisions-archive\n---\n"
        "# Key Decisions 2026-Q3\n\nBack to [[Key Decisions]].\n\n"
        + _kd_entry("2026-09-15", "mid")
        + _kd_entry("2026-07-02", "old")
    )
    plan = lr.plan_rollover({KD: KD_TEXT, KD_Q3: existing}, TODAY)
    days = [c.splitlines()[0][4:14] for c in _entry_chunks(plan.files[KD_Q3])]
    assert days == ["2026-09-30", "2026-09-15", "2026-07-02", "2026-07-01"]
    assert plan.files[KD_Q3].startswith(existing.split("### 2026-09-15")[0])


def test_key_decisions_archive_entry_already_present_is_not_duplicated() -> None:
    existing = (
        "---\ndate: 2026-07-05\ndescription: \"x\"\ntags:\n  - key-decisions-archive\n---\n"
        "# Key Decisions 2026-Q3\n\nBack to [[Key Decisions]].\n\n" + KD_ENTRIES[2]
    )
    plan = lr.plan_rollover({KD: KD_TEXT, KD_Q3: existing}, TODAY)
    assert plan.files[KD_Q3].count("### 2026-09-30") == 1
    assert "### 2026-09-30" not in plan.files[KD]


def test_key_decisions_archive_has_frontmatter_and_back_link() -> None:
    plan = lr.plan_rollover({KD: KD_TEXT}, TODAY)
    text = plan.files[KD_Q3]
    assert text.startswith("---\n")
    front, _, body = text[4:].partition("\n---\n")
    assert "date: 2026-10-24" in front
    assert "description:" in front
    assert "tags:" in front and "key-decisions-archive" in front
    assert body.count("[[Key Decisions]]") == 1


def test_key_decisions_live_archive_list_links_every_archive_file() -> None:
    existing = "---\ndate: 2026-01-05\ndescription: \"x\"\ntags:\n  - t\n---\n# old\n"
    old = "brain/archive/key-decisions/2025-Q4.md"
    plan = lr.plan_rollover({KD: KD_TEXT, old: existing}, TODAY)
    live = plan.files[KD]
    assert "## Archive" in live
    section = live.split("## Archive")[1].split("\n## ")[0]
    for path in (KD_Q3, KD_Q2, KD_Q1, old):
        assert f"[[{path[:-3]}]]" in section
    # newest first
    assert section.index("2026-Q3") < section.index("2026-Q2") < section.index("2026-Q1") < section.index("2025-Q4")
    assert live.index("## Archive") < live.index("## Recent")


def test_key_decisions_existing_archive_section_is_rebuilt_not_duplicated() -> None:
    with_section = KD_TEXT.replace("## Recent", "## Archive\n\n- [[brain/archive/key-decisions/2026-Q1]]\n\n## Recent", 1)
    plan = lr.plan_rollover({KD: with_section}, TODAY)
    assert plan.files[KD].count("## Archive") == 1
    assert plan.files[KD].count("[[brain/archive/key-decisions/2026-Q1]]") == 1


def test_dated_heading_inside_a_code_fence_is_not_moved() -> None:
    fenced = _kd_entry("2026-01-02", "has fence", "```\n### 2025-01-01 (x) - fake\n```")
    plan = lr.plan_rollover({KD: KD_HEAD + KD_ENTRIES[0] + fenced}, TODAY)
    assert plan.files[KD_Q1].count("### 2025-01-01") == 1
    assert "2025-Q1" not in "".join(plan.files)


def test_entries_outside_recent_are_left_alone() -> None:
    text = KD_HEAD + KD_ENTRIES[0] + "## Elsewhere\n\n" + _kd_entry("2026-01-02", "not under recent")
    assert lr.plan_rollover({KD: text}, TODAY).files == {}


# ---------------------------------------------------------------------------
# Brag Doc
# ---------------------------------------------------------------------------


def test_brag_whole_quarter_sections_move_to_their_own_archive() -> None:
    plan = lr.plan_rollover({BRAG: BRAG_TEXT}, TODAY)
    assert set(plan.files) == {BRAG, BRAG_Q3, BRAG_Q2}
    assert BRAG_Q3_SEC in plan.files[BRAG_Q3]
    assert BRAG_Q2_SEC in plan.files[BRAG_Q2]
    assert "## Q2 2026" not in plan.files[BRAG_Q3]


def test_brag_current_quarter_section_stays_live_with_growth_order_intact() -> None:
    plan = lr.plan_rollover({BRAG: BRAG_TEXT}, TODAY)
    live = plan.files[BRAG]
    assert BRAG_Q4 in live
    assert "## Q3 2026" not in live and "## Q2 2026" not in live
    # Growth stays oldest-first inside the moved section: no reordering.
    assert "- **2026-01-05 (x) old**\n- **2026-01-06 (x) newer**" in plan.files[BRAG_Q3]


def test_brag_conservation_live_plus_archives_hold_every_section_byte_for_byte() -> None:
    plan = lr.plan_rollover({BRAG: BRAG_TEXT}, TODAY)
    body = [
        plan.files[BRAG].split("# Brag Doc")[1],
        plan.files[BRAG_Q3],
        plan.files[BRAG_Q2],
    ]
    joined = "".join(body)
    for section in (BRAG_Q4, BRAG_Q3_SEC, BRAG_Q2_SEC):
        assert joined.count(section) == 1
    bullets = [l for l in BRAG_TEXT.splitlines() if l.startswith("- **")]
    got = [l for part in body for l in part.splitlines() if l.startswith("- **")]
    assert sorted(got) == sorted(bullets)


def test_brag_archive_is_tagged_brag_doc_archive_not_brag_doc_and_links_back() -> None:
    plan = lr.plan_rollover({BRAG: BRAG_TEXT}, TODAY)
    text = plan.files[BRAG_Q3]
    front, _, body = text[4:].partition("\n---\n")
    assert "brag-doc-archive" in front
    assert "  - brag-doc\n" not in front + "\n"
    assert "date: 2026-10-24" in front and "description:" in front
    assert body.count("[[Brag Doc]]") == 1


def test_brag_live_archive_list_links_every_archive_file() -> None:
    plan = lr.plan_rollover({BRAG: BRAG_TEXT}, TODAY)
    live = plan.files[BRAG]
    section = live.split("## Archive")[1].split("\n## ")[0]
    assert "[[perf/archive/brag-2026-Q3]]" in section
    assert "[[perf/archive/brag-2026-Q2]]" in section
    assert section.index("Q3") < section.index("Q2")
    assert live.index("## Archive") < live.index("## Q4 2026")


def test_brag_second_run_changes_nothing() -> None:
    first = lr.plan_rollover({BRAG: BRAG_TEXT}, TODAY)
    second = lr.plan_rollover(dict(first.files), TODAY)
    assert second.files == {}


def test_brag_second_run_with_existing_archive_changes_nothing() -> None:
    seeded = lr.plan_rollover({BRAG: BRAG_TEXT}, TODAY)
    existing = {BRAG_Q3: seeded.files[BRAG_Q3]}
    first = lr.plan_rollover({BRAG: BRAG_TEXT, **existing}, TODAY)
    assert lr.plan_rollover({**existing, **first.files}, TODAY).files == {}
    # Half-finished: archives written, live file not. The re-run drops the
    # already-archived sections from live and leaves the archives alone.
    half = {**existing, **{p: t for p, t in first.files.items() if p != BRAG}, BRAG: BRAG_TEXT}
    rerun = lr.plan_rollover(half, TODAY)
    assert rerun.skipped == []
    assert rerun.files[BRAG] == first.files[BRAG]
    assert BRAG_Q3 not in rerun.files and BRAG_Q2 not in rerun.files


def test_brag_section_for_an_already_archived_quarter_is_not_clobbered() -> None:
    first = lr.plan_rollover({BRAG: BRAG_TEXT}, TODAY)
    changed_section = BRAG_Q3_SEC.replace("nested detail", "other detail")
    live = first.files[BRAG].replace("## Q4 2026", changed_section + "## Q4 2026", 1)
    plan = lr.plan_rollover({BRAG: live, BRAG_Q3: first.files[BRAG_Q3]}, TODAY)
    assert BRAG_Q3 not in plan.files
    assert "## Q3 2026" in plan.files.get(BRAG, live)
    assert plan.skipped == [BRAG_Q3]


def test_brag_future_quarter_section_is_not_moved() -> None:
    text = BRAG_HEAD + _brag_section("Q1 2027", ["2027-01-02"]) + BRAG_Q4
    assert lr.plan_rollover({BRAG: text}, TODAY).files == {}


def test_brag_fenced_quarter_heading_is_not_a_section() -> None:
    text = BRAG_HEAD + BRAG_Q4 + "```\n## Q1 2020\n```\n"
    assert lr.plan_rollover({BRAG: text}, TODAY).files == {}


# ---------------------------------------------------------------------------
# Filesystem wrapper and CLI
# ---------------------------------------------------------------------------


def _vault(tmp_path: Path) -> Path:
    (tmp_path / "brain").mkdir()
    (tmp_path / "perf").mkdir()
    (tmp_path / KD).write_text(KD_TEXT, encoding="utf-8", newline="")
    (tmp_path / BRAG).write_text(BRAG_TEXT, encoding="utf-8", newline="")
    return tmp_path


def test_rollover_ledgers_is_dry_by_default(tmp_path: Path) -> None:
    root = _vault(tmp_path)
    result = lr.rollover_ledgers(root, today=TODAY)
    assert result["applied"] is False
    assert result["moved"][KD_Q3] == 2
    assert result["moved"][BRAG_Q3] == 1
    assert (root / KD).read_text(encoding="utf-8") == KD_TEXT
    assert not (root / "brain" / "archive").exists()


def test_rollover_ledgers_apply_writes_files_and_is_idempotent(tmp_path: Path) -> None:
    root = _vault(tmp_path)
    result = lr.rollover_ledgers(root, today=TODAY, apply=True)
    assert result["applied"] is True
    assert (root / KD_Q2).is_file() and (root / BRAG_Q3).is_file()
    snapshot = {p: p.read_bytes() for p in root.rglob("*.md")}
    again = lr.rollover_ledgers(root, today=TODAY, apply=True)
    assert again["moved"] == {} and again["written"] == []
    assert {p: p.read_bytes() for p in root.rglob("*.md")} == snapshot


def test_rollover_ledgers_preserves_crlf_bytes(tmp_path: Path) -> None:
    root = tmp_path
    (root / "brain").mkdir()
    crlf = KD_TEXT.replace("\n", "\r\n")
    (root / KD).write_bytes(crlf.encode())
    lr.rollover_ledgers(root, today=TODAY, apply=True)
    moved = (root / KD_Q3).read_bytes()
    assert b"### 2026-09-30 (context) - last day of Q3\r\n" in moved


def test_cli_dry_run_prints_counts_and_writes_nothing(tmp_path: Path, capsys) -> None:
    root = _vault(tmp_path)
    rc = lr.main(["rollover", "--vault-root", str(root), "--today", "2026-10-24"])
    out = capsys.readouterr().out
    assert rc == 0
    assert "dry run" in out
    assert f"{KD_Q3}: 2" in out and f"{BRAG_Q3}: 1" in out
    assert not (root / "brain" / "archive").exists()


def test_cli_apply_writes(tmp_path: Path, capsys) -> None:
    root = _vault(tmp_path)
    rc = lr.main(["rollover", "--vault-root", str(root), "--today", "2026-10-24", "--apply"])
    assert rc == 0
    assert (root / KD_Q3).is_file()
    assert "applied" in capsys.readouterr().out


@pytest.mark.parametrize("kind", ["missing", "file"])
def test_cli_rejects_a_vault_root_that_is_not_a_directory(tmp_path: Path, capsys, kind: str) -> None:
    root = tmp_path / "nope"
    if kind == "file":
        root.write_text("x", encoding="utf-8")
    rc = lr.main(["rollover", "--vault-root", str(root), "--today", "2026-10-24"])
    captured = capsys.readouterr()
    assert rc != 0
    assert "nothing to move" not in captured.out
    assert str(root) in captured.err and "not a directory" in captured.err
