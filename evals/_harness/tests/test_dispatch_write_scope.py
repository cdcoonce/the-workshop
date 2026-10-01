"""Write-scope tests for evals._harness.dispatch.

#993 already asserts, per module, that the harness writes only under
``evals/`` and never a file named ``tests.md`` (see
``test_ledger.py::test_write_run_writes_only_under_runs_dir_and_never_a_file_named_tests_md``
and the equivalent in ``test_report.py``). This extends that same assertion
to #995's own write surface rather than duplicating either of those tests:
``build_dispatch_prompt``, ``build_no_skill_prompt``, and ``score_attempt``
are read-only, and ``snapshot_end_state`` writes only under the ``dest`` its
caller supplies.
"""

from __future__ import annotations

import json
from pathlib import Path

from evals._harness.dispatch import (
    build_dispatch_prompt,
    build_no_skill_prompt,
    score_attempt,
    snapshot_end_state,
)


def _files_under(root: Path) -> set[Path]:
    return {path for path in root.rglob("*") if path.is_file()}


def _make_minimal_case(case_dir: Path, *, with_end_state: bool = False) -> None:
    case_dir.mkdir(parents=True)
    (case_dir / "prompt.md").write_text("Investigate the repo.\n", encoding="utf-8")
    (case_dir / "acceptance.md").write_text("private\n", encoding="utf-8")
    predicates = "def always_true(evidence):\n    return True\n"
    if with_end_state:
        predicates += (
            "\n\ndef end_state(workdir, case_dir, transcripts):\n"
            "    return {'note.txt': 'noted'}\n"
        )
    (case_dir / "predicates.py").write_text(predicates, encoding="utf-8")
    (case_dir / "case.toml").write_text(
        'mode = "subagent"\n'
        'prompt = "prompt.md"\n'
        "\n"
        "[[items]]\n"
        'id = "item-a"\n'
        'kind = "trend"\n'
        'scorer = "always_true"\n',
        encoding="utf-8",
    )


def _write_transcript(path: Path, final_text: str = "done") -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    line = json.dumps(
        {
            "type": "assistant",
            "message": {"model": "claude-test", "content": [{"type": "text", "text": final_text}]},
        }
    )
    path.write_text(line + "\n", encoding="utf-8")


def test_prompt_and_score_builders_write_nothing(tmp_path):
    case_dir = tmp_path / "skill-x" / "case-a"
    _make_minimal_case(case_dir)
    transcript_path = tmp_path / "raws" / "t.jsonl"
    _write_transcript(transcript_path)

    before = _files_under(tmp_path)

    build_dispatch_prompt(case_dir)
    build_no_skill_prompt(case_dir)
    score_attempt(case_dir, [transcript_path], None, {"item-a"})

    after = _files_under(tmp_path)

    assert after == before
    assert not any(path.name == "tests.md" for path in tmp_path.rglob("*"))


def test_snapshot_end_state_writes_only_under_dest_and_never_tests_md(tmp_path):
    case_dir = tmp_path / "skill-x" / "case-b"
    _make_minimal_case(case_dir, with_end_state=True)
    workdir = tmp_path / "workdir"
    workdir.mkdir()
    transcript_path = tmp_path / "raws" / "t2.jsonl"
    _write_transcript(transcript_path)
    dest = tmp_path / "attempt-1" / "end_state"

    before = _files_under(tmp_path)

    snapshot_end_state(case_dir, workdir, [transcript_path], dest)

    after = _files_under(tmp_path)
    new_files = after - before

    assert new_files == {dest / "note.txt"}
    assert not any(path.name == "tests.md" for path in tmp_path.rglob("*"))
