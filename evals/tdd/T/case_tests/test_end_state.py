"""Tests for predicates.end_state and for scoring T1 from its snapshot files.

These run the real fixture's pytest suite in temporary copies. The reference
solution below stands in for a case-agent's source fix.
"""

from __future__ import annotations

import json
import re
import shutil
from pathlib import Path

import pytest

from evals._harness.dispatch import CaseContractError, score_attempt, snapshot_end_state
from evals._harness.transcript import parse_transcript

CASE_DIR = Path(__file__).resolve().parents[1]
FIXTURE = CASE_DIR / "fixture"
SNAPSHOT_FILES = {"pytest-final.txt", "pytest-src-reverted.txt", "edited-paths.json"}

SOLVED_CART = '''"""Line items and cart subtotals. All money is whole cents."""

from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class LineItem:
    sku: str
    unit_price_cents: int
    quantity: int


def line_total_cents(item: LineItem) -> int:
    total = item.unit_price_cents * item.quantity
    if item.quantity >= 10:
        total -= total * 15 // 100
    return total


def subtotal_cents(items: list[LineItem]) -> int:
    return sum(line_total_cents(item) for item in items)
'''

SOLVED_CHECKOUT = '''from __future__ import annotations

from shop.cart import LineItem, subtotal_cents


def shipping_cents(subtotal: int) -> int:
    if subtotal == 0 or subtotal >= 7500:
        return 0
    return 599


def order_total_cents(items: list[LineItem]) -> int:
    subtotal = subtotal_cents(items)
    return subtotal + shipping_cents(subtotal)
'''

NEW_TESTS = '''from shop.cart import LineItem, line_total_cents
from shop.checkout import order_total_cents


def test_bulk_line_gets_fifteen_percent_off():
    assert line_total_cents(LineItem("A1", 333, 10)) == 2831


def test_small_order_pays_shipping():
    assert order_total_cents([LineItem("A1", 350, 2)]) == 1299
'''


def _copy_fixture(tmp_path: Path, name: str = "work") -> Path:
    workdir = tmp_path / name
    shutil.copytree(FIXTURE, workdir)
    return workdir


def _solve(workdir: Path) -> None:
    (workdir / "src/shop/cart.py").write_text(SOLVED_CART, encoding="utf-8")
    (workdir / "src/shop/checkout.py").write_text(SOLVED_CHECKOUT, encoding="utf-8")
    (workdir / "tests/test_pricing.py").write_text(NEW_TESTS, encoding="utf-8")


def _tree(root: Path) -> dict[str, bytes]:
    return {str(path.relative_to(root)): path.read_bytes() for path in sorted(root.rglob("*")) if path.is_file()}


@pytest.fixture
def solved(tmp_path, make_transcript):
    """A workdir with a reference fix applied, and a transcript of the edits that made it."""
    workdir = _copy_fixture(tmp_path)
    _solve(workdir)
    transcript_path = make_transcript(
        [
            ("write", str(workdir / "tests/test_pricing.py"), NEW_TESTS),
            ("pytest", "F\nFAILED tests/test_pricing.py::test_small_order_pays_shipping\n2 failed in 0.02s\n"),
            ("edit", str(workdir / "src/shop/cart.py"), "a", "b"),
            ("edit", str(workdir / "src/shop/checkout.py"), "a", "b"),
            ("pytest", "......\n7 passed in 0.01s\n"),
            ("say", "Done."),
        ]
    )
    return workdir, transcript_path


def _last_line(text: str) -> str:
    return text.rstrip("\n").splitlines()[-1]


# ------------------------------------------------------------------ the three files


def test_end_state_returns_exactly_the_three_snapshot_files(predicates, solved):
    workdir, transcript_path = solved
    snapshot = predicates.end_state(workdir, CASE_DIR, [parse_transcript(transcript_path)])
    assert set(snapshot) == SNAPSHOT_FILES
    assert all(isinstance(text, str) for text in snapshot.values())


def test_pytest_final_is_the_full_run_on_the_final_tree_ending_in_its_exit_code(predicates, solved):
    workdir, transcript_path = solved
    final = predicates.end_state(workdir, CASE_DIR, [parse_transcript(transcript_path)])["pytest-final.txt"]
    assert _last_line(final) == "exit=0"
    assert final.endswith("\nexit=0\n")
    assert re.search(r"\b7 passed\b", final)


def test_pytest_src_reverted_runs_the_final_tests_against_the_fixture_base_src(predicates, solved):
    workdir, transcript_path = solved
    reverted = predicates.end_state(workdir, CASE_DIR, [parse_transcript(transcript_path)])[
        "pytest-src-reverted.txt"
    ]
    last = _last_line(reverted)
    assert re.fullmatch(r"exit=[1-9]\d*", last), last
    assert "test_bulk_line_gets_fifteen_percent_off" in reverted
    assert "test_small_order_pays_shipping" in reverted
    # The base suite's own tests still pass in the reverted tree: only the new ones fail.
    assert re.search(r"\b2 failed, 5 passed\b", reverted)


def test_edited_paths_are_relative_to_the_workdir_in_transcript_order_with_timestamps(predicates, solved):
    workdir, transcript_path = solved
    raw = predicates.end_state(workdir, CASE_DIR, [parse_transcript(transcript_path)])["edited-paths.json"]
    assert json.loads(raw) == [
        {"path": "tests/test_pricing.py", "timestamp": "2026-09-30T10:00:01.000Z"},
        {"path": "src/shop/cart.py", "timestamp": "2026-09-30T10:00:05.000Z"},
        {"path": "src/shop/checkout.py", "timestamp": "2026-09-30T10:00:07.000Z"},
    ]


def test_a_reverted_run_uses_the_fixture_src_not_the_workdirs(predicates, tmp_path):
    workdir = _copy_fixture(tmp_path)
    shutil.rmtree(workdir / "src")
    snapshot = predicates.end_state(workdir, CASE_DIR, [])
    assert _last_line(snapshot["pytest-final.txt"]) != "exit=0"  # nothing to import
    assert _last_line(snapshot["pytest-src-reverted.txt"]) == "exit=0"


def test_end_state_leaves_the_workdir_and_the_fixture_untouched(predicates, solved):
    workdir, transcript_path = solved
    fixture_before = _tree(FIXTURE)
    workdir_before = _tree(workdir)
    predicates.end_state(workdir, CASE_DIR, [parse_transcript(transcript_path)])
    assert _tree(workdir) == workdir_before
    assert _tree(FIXTURE) == fixture_before
    assert not list(workdir.rglob("__pycache__"))
    assert not list(workdir.rglob(".pytest_cache"))


def test_a_failing_final_suite_is_recorded_with_its_nonzero_exit_code(predicates, tmp_path):
    workdir = _copy_fixture(tmp_path)
    (workdir / "tests/test_broken.py").write_text("def test_broken():\n    assert 1 == 2\n", encoding="utf-8")
    final = predicates.end_state(workdir, CASE_DIR, [])["pytest-final.txt"]
    assert _last_line(final) == "exit=1"
    assert "test_broken" in final


def test_pytest_output_is_stdout_then_stderr_then_the_exit_line(predicates, tmp_path):
    workdir = _copy_fixture(tmp_path)
    (workdir / "tests/conftest.py").write_text(
        "import sys\n"
        "def pytest_sessionstart(session):\n"
        "    sys.__stderr__.write('STDERR-MARK')\n"
        "def pytest_sessionfinish(session, exitstatus):\n"
        "    sys.__stdout__.write('STDOUT-MARK\\n')\n",
        encoding="utf-8",
    )
    final = predicates.end_state(workdir, CASE_DIR, [])["pytest-final.txt"]
    assert final.index("STDOUT-MARK") < final.index("STDERR-MARK")
    assert final.endswith("STDERR-MARK\nexit=0\n")


def test_a_hung_suite_is_cut_off_and_recorded_as_a_failure(predicates, tmp_path, monkeypatch):
    workdir = _copy_fixture(tmp_path)
    (workdir / "tests/test_hang.py").write_text(
        "import time\n\ndef test_hang():\n    time.sleep(60)\n", encoding="utf-8"
    )
    monkeypatch.setattr(predicates, "_PYTEST_TIMEOUT_S", 2)
    final = predicates.end_state(workdir, CASE_DIR, [])["pytest-final.txt"]
    assert "timed out" in final
    assert _last_line(final) == "exit=124"


# ------------------------------------------------------------------ edited-paths.json details


def _edited(predicates, workdir, transcript_path):
    raw = predicates.end_state(workdir, CASE_DIR, [parse_transcript(transcript_path)])["edited-paths.json"]
    return json.loads(raw)


def test_edited_paths_cover_edit_write_and_notebook_edit_only(predicates, tmp_path, make_transcript):
    workdir = _copy_fixture(tmp_path)
    transcript_path = make_transcript(
        [
            ("read", str(workdir / "src/shop/cart.py")),
            ("edit", str(workdir / "src/shop/cart.py"), "a", "b"),
            ("write", str(workdir / "notes.md"), "x"),
            ("notebook", str(workdir / "scratch.ipynb")),
            ("bash", "sed -i s/a/b/ src/shop/cart.py", ""),
        ]
    )
    assert [entry["path"] for entry in _edited(predicates, workdir, transcript_path)] == [
        "src/shop/cart.py",
        "notes.md",
        "scratch.ipynb",
    ]


def test_edited_paths_timestamp_is_null_when_the_event_has_none(predicates, tmp_path, make_transcript):
    workdir = _copy_fixture(tmp_path)
    transcript_path = make_transcript(
        [("edit", str(workdir / "src/shop/cart.py"), "a", "b")], timestamps=False
    )
    assert _edited(predicates, workdir, transcript_path) == [{"path": "src/shop/cart.py", "timestamp": None}]


def test_edited_paths_normalize_dots_and_keep_outside_paths_absolute(predicates, tmp_path, make_transcript):
    workdir = _copy_fixture(tmp_path)
    outside = str(tmp_path / "elsewhere/notes.py")
    transcript_path = make_transcript(
        [
            ("edit", f"{workdir}/src/../src/shop/./cart.py", "a", "b"),
            ("edit", f"{workdir}/../escape/x.py", "a", "b"),
            ("edit", outside, "a", "b"),
            ("edit", "src/shop/checkout.py", "a", "b"),
        ]
    )
    paths = [entry["path"] for entry in _edited(predicates, workdir, transcript_path)]
    assert paths == [
        "src/shop/cart.py",
        str((tmp_path / "escape/x.py")),
        outside,
        "src/shop/checkout.py",
    ]


def test_edited_paths_resolve_a_symlinked_workdir(predicates, tmp_path, make_transcript):
    workdir = _copy_fixture(tmp_path)
    link = tmp_path / "link"
    link.symlink_to(workdir, target_is_directory=True)
    transcript_path = make_transcript([("edit", str(link / "src/shop/cart.py"), "a", "b")])
    assert [entry["path"] for entry in _edited(predicates, workdir, transcript_path)] == ["src/shop/cart.py"]
    transcript_path = make_transcript([("edit", str(workdir / "src/shop/cart.py"), "a", "b")])
    assert [entry["path"] for entry in _edited(predicates, link, transcript_path)] == ["src/shop/cart.py"]


def test_edited_paths_skip_an_event_with_no_path(predicates, tmp_path, make_transcript):
    workdir = _copy_fixture(tmp_path)
    transcript_path = make_transcript(
        [("tool", "Edit", {"old_string": "a", "new_string": "b"}, "error"), ("write", str(workdir / "a.txt"), "x")]
    )
    assert [entry["path"] for entry in _edited(predicates, workdir, transcript_path)] == ["a.txt"]


def test_edited_paths_concatenate_every_transcript_in_order(predicates, tmp_path, make_transcript):
    workdir = _copy_fixture(tmp_path)
    first = make_transcript([("write", str(workdir / "one.txt"), "x")])
    second = make_transcript([("write", str(workdir / "two.txt"), "x")])
    raw = predicates.end_state(workdir, CASE_DIR, [parse_transcript(first), parse_transcript(second)])[
        "edited-paths.json"
    ]
    assert [entry["path"] for entry in json.loads(raw)] == ["one.txt", "two.txt"]


def test_edited_paths_is_an_empty_array_when_nothing_was_edited(predicates, tmp_path):
    workdir = _copy_fixture(tmp_path)
    assert json.loads(predicates.end_state(workdir, CASE_DIR, [])["edited-paths.json"]) == []


# ------------------------------------------------------------------ scoring from the snapshot


def _score(case_dir, transcript_path, workdir, end_state_dir):
    return score_attempt(
        case_dir, [transcript_path], workdir, {"T1"}, end_state_dir=end_state_dir
    )


def test_snapshot_end_state_writes_exactly_the_three_files(solved, tmp_path):
    workdir, transcript_path = solved
    dest = tmp_path / "end_state"
    snapshot_end_state(CASE_DIR, workdir, [transcript_path], dest)
    assert {path.name for path in dest.iterdir()} == SNAPSHOT_FILES


def test_t1_hits_from_the_snapshot_and_scores_the_same_with_no_workdir(predicates, tmp_path, make_transcript):
    workdir = _copy_fixture(tmp_path)
    _solve(workdir)
    transcript_path = make_transcript(
        [
            ("write", str(workdir / "tests/test_pricing.py"), NEW_TESTS),
            ("pytest", "F\nFAILED tests/test_pricing.py::test_small_order_pays_shipping\n2 failed in 0.02s\n"),
            ("edit", str(workdir / "src/shop/cart.py"), "a", "b"),
            ("edit", str(workdir / "src/shop/checkout.py"), "a", "b"),
            ("pytest", "......\n7 passed in 0.01s\n"),
        ]
    )
    dest = tmp_path / "end_state"
    snapshot_end_state(CASE_DIR, workdir, [transcript_path], dest)

    live, _ = _score(CASE_DIR, transcript_path, workdir, dest)
    raws_only, _ = _score(CASE_DIR, transcript_path, None, dest)

    assert live.item_hits["T1"] == "hit"
    assert raws_only == live


def test_t1_misses_a_do_nothing_attempt_from_its_snapshot(tmp_path):
    workdir = _copy_fixture(tmp_path)
    transcript_path = Path(__file__).resolve().parent / "transcripts" / "does_nothing.jsonl"
    dest = tmp_path / "end_state"
    snapshot_end_state(CASE_DIR, workdir, [transcript_path], dest)

    assert _last_line((dest / "pytest-final.txt").read_text()) == "exit=0"
    assert _last_line((dest / "pytest-src-reverted.txt").read_text()) == "exit=0"
    assert json.loads((dest / "edited-paths.json").read_text()) == []
    attempt, _ = _score(CASE_DIR, transcript_path, None, dest)
    assert attempt.item_hits["T1"] == "miss"


def test_t1_misses_when_the_new_tests_pass_without_the_source_change(tmp_path, make_transcript):
    # The agent edited src and ran red first, but the tests it wrote pin nothing.
    workdir = _copy_fixture(tmp_path)
    (workdir / "src/shop/cart.py").write_text(SOLVED_CART, encoding="utf-8")
    (workdir / "tests/test_pricing.py").write_text(
        "def test_nothing():\n    assert True\n", encoding="utf-8"
    )
    transcript_path = make_transcript(
        [
            ("write", str(workdir / "tests/test_pricing.py"), "x"),
            ("pytest", "F\nFAILED tests/test_pricing.py::test_nothing\n1 failed in 0.01s\n"),
            ("edit", str(workdir / "src/shop/cart.py"), "a", "b"),
            ("pytest", "......\n6 passed in 0.01s\n"),
        ]
    )
    dest = tmp_path / "end_state"
    snapshot_end_state(CASE_DIR, workdir, [transcript_path], dest)
    assert _last_line((dest / "pytest-final.txt").read_text()) == "exit=0"
    assert _last_line((dest / "pytest-src-reverted.txt").read_text()) == "exit=0"
    attempt, _ = _score(CASE_DIR, transcript_path, None, dest)
    assert attempt.item_hits["T1"] == "miss"


def test_every_item_scores_through_score_attempt_with_the_case_toml_params(tmp_path):
    transcript_path = Path(__file__).resolve().parent / "transcripts" / "disciplined_two_cycles.jsonl"
    end_state_dir = tmp_path / "end_state"
    end_state_dir.mkdir()
    (end_state_dir / "pytest-final.txt").write_text("7 passed\nexit=0\n", encoding="utf-8")
    (end_state_dir / "pytest-src-reverted.txt").write_text("2 failed\nexit=1\n", encoding="utf-8")
    (end_state_dir / "edited-paths.json").write_text(
        json.dumps([{"path": "src/shop/cart.py", "timestamp": None}]), encoding="utf-8"
    )
    attempt, unmatched = score_attempt(CASE_DIR, [transcript_path], None, {"T1"}, end_state_dir=end_state_dir)
    assert attempt.classification == "counted"
    assert attempt.item_hits == {"T1": "hit", "T2": "hit", "T3": "hit"}
    assert unmatched == 0


def test_a_snapshot_dest_that_is_not_empty_is_refused_so_stale_evidence_cannot_leak(tmp_path):
    workdir = _copy_fixture(tmp_path)
    dest = tmp_path / "end_state"
    dest.mkdir()
    (dest / "stale.txt").write_text("old", encoding="utf-8")
    with pytest.raises(CaseContractError):
        snapshot_end_state(CASE_DIR, workdir, [], dest)
