"""Tests for evals._harness.dispatch — the eval-suite conductor's harness entry points.

Every synthetic case is built at test time under ``tmp_path``, never
committed under ``evals/``. The committed-case scans below are exercised
against the real ``evals/`` tree too, vacuously until #998-#1002 populate
case directories.
"""

from __future__ import annotations

import json
import re
import shutil
from pathlib import Path

import pytest

from evals._harness.dispatch import (
    AcceptanceLeakError,
    CaseContractError,
    PromptPathError,
    build_dispatch_prompt,
    build_no_skill_prompt,
    find_duplicate_item_ids,
    find_invalid_modes,
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


def _assert_case_modes_valid(case_dirs: list[Path]) -> None:
    """The mode check, as a test would run it: red on any invalid or missing ``mode``."""
    problems = find_invalid_modes(case_dirs)
    assert problems == [], problems


def _assert_no_duplicate_item_ids(skill_dirs: list[Path]) -> None:
    """The per-skill id-namespace check, as a test would run it."""
    for skill_dir in skill_dirs:
        assert find_duplicate_item_ids(skill_dir) == set(), skill_dir


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
    _assert_case_modes_valid(_committed_case_dirs())


@pytest.mark.parametrize(
    "case_toml_text",
    [
        'prompt = "prompt.md"\n',
        'mode = "bogus"\nprompt = "prompt.md"\n',
        'mode = ["subagent"]\nprompt = "prompt.md"\n',
        'mode = "subagent\n',
    ],
    ids=["missing", "bogus", "list", "unparseable"],
)
def test_the_committed_case_mode_check_goes_red_on_a_synthetic_bad_case(tmp_path, case_toml_text):
    """Spec test 1: a synthetic case with a missing or invalid mode turns THE TEST red."""
    bad_case = tmp_path / "skill-m" / "bad-case"
    bad_case.mkdir(parents=True)
    (bad_case / "case.toml").write_text(case_toml_text, encoding="utf-8")

    with pytest.raises(AssertionError):
        _assert_case_modes_valid([bad_case])


def test_the_committed_case_mode_check_stays_green_on_valid_synthetic_cases(tmp_path):
    case_dirs = []
    for mode in ("subagent", "inline"):
        case_dir = tmp_path / "skill-m" / f"case-{mode}"
        case_dir.mkdir(parents=True)
        (case_dir / "case.toml").write_text(
            f'mode = "{mode}"\nprompt = "prompt.md"\n', encoding="utf-8"
        )
        case_dirs.append(case_dir)

    _assert_case_modes_valid(case_dirs)


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


_ACCEPTANCE_TEXT = (
    "# Acceptance\n"
    "\n"
    "- The reviewer must report the missing auth check in login.py.\n"
    "- The reviewer must not rewrite the whole module.\n"
)


def _leak_case(
    tmp_path: Path, prompt_text: str, acceptance_text: str | None = _ACCEPTANCE_TEXT
) -> Path:
    case_dir = tmp_path / "skill-z" / "leak-case"
    case_dir.mkdir(parents=True)
    (case_dir / "prompt.md").write_text(prompt_text, encoding="utf-8")
    if acceptance_text is not None:
        (case_dir / "acceptance.md").write_text(acceptance_text, encoding="utf-8")
    (case_dir / "case.toml").write_text(
        'mode = "subagent"\nprompt = "prompt.md"\n', encoding="utf-8"
    )
    return case_dir


def test_build_dispatch_prompt_refuses_a_prompt_that_embeds_acceptance_md_exactly(tmp_path):
    """Spec test 2: a synthetic case whose prompt.md embeds acceptance.md's exact text.

    Red before the leak guard (the prompt came back unchanged), green after.
    """
    case_dir = _leak_case(tmp_path, "Investigate the repo.\n\n" + _ACCEPTANCE_TEXT)

    with pytest.raises(AcceptanceLeakError):
        build_dispatch_prompt(case_dir)


def test_build_dispatch_prompt_refuses_a_prompt_that_embeds_a_single_acceptance_line(tmp_path):
    case_dir = _leak_case(
        tmp_path,
        "Investigate the repo and report.\n"
        "Remember: The reviewer must report the missing auth check in login.py.\n",
    )

    with pytest.raises(AcceptanceLeakError):
        build_dispatch_prompt(case_dir)


def test_build_dispatch_prompt_refuses_a_leaked_line_whose_bullet_and_indentation_differ(tmp_path):
    case_dir = _leak_case(
        tmp_path,
        "Investigate the repo.\n\n    * The  reviewer must not rewrite the whole module.\n",
    )

    with pytest.raises(AcceptanceLeakError):
        build_dispatch_prompt(case_dir)


def test_build_dispatch_prompt_builds_a_clean_prompt_without_leaking_acceptance(tmp_path):
    case_dir = _leak_case(tmp_path, "Investigate the repo and report findings.\n")

    output = build_dispatch_prompt(case_dir)

    assert output == "Investigate the repo and report findings.\n"
    assert "missing auth check" not in output


def test_build_dispatch_prompt_ignores_markdown_noise_shared_with_acceptance(tmp_path):
    case_dir = _leak_case(
        tmp_path,
        "# Task\n\nInvestigate the repo.\n",
        acceptance_text="# Task\n\n---\n- \nSomething only acceptance says here.\n",
    )

    # A heading-only or punctuation-only line is not acceptance content, but
    # "# Task" is a real line of text shared with the prompt: it is short
    # enough to count as a leak only if it is a whole line. It is.
    with pytest.raises(AcceptanceLeakError):
        build_dispatch_prompt(case_dir)

    case_dir = _leak_case(
        tmp_path / "second",
        "Investigate the repo.\n---\n",
        acceptance_text="---\n- \nSomething only acceptance says here.\n",
    )

    assert build_dispatch_prompt(case_dir) == "Investigate the repo.\n---\n"


def test_build_dispatch_prompt_works_without_an_acceptance_file(tmp_path):
    case_dir = _leak_case(tmp_path, "Investigate the repo.\n", acceptance_text=None)

    assert build_dispatch_prompt(case_dir) == "Investigate the repo.\n"


# ---------------------------------------------------------------------------
# the prompt path must stay inside the case directory and never name acceptance.md
# ---------------------------------------------------------------------------


def _prompt_path_case(tmp_path: Path, prompt_value: str) -> Path:
    case_dir = tmp_path / "skill-p" / "case-p"
    case_dir.mkdir(parents=True)
    (case_dir / "acceptance.md").write_text("Private acceptance criterion here.\n", encoding="utf-8")
    (case_dir / "case.toml").write_text(
        f'mode = "subagent"\nprompt = {json.dumps(prompt_value)}\n', encoding="utf-8"
    )
    return case_dir


@pytest.mark.parametrize("builder", [build_dispatch_prompt, build_no_skill_prompt])
@pytest.mark.parametrize("prompt_value", ["acceptance.md", "./acceptance.md", "sub/../acceptance.md"])
def test_a_prompt_that_names_acceptance_md_is_refused(tmp_path, builder, prompt_value):
    case_dir = _prompt_path_case(tmp_path, prompt_value)
    (case_dir / "sub").mkdir()

    with pytest.raises(PromptPathError):
        builder(case_dir)


@pytest.mark.parametrize("builder", [build_dispatch_prompt, build_no_skill_prompt])
def test_a_prompt_symlink_to_acceptance_md_is_refused(tmp_path, builder):
    case_dir = _prompt_path_case(tmp_path, "prompt.md")
    (case_dir / "prompt.md").symlink_to(case_dir / "acceptance.md")

    with pytest.raises(PromptPathError):
        builder(case_dir)


@pytest.mark.parametrize("builder", [build_dispatch_prompt, build_no_skill_prompt])
def test_a_prompt_path_escaping_the_case_directory_is_refused(tmp_path, builder):
    (tmp_path / "skill-p").mkdir()
    (tmp_path / "skill-p" / "secret.txt").write_text("outside the case\n", encoding="utf-8")
    case_dir = _prompt_path_case(tmp_path, "../secret.txt")

    with pytest.raises(PromptPathError):
        builder(case_dir)


@pytest.mark.parametrize("builder", [build_dispatch_prompt, build_no_skill_prompt])
def test_an_absolute_prompt_path_is_refused(tmp_path, builder):
    outside = tmp_path / "outside.txt"
    outside.write_text("outside the case\n", encoding="utf-8")
    case_dir = _prompt_path_case(tmp_path, str(outside))

    with pytest.raises(PromptPathError):
        builder(case_dir)


@pytest.mark.parametrize("builder", [build_dispatch_prompt, build_no_skill_prompt])
def test_a_prompt_symlink_pointing_outside_the_case_directory_is_refused(tmp_path, builder):
    outside = tmp_path / "outside.txt"
    outside.write_text("outside the case\n", encoding="utf-8")
    case_dir = _prompt_path_case(tmp_path, "prompt.md")
    (case_dir / "prompt.md").symlink_to(outside)

    with pytest.raises(PromptPathError):
        builder(case_dir)


@pytest.mark.parametrize("builder", [build_dispatch_prompt, build_no_skill_prompt])
def test_a_missing_prompt_file_is_named_in_the_error(tmp_path, builder):
    case_dir = _prompt_path_case(tmp_path, "nope.md")

    with pytest.raises(PromptPathError, match="nope.md"):
        builder(case_dir)


def test_a_prompt_in_a_subdirectory_of_the_case_directory_is_accepted(tmp_path):
    case_dir = _prompt_path_case(tmp_path, "prompts/main.md")
    (case_dir / "prompts").mkdir()
    (case_dir / "prompts" / "main.md").write_text("Investigate the repo.\n", encoding="utf-8")

    assert build_dispatch_prompt(case_dir) == "Investigate the repo.\n"


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


def test_build_no_skill_prompt_refuses_a_prompt_that_embeds_acceptance_md(tmp_path):
    case_dir = _leak_case(tmp_path, "Investigate the repo.\n\n" + _ACCEPTANCE_TEXT)

    with pytest.raises(AcceptanceLeakError):
        build_no_skill_prompt(case_dir)


def test_build_no_skill_prompt_refuses_a_prompt_that_embeds_a_single_acceptance_line(tmp_path):
    case_dir = _leak_case(
        tmp_path,
        "Investigate the repo.\nThe reviewer must report the missing auth check in login.py.\n",
    )

    with pytest.raises(AcceptanceLeakError):
        build_no_skill_prompt(case_dir)


def test_build_no_skill_prompt_builds_a_clean_prompt_without_leaking_acceptance(tmp_path):
    case_dir = _leak_case(tmp_path, "Investigate the repo.\n")

    output = build_no_skill_prompt(case_dir)

    assert "missing auth check" not in output
    assert output.startswith("Investigate the repo.")


def _no_skill_case(tmp_path: Path, skill: str, prompt_text: str) -> Path:
    case_dir = tmp_path / skill / "case-a"
    case_dir.mkdir(parents=True)
    (case_dir / "prompt.md").write_text(prompt_text, encoding="utf-8")
    (case_dir / "case.toml").write_text(
        'mode = "subagent"\nprompt = "prompt.md"\n', encoding="utf-8"
    )
    return case_dir


def _skill_reference_pattern(skill: str) -> re.Pattern[str]:
    """A case-insensitive whole-token reference to *skill* (bare, namespaced, or in a path)."""
    return re.compile(rf"(?<![\w-]){re.escape(skill)}(?![\w-])", re.IGNORECASE)


def test_build_no_skill_prompt_keeps_task_text_when_skill_name_is_mid_line(tmp_path):
    case_dir = _no_skill_case(
        tmp_path,
        "adversarial-review",
        "Review this code with adversarial-review: look at auth.py line 3 for a SQL injection bug.\n"
        "Also check tdd.\n",
    )

    output = build_no_skill_prompt(case_dir)

    assert "look at auth.py line 3 for a SQL injection bug." in output
    assert "Also check tdd." in output
    assert "Review this code" in output
    assert not _skill_reference_pattern("adversarial-review").search(output)


def test_build_no_skill_prompt_keeps_a_single_line_prompt_that_names_the_skill(tmp_path):
    case_dir = _no_skill_case(
        tmp_path, "adversarial-review", "Run /workbench:adversarial-review on it."
    )

    output = build_no_skill_prompt(case_dir)

    assert output.startswith("Run")
    assert "on it." in output
    assert not _skill_reference_pattern("adversarial-review").search(output)


def test_build_no_skill_prompt_removes_the_skill_name_case_insensitively(tmp_path):
    case_dir = _no_skill_case(
        tmp_path, "adversarial-review", "Adversarial-Review is great. Find the bug in foo.py.\n"
    )

    output = build_no_skill_prompt(case_dir)

    assert "Find the bug in foo.py." in output
    assert not _skill_reference_pattern("adversarial-review").search(output)


def test_build_no_skill_prompt_removes_a_skill_path_reference_but_keeps_the_task(tmp_path):
    case_dir = _no_skill_case(
        tmp_path,
        "adversarial-review",
        "Read plugins/workbench/skills/adversarial-review/SKILL.md first, then fix parser.py.\n",
    )

    output = build_no_skill_prompt(case_dir)

    assert "then fix parser.py." in output
    assert "plugins/workbench/skills/" not in output
    assert "SKILL.md" not in output
    assert not _skill_reference_pattern("adversarial-review").search(output)


def test_build_no_skill_prompt_does_not_eat_words_that_merely_contain_the_skill_name(tmp_path):
    case_dir = _no_skill_case(
        tmp_path,
        "commit",
        "Use the commit skill for this.\n"
        "The commitment to quality matters.\n"
        "We are committing to the plan.\n",
    )

    output = build_no_skill_prompt(case_dir)

    assert "The commitment to quality matters." in output
    assert "We are committing to the plan." in output
    assert not _skill_reference_pattern("commit").search(output)


# ---------------------------------------------------------------------------
# duplicate item ids share one namespace per skill
# ---------------------------------------------------------------------------


def test_committed_cases_have_no_duplicate_item_ids_within_a_skill():
    _assert_no_duplicate_item_ids(_committed_skill_dirs())


def _write_item_ids_case(case_dir: Path, *item_ids: str) -> None:
    case_dir.mkdir(parents=True)
    items = "".join(
        f'\n[[items]]\nid = "{item_id}"\nkind = "trend"\nscorer = "always_true"\n'
        for item_id in item_ids
    )
    (case_dir / "case.toml").write_text(
        'mode = "subagent"\nprompt = "prompt.md"\n' + items, encoding="utf-8"
    )


def test_duplicate_item_id_across_two_cases_of_one_skill_turns_the_test_red(tmp_path):
    """Spec test: two synthetic cases sharing an id make THE TEST go red."""
    skill_dir = tmp_path / "skill-y"
    _write_item_ids_case(skill_dir / "case-a", "shared-id", "only-a")
    _write_item_ids_case(skill_dir / "case-b", "shared-id", "only-b")

    assert find_duplicate_item_ids(skill_dir) == {"shared-id"}
    with pytest.raises(AssertionError):
        _assert_no_duplicate_item_ids([skill_dir])


def test_duplicate_item_id_inside_a_single_case_is_also_a_duplicate(tmp_path):
    skill_dir = tmp_path / "skill-y"
    _write_item_ids_case(skill_dir / "case-a", "twice", "twice")

    assert find_duplicate_item_ids(skill_dir) == {"twice"}


def test_distinct_item_ids_across_cases_stay_green(tmp_path):
    skill_dir = tmp_path / "skill-y"
    _write_item_ids_case(skill_dir / "case-a", "a-1", "a-2")
    _write_item_ids_case(skill_dir / "case-b", "b-1")

    assert find_duplicate_item_ids(skill_dir) == set()
    _assert_no_duplicate_item_ids([skill_dir])


def test_the_same_item_id_in_two_different_skills_is_not_a_duplicate(tmp_path):
    _write_item_ids_case(tmp_path / "skill-1" / "case-a", "shared-id")
    _write_item_ids_case(tmp_path / "skill-2" / "case-a", "shared-id")

    _assert_no_duplicate_item_ids([tmp_path / "skill-1", tmp_path / "skill-2"])


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


def _write_item_case(case_dir: Path, item_id: str) -> None:
    case_dir.mkdir(parents=True)
    (case_dir / "prompt.md").write_text("Investigate.\n", encoding="utf-8")
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
        f'id = "{item_id}"\n'
        'kind = "gate-candidate"\n'
        'scorer = "marker_scorer"\n'
        'params = { marker = "MARKER_HIT" }\n',
        encoding="utf-8",
    )


def test_score_attempt_tolerates_gated_ids_that_belong_to_a_sibling_case(tmp_path):
    """``checks.manifest`` is per skill, so the conductor passes the whole manifest set.

    A two-case skill: the manifest gates one item in each case, and the
    conductor hands both ids to every case's ``score_attempt``. Each case
    scores only its own items.
    """
    skill_dir = tmp_path / "skill-two"
    _write_item_case(skill_dir / "case-a", "item-a")
    _write_item_case(skill_dir / "case-b", "item-b")
    transcript_path = tmp_path / "hit.jsonl"
    _write_final_text_transcript(transcript_path, "saw MARKER_HIT")
    manifest_gated = {"item-a", "item-b"}

    attempt_a, _ = score_attempt(skill_dir / "case-a", [transcript_path], None, manifest_gated)
    attempt_b, _ = score_attempt(skill_dir / "case-b", [transcript_path], None, manifest_gated)

    assert attempt_a.item_hits == {"item-a": "hit"}
    assert attempt_b.item_hits == {"item-b": "hit"}


def test_score_attempt_tolerates_a_gated_id_naming_no_item_in_the_case(tmp_path):
    case_dir = tmp_path / "skill-x" / "case-a"
    _write_marker_case(case_dir)
    transcript_path = tmp_path / "hit.jsonl"
    _write_final_text_transcript(transcript_path, "done, saw MARKER_HIT")

    attempt, _ = score_attempt(case_dir, [transcript_path], None, {"no-such-item"})

    assert attempt.item_hits == {"item-a": "hit"}


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
# score_attempt: inline mode scores one transcript per lens agent
# ---------------------------------------------------------------------------


def _write_inline_lens_case(case_dir: Path) -> None:
    case_dir.mkdir(parents=True)
    (case_dir / "prompt.md").write_text("Review the diff.\n", encoding="utf-8")
    (case_dir / "predicates.py").write_text(
        "def both_lenses_reported(evidence):\n"
        "    files = {f['file'] for f in evidence.findings}\n"
        "    return {'one.py', 'two.py'} <= files\n",
        encoding="utf-8",
    )
    (case_dir / "case.toml").write_text(
        'mode = "inline"\n'
        'prompt = "prompt.md"\n'
        'envelope = "findings"\n'
        "\n"
        "[[items]]\n"
        'id = "item-lens"\n'
        'kind = "gate-candidate"\n'
        'scorer = "both_lenses_reported"\n',
        encoding="utf-8",
    )


def _findings_reply(file: str) -> str:
    return json.dumps({"findings": [{"file": file, "line": 1, "description": "a bug"}]})


@pytest.fixture
def lens_case(tmp_path):
    case_dir = tmp_path / "skill-lens" / "case-lens"
    _write_inline_lens_case(case_dir)
    return case_dir


def _lens_transcripts(tmp_path: Path, *kinds: str) -> list[Path]:
    """One transcript per lens agent: 'one'/'two' = findings, 'prose' = parse failure, 'bad' = truncated."""
    paths = []
    for index, kind in enumerate(kinds):
        path = tmp_path / f"lens-{index}.jsonl"
        if kind == "bad":
            _write_truncated_transcript(path)
        elif kind == "prose":
            _write_final_text_transcript(path, "I found nothing structured to report.")
        else:
            _write_final_text_transcript(path, _findings_reply(f"{kind}.py"))
        paths.append(path)
    return paths


def test_inline_findings_are_the_union_across_every_lens_transcript(tmp_path, lens_case):
    transcripts = _lens_transcripts(tmp_path, "one", "two")

    attempt, _ = score_attempt(lens_case, transcripts, None, {"item-lens"})

    assert attempt.classification == "counted"
    assert attempt.parse_error is False
    assert attempt.item_hits == {"item-lens": "hit"}


def test_inline_findings_union_includes_a_later_transcript_when_the_first_has_none(
    tmp_path, lens_case
):
    transcripts = _lens_transcripts(tmp_path, "prose", "one", "two")

    attempt, _ = score_attempt(lens_case, transcripts, None, {"item-lens"})

    assert attempt.item_hits == {"item-lens": "miss"}
    assert attempt.parse_error is True


def test_inline_one_unparseable_lens_reply_sets_parse_error_for_the_whole_attempt(
    tmp_path, lens_case
):
    transcripts = _lens_transcripts(tmp_path, "one", "prose", "two")

    attempt, _ = score_attempt(lens_case, transcripts, None, {"item-lens"})

    assert attempt.classification == "counted"
    assert attempt.parse_error is True
    assert attempt.item_hits == {"item-lens": "miss"}


def test_inline_an_incomplete_later_lens_transcript_makes_the_attempt_indeterminate(
    tmp_path, lens_case
):
    transcripts = _lens_transcripts(tmp_path, "one", "bad", "two")

    attempt, _ = score_attempt(lens_case, transcripts, None, {"item-lens"})

    assert attempt.classification == "indeterminate"
    assert attempt.item_hits == {"item-lens": "indeterminate"}
    assert attempt.parse_error is False


def test_inline_an_incomplete_first_lens_transcript_makes_the_attempt_indeterminate(
    tmp_path, lens_case
):
    transcripts = _lens_transcripts(tmp_path, "bad", "one", "two")

    attempt, _ = score_attempt(lens_case, transcripts, None, {"item-lens"})

    assert attempt.classification == "indeterminate"


def test_inline_incomplete_outranks_a_parse_failure_among_the_lens_transcripts(tmp_path, lens_case):
    transcripts = _lens_transcripts(tmp_path, "one", "prose", "bad")

    attempt, _ = score_attempt(lens_case, transcripts, None, {"item-lens"})

    assert attempt.classification == "indeterminate"
    assert attempt.parse_error is False


def test_inline_a_dispatch_error_override_wins_over_complete_lens_transcripts(tmp_path, lens_case):
    transcripts = _lens_transcripts(tmp_path, "one", "two")

    attempt, _ = score_attempt(
        lens_case, transcripts, None, {"item-lens"}, transcript_status="dispatch_error"
    )

    assert attempt.classification == "indeterminate"


def test_inline_with_no_transcripts_is_indeterminate(tmp_path, lens_case):
    attempt, _ = score_attempt(lens_case, [], None, {"item-lens"})

    assert attempt.classification == "indeterminate"


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


# ---------------------------------------------------------------------------
# a malformed case names its own defect
# ---------------------------------------------------------------------------


def _bare_case(tmp_path: Path, case_toml_text: str, predicates: str | None = None) -> Path:
    case_dir = tmp_path / "skill-q" / "case-q"
    case_dir.mkdir(parents=True)
    (case_dir / "prompt.md").write_text("Investigate.\n", encoding="utf-8")
    (case_dir / "case.toml").write_text(case_toml_text, encoding="utf-8")
    if predicates is not None:
        (case_dir / "predicates.py").write_text(predicates, encoding="utf-8")
    return case_dir


_ONE_ITEM_TOML = (
    'mode = "subagent"\nprompt = "prompt.md"\n\n'
    '[[items]]\nid = "item-q"\nkind = "trend"\nscorer = "scorer_q"\n'
)


def _complete_transcript(tmp_path: Path) -> Path:
    path = tmp_path / "q.jsonl"
    _write_final_text_transcript(path, "done")
    return path


def test_score_attempt_names_the_case_when_predicates_py_is_missing(tmp_path):
    case_dir = _bare_case(tmp_path, _ONE_ITEM_TOML, predicates=None)

    with pytest.raises(CaseContractError, match=r"case-q.*predicates\.py|predicates\.py.*case-q"):
        score_attempt(case_dir, [_complete_transcript(tmp_path)], None, set())


def test_score_attempt_names_the_case_and_scorer_when_the_scorer_is_not_defined(tmp_path):
    case_dir = _bare_case(tmp_path, _ONE_ITEM_TOML, predicates="def other(evidence):\n    return True\n")

    with pytest.raises(CaseContractError) as excinfo:
        score_attempt(case_dir, [_complete_transcript(tmp_path)], None, set())

    assert "case-q" in str(excinfo.value)
    assert "scorer_q" in str(excinfo.value)


def test_score_attempt_names_the_scorer_when_it_is_not_callable(tmp_path):
    case_dir = _bare_case(tmp_path, _ONE_ITEM_TOML, predicates="scorer_q = 3\n")

    with pytest.raises(CaseContractError, match="scorer_q"):
        score_attempt(case_dir, [_complete_transcript(tmp_path)], None, set())


def test_a_broken_scorer_reference_is_reported_even_when_the_attempt_is_indeterminate(tmp_path):
    """A case bug must not hide behind harness breakage and burn the reserve."""
    case_dir = _bare_case(tmp_path, _ONE_ITEM_TOML, predicates="def other(evidence):\n    return True\n")
    bad_transcript = tmp_path / "bad.jsonl"
    _write_truncated_transcript(bad_transcript)

    with pytest.raises(CaseContractError, match="scorer_q"):
        score_attempt(case_dir, [bad_transcript], None, set())


@pytest.mark.parametrize("mode_literal", ['["subagent"]', "3", "true", '{ a = "subagent" }'])
def test_a_non_string_mode_is_a_value_error_like_any_other_bad_mode(tmp_path, mode_literal):
    case_dir = _bare_case(tmp_path, f'mode = {mode_literal}\nprompt = "prompt.md"\n')

    with pytest.raises(ValueError):
        build_dispatch_prompt(case_dir)


@pytest.mark.parametrize(
    "items_toml",
    [
        '[[items]]\nkind = "trend"\nscorer = "scorer_q"\n',
        '[[items]]\nid = "item-q"\nkind = "trend"\n',
        '[[items]]\nid = "item-q"\nkind = "trend"\nscorer = "scorer_q"\nparams = 3\n',
    ],
)
def test_an_item_missing_id_or_scorer_or_with_bad_params_is_named(tmp_path, items_toml):
    case_dir = _bare_case(
        tmp_path,
        'mode = "subagent"\nprompt = "prompt.md"\n\n' + items_toml,
        predicates="def scorer_q(evidence):\n    return True\n",
    )

    with pytest.raises(CaseContractError, match="case-q"):
        score_attempt(case_dir, [_complete_transcript(tmp_path)], None, set())


def test_a_binary_file_in_the_end_state_directory_does_not_crash_scoring(tmp_path):
    case_dir = _bare_case(
        tmp_path,
        _ONE_ITEM_TOML,
        predicates=(
            "def scorer_q(evidence):\n"
            "    return sorted(evidence.end_state) == ['blob.bin', 'note.txt'] "
            "and evidence.end_state['note.txt'] == 'hello'\n"
        ),
    )
    end_state_dir = tmp_path / "end_state"
    end_state_dir.mkdir()
    (end_state_dir / "note.txt").write_text("hello", encoding="utf-8")
    (end_state_dir / "blob.bin").write_bytes(b"\xff\xfe\x00\x80binary")

    attempt, _ = score_attempt(
        case_dir, [_complete_transcript(tmp_path)], None, set(), end_state_dir=end_state_dir
    )

    assert attempt.item_hits == {"item-q": "hit"}


# ---------------------------------------------------------------------------
# snapshot_end_state: file-name guard, symlinks
# ---------------------------------------------------------------------------


def _snapshot_case(tmp_path: Path, returned_literal: str) -> Path:
    return _bare_case(
        tmp_path,
        _ONE_ITEM_TOML,
        predicates=(
            "def scorer_q(evidence):\n    return True\n\n"
            "def end_state(workdir, case_dir, transcripts):\n"
            f"    return {returned_literal}\n"
        ),
    )


def _written_files(root: Path) -> list[str]:
    return sorted(str(p.relative_to(root)) for p in root.rglob("*") if p.is_file())


@pytest.mark.parametrize(
    "name",
    ["../x", "/abs/path", "a/b", "..", ".", "", "a\\b", "a\0b", "tests.md", "Tests.MD"],
)
def test_snapshot_end_state_rejects_an_unsafe_file_name_and_writes_nothing(tmp_path, name):
    case_dir = _snapshot_case(tmp_path, f'{{"ok.txt": "fine", {name!r}: "bad"}}')
    workdir = tmp_path / "workdir"
    workdir.mkdir()
    dest = tmp_path / "attempt" / "end_state"

    with pytest.raises(ValueError):
        snapshot_end_state(case_dir, workdir, [], dest)

    assert _written_files(tmp_path / "attempt") == []
    assert not (tmp_path / "x").exists()


def test_snapshot_end_state_rejects_a_non_string_name_or_text(tmp_path):
    workdir = tmp_path / "workdir"
    workdir.mkdir()
    for returned in ('{5: "x"}', '{"a.txt": 5}', '["a.txt"]'):
        case_dir = _snapshot_case(tmp_path / returned.replace('"', "").replace(" ", ""), returned)
        with pytest.raises(ValueError):
            snapshot_end_state(case_dir, workdir, [], tmp_path / "dest-types")


def test_snapshot_end_state_refuses_to_write_through_a_symlinked_file_in_dest(tmp_path):
    case_dir = _snapshot_case(tmp_path, '{"note.txt": "new"}')
    workdir = tmp_path / "workdir"
    workdir.mkdir()
    victim = tmp_path / "victim.txt"
    victim.write_text("original", encoding="utf-8")
    dest = tmp_path / "end_state"
    dest.mkdir()
    (dest / "note.txt").symlink_to(victim)

    with pytest.raises(ValueError):
        snapshot_end_state(case_dir, workdir, [], dest)

    assert victim.read_text(encoding="utf-8") == "original"


def test_snapshot_end_state_refuses_a_dangling_symlink_in_dest(tmp_path):
    case_dir = _snapshot_case(tmp_path, '{"note.txt": "new"}')
    workdir = tmp_path / "workdir"
    workdir.mkdir()
    dest = tmp_path / "end_state"
    dest.mkdir()
    target = tmp_path / "created-by-attack.txt"
    (dest / "note.txt").symlink_to(target)

    with pytest.raises(ValueError):
        snapshot_end_state(case_dir, workdir, [], dest)

    assert not target.exists()


def test_snapshot_end_state_refuses_a_dest_that_is_itself_a_symlink(tmp_path):
    case_dir = _snapshot_case(tmp_path, '{"note.txt": "new"}')
    workdir = tmp_path / "workdir"
    workdir.mkdir()
    elsewhere = tmp_path / "elsewhere"
    elsewhere.mkdir()
    dest = tmp_path / "end_state"
    dest.symlink_to(elsewhere)

    with pytest.raises(ValueError):
        snapshot_end_state(case_dir, workdir, [], dest)

    assert list(elsewhere.iterdir()) == []
