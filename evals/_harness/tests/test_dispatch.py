"""Tests for evals._harness.dispatch — the eval-suite conductor's harness entry points.

Every synthetic case is built at test time under ``tmp_path``, never
committed under ``evals/``. The committed-case scans below are exercised
against the real ``evals/`` tree too, vacuously until #998-#1002 populate
case directories.
"""

from __future__ import annotations

import json
import shutil
import tomllib
from pathlib import Path

import pytest

from evals._harness.dispatch import (
    build_dispatch_prompt,
    build_no_skill_prompt,
    score_attempt,
    snapshot_end_state,
)

_REPO_ROOT = Path(__file__).resolve().parents[3]
_EVALS_ROOT = _REPO_ROOT / "evals"
_NO_SKILL_INSTRUCTION = "Do not invoke any skill while completing this task."


def _committed_case_dirs() -> list[Path]:
    return sorted(p.parent for p in _EVALS_ROOT.glob("*/*/case.toml"))


def _committed_skill_dirs() -> list[Path]:
    return sorted(p for p in _EVALS_ROOT.iterdir() if p.is_dir() and p.name != "_harness")


def _find_duplicate_item_ids(skill_dir: Path) -> set[str]:
    """Item ids share one namespace per skill (``checks.manifest`` is per skill)."""
    seen: set[str] = set()
    duplicates: set[str] = set()
    for case_toml_path in sorted(skill_dir.glob("*/case.toml")):
        case_toml = tomllib.loads(case_toml_path.read_text(encoding="utf-8"))
        for item in case_toml.get("items", []):
            item_id = item["id"]
            if item_id in seen:
                duplicates.add(item_id)
            seen.add(item_id)
    return duplicates


def _write_final_text_transcript(path: Path, final_text: str, model: str = "claude-test") -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    line = json.dumps(
        {
            "type": "assistant",
            "message": {"model": model, "content": [{"type": "text", "text": final_text}]},
        }
    )
    path.write_text(line + "\n", encoding="utf-8")


def _write_truncated_transcript(path: Path) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text("not valid json at all\n", encoding="utf-8")


def _write_marker_case(case_dir: Path) -> None:
    case_dir.mkdir(parents=True)
    (case_dir / "prompt.md").write_text("Investigate the repo.\n", encoding="utf-8")
    (case_dir / "acceptance.md").write_text("private acceptance notes\n", encoding="utf-8")
    (case_dir / "predicates.py").write_text(
        "def marker_scorer(evidence, marker):\n"
        "    return any(marker in t.final_text for t in evidence.transcripts)\n",
        encoding="utf-8",
    )
    (case_dir / "case.toml").write_text(
        'mode = "subagent"\n'
        'prompt = "prompt.md"\n'
        "\n"
        "[[items]]\n"
        'id = "item-a"\n'
        'kind = "gate-candidate"\n'
        'scorer = "marker_scorer"\n'
        'params = { marker = "MARKER_HIT" }\n',
        encoding="utf-8",
    )


# ---------------------------------------------------------------------------
# mode validation
# ---------------------------------------------------------------------------


def test_committed_cases_declare_valid_mode():
    for case_dir in _committed_case_dirs():
        case_toml = tomllib.loads((case_dir / "case.toml").read_text(encoding="utf-8"))
        assert case_toml.get("mode") in {"subagent", "inline"}, case_dir


def test_missing_mode_is_rejected(tmp_path):
    case_dir = tmp_path / "case-missing-mode"
    case_dir.mkdir()
    (case_dir / "prompt.md").write_text("hello\n", encoding="utf-8")
    (case_dir / "case.toml").write_text('prompt = "prompt.md"\n', encoding="utf-8")

    with pytest.raises(ValueError):
        build_dispatch_prompt(case_dir)


def test_invalid_mode_is_rejected(tmp_path):
    case_dir = tmp_path / "case-bad-mode"
    case_dir.mkdir()
    (case_dir / "prompt.md").write_text("hello\n", encoding="utf-8")
    (case_dir / "case.toml").write_text('mode = "bogus"\nprompt = "prompt.md"\n', encoding="utf-8")

    with pytest.raises(ValueError):
        build_dispatch_prompt(case_dir)


# ---------------------------------------------------------------------------
# build_dispatch_prompt: never leaks acceptance.md
# ---------------------------------------------------------------------------


def test_build_dispatch_prompt_never_leaks_acceptance_text_for_committed_cases():
    for case_dir in _committed_case_dirs():
        acceptance_path = case_dir / "acceptance.md"
        if not acceptance_path.exists():
            continue
        acceptance_text = acceptance_path.read_text(encoding="utf-8")
        output = build_dispatch_prompt(case_dir)
        assert acceptance_text not in output


def test_build_dispatch_prompt_does_not_leak_acceptance_text_even_when_prompt_embeds_it(tmp_path):
    """A synthetic case whose acceptance.md holds a unique marker.

    Proves the leak check is meaningful: the corresponding teeth mutant makes
    ``build_dispatch_prompt`` also read and append ``acceptance.md``, which
    turns this assertion red; the real implementation never reads
    ``acceptance.md`` at all, so it stays green.
    """
    case_dir = tmp_path / "leaky-case"
    case_dir.mkdir()
    acceptance_text = "ACCEPTANCE-ONLY: do not ship if the auth check is missing.\n"
    (case_dir / "acceptance.md").write_text(acceptance_text, encoding="utf-8")
    (case_dir / "prompt.md").write_text(
        "Investigate the repo and report findings.\n", encoding="utf-8"
    )
    (case_dir / "case.toml").write_text(
        'mode = "subagent"\nprompt = "prompt.md"\n', encoding="utf-8"
    )

    output = build_dispatch_prompt(case_dir)

    assert acceptance_text not in output


# ---------------------------------------------------------------------------
# build_no_skill_prompt
# ---------------------------------------------------------------------------


def test_build_no_skill_prompt_omits_skill_name_and_adds_instruction(tmp_path):
    skill_dir = tmp_path / "adversarial-review"
    case_dir = skill_dir / "case-a"
    case_dir.mkdir(parents=True)
    (case_dir / "prompt.md").write_text(
        "Use the adversarial-review skill to review this change.\n"
        "Focus on the auth module.\n",
        encoding="utf-8",
    )
    (case_dir / "case.toml").write_text(
        'mode = "subagent"\nprompt = "prompt.md"\n', encoding="utf-8"
    )

    output = build_no_skill_prompt(case_dir)

    assert "adversarial-review" not in output
    assert _NO_SKILL_INSTRUCTION in output
    assert "Focus on the auth module." in output


def test_build_no_skill_prompt_never_leaks_acceptance_text_even_when_prompt_embeds_it(tmp_path):
    case_dir = tmp_path / "skill-z" / "leaky-case"
    case_dir.mkdir(parents=True)
    acceptance_text = "ACCEPTANCE-ONLY: verify the retry cap is enforced.\n"
    (case_dir / "acceptance.md").write_text(acceptance_text, encoding="utf-8")
    (case_dir / "prompt.md").write_text("Investigate the retry loop.\n", encoding="utf-8")
    (case_dir / "case.toml").write_text(
        'mode = "subagent"\nprompt = "prompt.md"\n', encoding="utf-8"
    )

    output = build_no_skill_prompt(case_dir)

    assert acceptance_text not in output


# ---------------------------------------------------------------------------
# duplicate item ids share one namespace per skill
# ---------------------------------------------------------------------------


def test_committed_cases_have_no_duplicate_item_ids_within_a_skill():
    for skill_dir in _committed_skill_dirs():
        assert _find_duplicate_item_ids(skill_dir) == set(), skill_dir


def test_duplicate_item_id_within_one_skill_across_cases_is_detected(tmp_path):
    skill_dir = tmp_path / "skill-y"
    for case_name in ("case-a", "case-b"):
        case_dir = skill_dir / case_name
        case_dir.mkdir(parents=True)
        (case_dir / "case.toml").write_text(
            'mode = "subagent"\n'
            'prompt = "prompt.md"\n'
            "\n"
            "[[items]]\n"
            'id = "shared-id"\n'
            'kind = "trend"\n'
            'scorer = "always_true"\n',
            encoding="utf-8",
        )

    assert _find_duplicate_item_ids(skill_dir) == {"shared-id"}


# ---------------------------------------------------------------------------
# score_attempt: hit / miss / truncated
# ---------------------------------------------------------------------------


def test_score_attempt_hits_via_synthetic_predicate(tmp_path):
    case_dir = tmp_path / "skill-x" / "case-a"
    _write_marker_case(case_dir)
    transcript_path = tmp_path / "hit.jsonl"
    _write_final_text_transcript(transcript_path, "done, saw MARKER_HIT in the code")

    attempt, unmatched = score_attempt(case_dir, [transcript_path], None, {"item-a"})

    assert attempt.classification == "counted"
    assert attempt.item_hits == {"item-a": "hit"}
    assert attempt.parse_error is False
    assert unmatched == 0


def test_score_attempt_misses_via_synthetic_predicate(tmp_path):
    case_dir = tmp_path / "skill-x" / "case-a"
    _write_marker_case(case_dir)
    transcript_path = tmp_path / "miss.jsonl"
    _write_final_text_transcript(transcript_path, "done, nothing notable")

    attempt, unmatched = score_attempt(case_dir, [transcript_path], None, {"item-a"})

    assert attempt.classification == "counted"
    assert attempt.item_hits == {"item-a": "miss"}
    assert unmatched == 0


def test_score_attempt_truncated_transcript_is_indeterminate(tmp_path):
    case_dir = tmp_path / "skill-x" / "case-a"
    _write_marker_case(case_dir)
    bad_transcript = tmp_path / "bad.jsonl"
    _write_truncated_transcript(bad_transcript)

    attempt, unmatched = score_attempt(case_dir, [bad_transcript], None, {"item-a"})

    assert attempt.classification == "indeterminate"
    assert attempt.item_hits == {"item-a": "indeterminate"}
    assert unmatched == 0


def test_score_attempt_rejects_a_gated_id_not_in_case_toml(tmp_path):
    case_dir = tmp_path / "skill-x" / "case-a"
    _write_marker_case(case_dir)
    transcript_path = tmp_path / "hit.jsonl"
    _write_final_text_transcript(transcript_path, "done, saw MARKER_HIT")

    with pytest.raises(ValueError):
        score_attempt(case_dir, [transcript_path], None, {"no-such-item"})


# ---------------------------------------------------------------------------
# score_attempt: envelope = "findings" parsing
# ---------------------------------------------------------------------------


def test_score_attempt_findings_envelope_parse_failure_scores_miss_with_parse_error(tmp_path):
    case_dir = tmp_path / "skill-x" / "case-b"
    case_dir.mkdir(parents=True)
    (case_dir / "prompt.md").write_text("Review the diff.\n", encoding="utf-8")
    (case_dir / "predicates.py").write_text(
        "def any_finding(evidence):\n    return bool(evidence.findings)\n",
        encoding="utf-8",
    )
    (case_dir / "case.toml").write_text(
        'mode = "subagent"\n'
        'prompt = "prompt.md"\n'
        'envelope = "findings"\n'
        "\n"
        "[[items]]\n"
        'id = "item-b"\n'
        'kind = "gate-candidate"\n'
        'scorer = "any_finding"\n',
        encoding="utf-8",
    )
    transcript_path = tmp_path / "prose.jsonl"
    _write_final_text_transcript(
        transcript_path, "I looked around but found nothing structured to report."
    )

    attempt, unmatched = score_attempt(case_dir, [transcript_path], None, {"item-b"})

    assert attempt.parse_error is True
    assert attempt.item_hits == {"item-b": "miss"}
    assert unmatched == 0


def test_score_attempt_without_findings_envelope_scores_prose_normally(tmp_path):
    case_dir = tmp_path / "skill-x" / "case-c"
    case_dir.mkdir(parents=True)
    (case_dir / "prompt.md").write_text("Fix the bug.\n", encoding="utf-8")
    (case_dir / "predicates.py").write_text(
        "def mentions_fix(evidence):\n"
        "    return any('fixed' in t.final_text for t in evidence.transcripts)\n",
        encoding="utf-8",
    )
    (case_dir / "case.toml").write_text(
        'mode = "subagent"\n'
        'prompt = "prompt.md"\n'
        "\n"
        "[[items]]\n"
        'id = "item-c"\n'
        'kind = "triggering"\n'
        'scorer = "mentions_fix"\n',
        encoding="utf-8",
    )
    transcript_path = tmp_path / "prose2.jsonl"
    _write_final_text_transcript(transcript_path, "I fixed the bug in module foo.")

    attempt, unmatched = score_attempt(case_dir, [transcript_path], None, {"item-c"})

    assert attempt.parse_error is False
    assert attempt.item_hits == {"item-c": "hit"}
    assert unmatched == 0


def test_score_attempt_counts_unmatched_findings_for_findings_envelope_case(tmp_path):
    case_dir = tmp_path / "skill-x" / "case-f"
    case_dir.mkdir(parents=True)
    (case_dir / "prompt.md").write_text("Review the diff.\n", encoding="utf-8")
    (case_dir / "predicates.py").write_text(
        "from evals._harness.matchers import review_match\n\n"
        "def credited(evidence, file_suffix, regex):\n"
        "    return any(\n"
        "        review_match(f, file_suffix=file_suffix, regex=regex, line_window=None)\n"
        "        for f in evidence.findings\n"
        "    )\n",
        encoding="utf-8",
    )
    (case_dir / "case.toml").write_text(
        'mode = "subagent"\n'
        'prompt = "prompt.md"\n'
        'envelope = "findings"\n'
        "\n"
        "[[items]]\n"
        'id = "item-f"\n'
        'kind = "gate-candidate"\n'
        'scorer = "credited"\n'
        'params = { file_suffix = "foo.py", regex = "bug" }\n',
        encoding="utf-8",
    )
    final_text = json.dumps(
        {
            "findings": [
                {"file": "foo.py", "line": 1, "description": "has a bug here"},
                {"file": "bar.py", "line": 2, "description": "unrelated note"},
            ]
        }
    )
    transcript_path = tmp_path / "f.jsonl"
    _write_final_text_transcript(transcript_path, final_text)

    attempt, unmatched = score_attempt(case_dir, [transcript_path], None, {"item-f"})

    assert attempt.item_hits == {"item-f": "hit"}
    assert unmatched == 1


# ---------------------------------------------------------------------------
# snapshot_end_state + score_attempt re-scoring from raws
# ---------------------------------------------------------------------------


def _write_end_state_case(case_dir: Path) -> None:
    case_dir.mkdir(parents=True)
    (case_dir / "prompt.md").write_text("Refactor.\n", encoding="utf-8")
    (case_dir / "predicates.py").write_text(
        "def end_state(workdir, case_dir, transcripts):\n"
        "    return {'result.txt': (workdir / 'result.txt').read_text(encoding='utf-8')}\n\n"
        "def result_says_done(evidence):\n"
        "    return evidence.end_state.get('result.txt', '').strip() == 'done'\n",
        encoding="utf-8",
    )
    (case_dir / "case.toml").write_text(
        'mode = "subagent"\n'
        'prompt = "prompt.md"\n'
        "\n"
        "[[items]]\n"
        'id = "item-d"\n'
        'kind = "gate-candidate"\n'
        'scorer = "result_says_done"\n',
        encoding="utf-8",
    )


def test_snapshot_end_state_then_rescore_from_raws_matches_the_live_score(tmp_path):
    case_dir = tmp_path / "skill-x" / "case-d"
    _write_end_state_case(case_dir)

    workdir = tmp_path / "workdir"
    workdir.mkdir()
    (workdir / "result.txt").write_text("done\n", encoding="utf-8")

    transcript_path = tmp_path / "d.jsonl"
    _write_final_text_transcript(transcript_path, "All set.")

    end_state_dir = tmp_path / "attempt-1" / "end_state"
    snapshot_end_state(case_dir, workdir, [transcript_path], end_state_dir)

    assert (end_state_dir / "result.txt").read_text(encoding="utf-8") == "done\n"

    live_attempt, live_unmatched = score_attempt(
        case_dir, [transcript_path], workdir, {"item-d"}, end_state_dir=end_state_dir
    )

    raw_end_state_dir = tmp_path / "raw" / "end_state"
    shutil.copytree(end_state_dir, raw_end_state_dir)
    rescored_attempt, rescored_unmatched = score_attempt(
        case_dir, [transcript_path], None, {"item-d"}, end_state_dir=raw_end_state_dir
    )

    assert live_attempt == rescored_attempt
    assert live_unmatched == rescored_unmatched
    assert live_attempt.item_hits == {"item-d": "hit"}


def test_snapshot_end_state_without_end_state_fn_leaves_dest_empty(tmp_path):
    case_dir = tmp_path / "skill-x" / "case-e"
    case_dir.mkdir(parents=True)
    (case_dir / "prompt.md").write_text("Do nothing special.\n", encoding="utf-8")
    (case_dir / "predicates.py").write_text(
        "def always_true(evidence):\n    return True\n", encoding="utf-8"
    )
    (case_dir / "case.toml").write_text(
        'mode = "subagent"\n'
        'prompt = "prompt.md"\n'
        "\n"
        "[[items]]\n"
        'id = "item-e"\n'
        'kind = "trend"\n'
        'scorer = "always_true"\n',
        encoding="utf-8",
    )

    workdir = tmp_path / "workdir-e"
    workdir.mkdir()
    dest = tmp_path / "end_state_empty"

    snapshot_end_state(case_dir, workdir, [], dest)

    assert dest.is_dir()
    assert list(dest.iterdir()) == []
