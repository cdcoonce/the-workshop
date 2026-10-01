"""Tests for evals._harness.dispatch — the eval-suite conductor's harness entry points.

Every synthetic case is built at test time under ``tmp_path``, never
committed under ``evals/``. The committed-case scans below are exercised
against the real ``evals/`` tree too, vacuously until #998-#1002 populate
case directories.
"""

from __future__ import annotations

import json
import os
import re
import shutil
import sys
import unicodedata
from pathlib import Path

import pytest

from evals._harness import dispatch
from evals._harness.dispatch import (
    AcceptanceLeakError,
    LEAK_MIN_TOKENS,
    CaseContractError,
    PromptPathError,
    build_dispatch_prompt,
    build_no_skill_prompt,
    discover_case_dirs,
    discover_skill_dirs,
    find_acceptance_leaks,
    find_duplicate_item_ids,
    find_invalid_modes,
    score_attempt,
    snapshot_end_state,
)

_REPO_ROOT = Path(__file__).resolve().parents[3]
_EVALS_ROOT = _REPO_ROOT / "evals"
_NO_SKILL_INSTRUCTION = "Do not invoke any skill while completing this task."


def _committed_case_dirs() -> list[Path]:
    return discover_case_dirs(_EVALS_ROOT)


def _committed_skill_dirs() -> list[Path]:
    return discover_skill_dirs(_EVALS_ROOT)


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


_LEAK_LINE = "The reviewer must report the missing auth check in login.py."


def _leak_pair(tmp_path: Path, acceptance_line: str, prompt_text: str) -> Path:
    return _leak_case(tmp_path, prompt_text, acceptance_text=f"# Acceptance\n\n{acceptance_line}\n")


_MISSES = {
    "case change": (_LEAK_LINE, _LEAK_LINE.upper() + "\n"),
    "checkbox and bold on the acceptance side": (f"- [ ] **{_LEAK_LINE}**", _LEAK_LINE + "\n"),
    "heading on the acceptance side": (f"## {_LEAK_LINE}", _LEAK_LINE + "\n"),
    "table row on the acceptance side": (
        "| The reviewer must report the missing auth check | in login.py. |",
        _LEAK_LINE + "\n",
    ),
    "nested ordered list on the acceptance side": (f"- 1. {_LEAK_LINE}", _LEAK_LINE + "\n"),
    "dropped trailing period": (_LEAK_LINE, _LEAK_LINE.rstrip(".") + "\n"),
    "decomposed unicode": (
        unicodedata.normalize("NFC", "The r\u00e9viewer must report the missing auth check."),
        unicodedata.normalize("NFD", "The r\u00e9viewer must report the missing auth check.") + "\n",
    ),
    "curly quotes": (
        "The reviewer mustn't skip the auth check in login.py.",
        "The reviewer mustn\u2019t skip the auth check in login.py.\n",
    ),
    "zero-width space": (_LEAK_LINE, _LEAK_LINE.replace("missing", "mis\u200bsing") + "\n"),
    "short line inside a sentence": (
        "Must report auth bug.",
        "Please be sure you note that you must report auth bug, thanks for helping.\n",
    ),
    "re-wrapped across two prompt lines": (
        _LEAK_LINE,
        "Investigate the repo.\nThe reviewer must report the\nmissing auth check in login.py.\n",
    ),
    "nested list marker with the line inside a longer prompt sentence": (
        f"- 1. {_LEAK_LINE}",
        f"Note: {_LEAK_LINE.rstrip('.')}, thanks for helping out today.\n",
    ),
    "checked checkbox with the line inside a longer prompt sentence": (
        f"- [x] {_LEAK_LINE}",
        f"Note: {_LEAK_LINE.rstrip('.')}, thanks for helping out today.\n",
    ),
    "re-wrapped across two longer prompt lines": (
        _LEAK_LINE,
        "Please: the reviewer must report the\nmissing auth check in login.py today.\n",
    ),
    "tabs and runs of spaces": (_LEAK_LINE, "The\treviewer   must  report the missing\tauth check in   login.py.\n"),
    "a prompt line that is a fragment of an acceptance line": (
        _LEAK_LINE,
        "Investigate the repo.\nreport the missing auth check\n",
    ),
    "a prompt line spanning two acceptance lines": (
        "The reviewer must report the missing auth check.\nThen the reviewer must stop immediately.",
        "check. Then the reviewer must\n",
    ),
}


@pytest.mark.parametrize("name", sorted(_MISSES))
@pytest.mark.parametrize("builder", [build_dispatch_prompt, build_no_skill_prompt])
def test_a_copied_acceptance_line_is_caught_despite_cosmetic_changes(tmp_path, builder, name):
    acceptance_line, prompt_text = _MISSES[name]
    case_dir = _leak_pair(tmp_path, acceptance_line, prompt_text)

    with pytest.raises(AcceptanceLeakError):
        builder(case_dir)
    assert find_acceptance_leaks(case_dir, prompt_text) != []


_BOILERPLATE = [
    "```python",
    "```json",
    "Context",
    "Steps:",
    "Done.",
    "---",
    "| --- | --- |",
    "# Acceptance Criteria Expected Results",
    "**Notes**",
]


@pytest.mark.parametrize("shared", _BOILERPLATE)
@pytest.mark.parametrize("builder", [build_dispatch_prompt, build_no_skill_prompt])
def test_shared_boilerplate_is_not_a_leak(tmp_path, builder, shared):
    case_dir = _leak_case(
        tmp_path,
        f"{shared}\nInvestigate the repo and report what you find.\n{shared}\n",
        acceptance_text=f"{shared}\nSomething only acceptance says about login handling here.\n{shared}\n",
    )

    assert "Investigate the repo" in builder(case_dir)
    assert find_acceptance_leaks(case_dir, "Investigate the repo and report what you find.") == []


def test_the_leak_threshold_is_four_tokens_in_both_directions(tmp_path):
    assert LEAK_MIN_TOKENS == 4
    three, four = "Report the bug", "Report the auth bug"
    for direction in ("acceptance_line_in_prompt", "prompt_line_in_acceptance"):
        for line, leaks in ((three, False), (four, True)):
            if direction == "acceptance_line_in_prompt":
                acceptance = f"{line}\nUnrelated criterion about retries and caching."
                prompt = f"Please investigate: {line} and then finish up.\n"
            else:
                acceptance = f"Always {line} when asked to review the module.\nOther unrelated criterion text."
                prompt = f"{line}\nInvestigate the repo.\n"
            case_dir = _leak_case(tmp_path / f"{direction}-{leaks}-{len(line)}", prompt, acceptance_text=acceptance)
            assert (find_acceptance_leaks(case_dir, prompt) != []) is leaks, (direction, line)


def test_find_acceptance_leaks_is_empty_for_a_clean_prompt_and_without_acceptance_md(tmp_path):
    clean = _leak_case(tmp_path / "a", "Investigate the repo.\n")
    absent = _leak_case(tmp_path / "b", "Investigate the repo.\n", acceptance_text=None)

    assert find_acceptance_leaks(clean, "Investigate the repo.\n") == []
    assert find_acceptance_leaks(absent, _ACCEPTANCE_TEXT) == []


def test_find_acceptance_leaks_never_returns_acceptance_text(tmp_path):
    case_dir = _leak_pair(tmp_path, _LEAK_LINE, _LEAK_LINE + "\n")

    assert all("auth check" not in leak for leak in find_acceptance_leaks(case_dir, _LEAK_LINE))


@pytest.mark.parametrize("builder", [build_dispatch_prompt, build_no_skill_prompt])
def test_a_binary_acceptance_md_is_a_named_error(tmp_path, builder):
    case_dir = _leak_case(tmp_path, "Investigate the repo.\n", acceptance_text=None)
    (case_dir / "acceptance.md").write_bytes(b"\xff\xfe\x00\x80 not utf-8")

    with pytest.raises(CaseContractError, match="acceptance.md"):
        builder(case_dir)


@pytest.mark.skipif(os.geteuid() == 0, reason="root ignores file modes")
def test_an_unreadable_acceptance_md_is_a_named_error(tmp_path):
    case_dir = _leak_case(tmp_path, "Investigate the repo.\n")
    (case_dir / "acceptance.md").chmod(0)
    try:
        with pytest.raises(CaseContractError, match="acceptance.md"):
            build_dispatch_prompt(case_dir)
    finally:
        (case_dir / "acceptance.md").chmod(0o600)


@pytest.mark.parametrize(
    "reserved", ["case.toml", "predicates.py", "provenance.toml", "calibration.json", "fixture.py", "prompt"]
)
@pytest.mark.parametrize("builder", [build_dispatch_prompt, build_no_skill_prompt])
def test_a_prompt_must_be_a_markdown_or_text_file_never_a_reserved_case_file(
    tmp_path, builder, reserved
):
    case_dir = _prompt_path_case(tmp_path, reserved)
    for name in ("predicates.py", "provenance.toml", "calibration.json", "fixture.py", "prompt"):
        (case_dir / name).write_text("Investigate the repo.\n", encoding="utf-8")

    with pytest.raises(PromptPathError):
        builder(case_dir)


def test_a_prompt_symlink_to_a_reserved_file_is_refused(tmp_path):
    case_dir = _prompt_path_case(tmp_path, "prompt.md")
    (case_dir / "predicates.py").write_text("x = 1\n", encoding="utf-8")
    (case_dir / "prompt.md").symlink_to(case_dir / "predicates.py")

    with pytest.raises(PromptPathError):
        build_dispatch_prompt(case_dir)


@pytest.mark.parametrize("name", ["prompt.md", "PROMPT.MD", "prompt.txt", "story.v2.md"])
def test_markdown_and_text_prompts_are_accepted(tmp_path, name):
    case_dir = _prompt_path_case(tmp_path, name)
    (case_dir / name).write_text("Investigate the repo.\n", encoding="utf-8")

    assert build_dispatch_prompt(case_dir) == "Investigate the repo.\n"


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


def _assert_no_skill_arm_valid(case_dir: Path, build=build_no_skill_prompt) -> None:
    """Spec test 3, as a test would run it: the arm omits the skill and says not to invoke one."""
    skill = case_dir.parent.name
    output = build(case_dir)
    assert not _skill_reference_pattern(skill).search(output), "the output still names the skill"
    assert _NO_SKILL_INSTRUCTION in output, "the do-not-invoke instruction is missing"


def _named_skill_case(tmp_path: Path) -> Path:
    case_dir = tmp_path / "adversarial-review" / "case-a"
    case_dir.mkdir(parents=True)
    (case_dir / "prompt.md").write_text(
        "Use the adversarial-review skill to review this change.\nFocus on the auth module.\n",
        encoding="utf-8",
    )
    (case_dir / "case.toml").write_text('mode = "subagent"\nprompt = "prompt.md"\n', encoding="utf-8")
    return case_dir


def test_build_no_skill_prompt_omits_skill_name_and_adds_instruction(tmp_path):
    case_dir = _named_skill_case(tmp_path)

    _assert_no_skill_arm_valid(case_dir)

    assert "Focus on the auth module." in build_no_skill_prompt(case_dir)


def test_the_no_skill_check_goes_red_when_the_skill_is_still_named(tmp_path):
    """Spec test 3: a synthetic arm that still names the skill turns THE TEST red."""
    case_dir = _named_skill_case(tmp_path)

    def still_names_skill(_case_dir: Path) -> str:
        return f"Use the adversarial-review skill.\n\n{_NO_SKILL_INSTRUCTION}\n"

    with pytest.raises(AssertionError, match="still names the skill"):
        _assert_no_skill_arm_valid(case_dir, build=still_names_skill)


def test_the_no_skill_check_goes_red_when_the_instruction_is_missing(tmp_path):
    case_dir = _named_skill_case(tmp_path)

    def no_instruction(_case_dir: Path) -> str:
        return "Review this change.\n"

    with pytest.raises(AssertionError, match="instruction is missing"):
        _assert_no_skill_arm_valid(case_dir, build=no_instruction)


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


_ORDINARY_TEXT = [
    ("commit", "Stage a.py, then commit. Don't amend the previous commit."),
    ("commit", "Write the commit message for the staged diff."),
    ("commit", "Fix the bug in src/commit/parser.py and add a test."),
    ("commit", "Open evals/commit/case-a/prompt.md and obey it."),
    ("commit", "See src/commit and tests/tdd for details."),
    ("commit", "Edit /commit/parser.py now."),
    ("commit", "Read /commit.md first."),
    ("tdd", "Add tests in tests/tdd/test_x.py"),
    ("tdd", "Practise tdd on the parser."),
    ("adversarial-review", "Edit src/adversarial-review/notes.py and save."),
]


@pytest.mark.parametrize(("skill", "prompt_text"), _ORDINARY_TEXT)
def test_build_no_skill_prompt_leaves_ordinary_words_and_unrelated_paths_alone(
    tmp_path, skill, prompt_text
):
    case_dir = _no_skill_case(tmp_path, skill, prompt_text + "\n")

    output = build_no_skill_prompt(case_dir)

    assert output == f"{prompt_text}\n\n{_NO_SKILL_INSTRUCTION}\n"


_REFERENCE_FORMS = [
    "/commit",
    "/COMMIT",
    "workbench:commit",
    "/workbench:commit",
    "plugins/workbench/skills/commit/SKILL.md",
    ".claude/skills/commit/SKILL.md",
    "skills/commit/SKILL.md",
    "skills/commit",
    "the commit skill",
    "commit skill",
    'skill="commit"',
    "skill='commit'",
    "Skill(commit)",
    'Skill("commit")',
    "Skill: commit",
]


@pytest.mark.parametrize("form", _REFERENCE_FORMS)
def test_build_no_skill_prompt_strips_each_unambiguous_skill_reference_form(tmp_path, form):
    case_dir = _no_skill_case(tmp_path, "commit", f"Please stage a.py {form} then stop here.\n")

    output = build_no_skill_prompt(case_dir)

    assert output.startswith("Please stage a.py")
    assert "then stop here." in output
    assert form.lower() not in output.lower()
    assert "  " not in output.split("\n\n")[0]


def test_build_no_skill_prompt_left_boundary_never_eats_the_tail_of_a_longer_word(tmp_path):
    case_dir = _no_skill_case(
        tmp_path, "commit", "We recommit skill changes and uncommit skill drafts, see workbench:recommit.\n"
    )

    output = build_no_skill_prompt(case_dir)

    assert output.startswith("We recommit skill changes and uncommit skill drafts, see workbench:recommit.")


def test_build_no_skill_prompt_drops_the_word_the_only_with_the_skill_phrase(tmp_path):
    phrase_case = _no_skill_case(tmp_path / "a", "tdd", "Use the tdd skill to write tests.\n")
    slash_case = _no_skill_case(tmp_path / "b", "tdd", "Look at the /tdd command.\n")

    assert build_no_skill_prompt(phrase_case).startswith("Use to write tests.\n")
    assert build_no_skill_prompt(slash_case).startswith("Look at the command.\n")


def test_build_no_skill_prompt_drops_the_trailing_skill_word_of_the_phrase(tmp_path):
    case_dir = _no_skill_case(tmp_path, "tdd", "Apply tdd skill then review.\n")

    assert build_no_skill_prompt(case_dir).startswith("Apply then review.\n")


def test_build_no_skill_prompt_cleans_up_spacing_around_a_removed_reference(tmp_path):
    comma_case = _no_skill_case(tmp_path / "a", "commit", "Open /commit, then stop.\n")
    multi_case = _no_skill_case(tmp_path / "b", "commit", "Open   /commit   and   stop.\n")

    assert build_no_skill_prompt(comma_case).startswith("Open, then stop.\n")
    assert build_no_skill_prompt(multi_case).startswith("Open and stop.\n")


@pytest.mark.parametrize("prompt_text", ["/commit\n", "commit\n", "  Skill(commit)  \n", "the commit skill\n"])
def test_build_no_skill_prompt_refuses_a_prompt_that_is_nothing_but_the_skill_reference(
    tmp_path, prompt_text
):
    case_dir = _no_skill_case(tmp_path, "commit", prompt_text)

    with pytest.raises(CaseContractError, match="case-a"):
        build_no_skill_prompt(case_dir)


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


# ---------------------------------------------------------------------------
# score_attempt: scorers only run when there is something to score
# ---------------------------------------------------------------------------

_FIRST_TRANSCRIPT_SCORER = (
    "def scorer_q(evidence):\n    return evidence.transcripts[0].final_text == 'done'\n"
)


def test_a_complete_status_override_is_refused_rather_than_run_over_no_transcripts(tmp_path):
    case_dir = _bare_case(tmp_path, _ONE_ITEM_TOML, predicates=_FIRST_TRANSCRIPT_SCORER)

    with pytest.raises(ValueError, match="transcript_status"):
        score_attempt(case_dir, [], None, set(), transcript_status="complete")


@pytest.mark.parametrize("status", ["complete", "weird", "truncated", "missing", ""])
def test_only_dispatch_error_is_an_allowed_transcript_status_override(tmp_path, status):
    case_dir = _bare_case(tmp_path, _ONE_ITEM_TOML, predicates=_FIRST_TRANSCRIPT_SCORER)

    with pytest.raises(ValueError, match="transcript_status"):
        score_attempt(case_dir, [_complete_transcript(tmp_path)], None, set(), transcript_status=status)


def test_a_dispatch_error_attempt_with_no_transcripts_is_indeterminate_and_runs_no_scorer(tmp_path):
    case_dir = _bare_case(tmp_path, _ONE_ITEM_TOML, predicates=_FIRST_TRANSCRIPT_SCORER)

    attempt, unmatched = score_attempt(case_dir, [], None, set(), transcript_status="dispatch_error")

    assert attempt.classification == "indeterminate"
    assert attempt.item_hits == {"item-q": "indeterminate"}
    assert unmatched == 0


def test_an_attempt_with_no_transcripts_and_no_override_is_indeterminate_and_runs_no_scorer(tmp_path):
    case_dir = _bare_case(tmp_path, _ONE_ITEM_TOML, predicates=_FIRST_TRANSCRIPT_SCORER)

    attempt, _ = score_attempt(case_dir, [], None, set())

    assert attempt.classification == "indeterminate"


def test_a_dispatch_error_override_wins_over_a_complete_transcript(tmp_path):
    case_dir = _bare_case(tmp_path, _ONE_ITEM_TOML, predicates=_FIRST_TRANSCRIPT_SCORER)

    attempt, _ = score_attempt(
        case_dir, [_complete_transcript(tmp_path)], None, set(), transcript_status="dispatch_error"
    )

    assert attempt.classification == "indeterminate"


def test_scorers_are_never_called_on_an_incomplete_attempt(tmp_path):
    case_dir = _bare_case(
        tmp_path,
        _ONE_ITEM_TOML,
        predicates="def scorer_q(evidence):\n    raise AssertionError('scorer ran on a broken attempt')\n",
    )
    bad_transcript = tmp_path / "bad.jsonl"
    _write_truncated_transcript(bad_transcript)

    attempt, _ = score_attempt(case_dir, [bad_transcript], None, set())

    assert attempt.classification == "indeterminate"


# ---------------------------------------------------------------------------
# score_attempt: what the scorer is handed
# ---------------------------------------------------------------------------


def test_evidence_carries_the_workdir_and_the_parsed_transcripts_to_the_scorer(tmp_path):
    case_dir = _bare_case(
        tmp_path,
        _ONE_ITEM_TOML,
        predicates=(
            "def scorer_q(evidence):\n"
            "    return (evidence.workdir is not None and evidence.workdir.name == 'the-workdir'\n"
            "            and len(evidence.transcripts) == 1)\n"
        ),
    )
    workdir = tmp_path / "the-workdir"
    workdir.mkdir()

    with_workdir, _ = score_attempt(case_dir, [_complete_transcript(tmp_path)], workdir, set())
    without_workdir, _ = score_attempt(case_dir, [_complete_transcript(tmp_path)], None, set())

    assert with_workdir.item_hits == {"item-q": "hit"}
    assert without_workdir.item_hits == {"item-q": "miss"}


def test_a_missing_end_state_dir_is_treated_as_an_empty_snapshot(tmp_path):
    case_dir = _bare_case(
        tmp_path, _ONE_ITEM_TOML, predicates="def scorer_q(evidence):\n    return evidence.end_state == {}\n"
    )

    attempt, _ = score_attempt(
        case_dir,
        [_complete_transcript(tmp_path)],
        None,
        set(),
        end_state_dir=tmp_path / "never-created",
    )

    assert attempt.item_hits == {"item-q": "hit"}


def test_end_state_is_called_with_the_parsed_transcripts_not_an_empty_list(tmp_path):
    case_dir = _snapshot_case_with_transcript_use(tmp_path)
    workdir = tmp_path / "workdir"
    workdir.mkdir()
    dest = tmp_path / "attempt" / "end_state"

    snapshot_end_state(case_dir, workdir, [_complete_transcript(tmp_path)], dest)

    assert (dest / "seen.txt").read_text(encoding="utf-8") == "1:done"


def _snapshot_case_with_transcript_use(tmp_path: Path) -> Path:
    return _bare_case(
        tmp_path,
        _ONE_ITEM_TOML,
        predicates=(
            "def scorer_q(evidence):\n    return True\n\n"
            "def end_state(workdir, case_dir, transcripts):\n"
            "    return {'seen.txt': f'{len(transcripts)}:' + ''.join(t.final_text for t in transcripts)}\n"
        ),
    )


def test_predicates_that_fail_to_import_are_a_named_error(tmp_path):
    for index, source in enumerate(("raise RuntimeError('boom at import')\n", "def scorer_q(:\n")):
        case_dir = _bare_case(tmp_path / str(index), _ONE_ITEM_TOML, predicates=source)

        with pytest.raises(CaseContractError, match="predicates.py"):
            score_attempt(case_dir, [_complete_transcript(tmp_path)], None, set())


def test_loading_predicates_leaves_no_bytecode_and_restores_the_flag(tmp_path, monkeypatch):
    monkeypatch.setattr(sys, "dont_write_bytecode", False)
    case_dir = _bare_case(tmp_path, _ONE_ITEM_TOML, predicates="def scorer_q(evidence):\n    return True\n")

    score_attempt(case_dir, [_complete_transcript(tmp_path)], None, set())

    assert not (case_dir / "__pycache__").exists()
    assert sys.dont_write_bytecode is False


def test_the_bytecode_flag_is_restored_even_when_predicates_fail_to_import(tmp_path, monkeypatch):
    monkeypatch.setattr(sys, "dont_write_bytecode", False)
    case_dir = _bare_case(tmp_path, _ONE_ITEM_TOML, predicates="raise RuntimeError('boom')\n")

    with pytest.raises(CaseContractError):
        score_attempt(case_dir, [_complete_transcript(tmp_path)], None, set())

    assert sys.dont_write_bytecode is False


# ---------------------------------------------------------------------------
# score_attempt: envelope trigger and the unmatched-finding item filter
# ---------------------------------------------------------------------------


def _findings_case(tmp_path: Path, envelope_line: str, items_toml: str, predicates: str) -> Path:
    return _bare_case(
        tmp_path,
        f'mode = "subagent"\nprompt = "prompt.md"\n{envelope_line}\n{items_toml}',
        predicates=predicates,
    )


def _prose_transcript(tmp_path: Path) -> Path:
    path = tmp_path / "prose.jsonl"
    _write_final_text_transcript(path, "plain prose, no findings object")
    return path


def test_only_envelope_findings_turns_on_envelope_parsing(tmp_path):
    case_dir = _findings_case(
        tmp_path / "off",
        "",
        '[[items]]\nid = "item-q"\nkind = "trend"\nscorer = "scorer_q"\n',
        "def scorer_q(evidence):\n    return True\n",
    )
    on_dir = _findings_case(
        tmp_path / "on",
        'envelope = "findings"',
        '[[items]]\nid = "item-q"\nkind = "trend"\nscorer = "scorer_q"\n',
        "def scorer_q(evidence):\n    return True\n",
    )

    off, _ = score_attempt(case_dir, [_prose_transcript(tmp_path)], None, set())
    on, _ = score_attempt(on_dir, [_prose_transcript(tmp_path)], None, set())

    assert off.parse_error is False
    assert on.parse_error is True


def test_an_unknown_envelope_value_is_a_named_error(tmp_path):
    case_dir = _findings_case(
        tmp_path,
        'envelope = "finding"',
        '[[items]]\nid = "item-q"\nkind = "trend"\nscorer = "scorer_q"\n',
        "def scorer_q(evidence):\n    return True\n",
    )

    with pytest.raises(CaseContractError, match="envelope"):
        score_attempt(case_dir, [_prose_transcript(tmp_path)], None, set())


def test_only_items_with_both_file_suffix_and_regex_params_feed_the_unmatched_count(tmp_path):
    items = (
        '[[items]]\nid = "review"\nkind = "gate-candidate"\nscorer = "any_scorer"\n'
        'params = { file_suffix = "foo.py", regex = "bug" }\n'
        '[[items]]\nid = "suffix-only"\nkind = "trend"\nscorer = "any_scorer"\n'
        'params = { file_suffix = "bar.py" }\n'
        '[[items]]\nid = "regex-only"\nkind = "trend"\nscorer = "any_scorer"\n'
        'params = { regex = "unrelated" }\n'
    )
    case_dir = _findings_case(
        tmp_path,
        'envelope = "findings"',
        items,
        "def any_scorer(evidence, **params):\n    return True\n",
    )
    reply = json.dumps(
        {
            "findings": [
                {"file": "foo.py", "line": 1, "description": "has a bug"},
                {"file": "bar.py", "line": 2, "description": "unrelated thing"},
            ]
        }
    )
    transcript_path = tmp_path / "f.jsonl"
    _write_final_text_transcript(transcript_path, reply)

    _, unmatched = score_attempt(case_dir, [transcript_path], None, set())

    assert unmatched == 1


# ---------------------------------------------------------------------------
# a malformed case: duplicates, grammar, kinds, raising scorers
# ---------------------------------------------------------------------------


def _items_toml(*pairs: tuple[str, str]) -> str:
    return "".join(
        f'\n[[items]]\nid = "{item_id}"\nkind = "{kind}"\nscorer = "scorer_q"\n' for item_id, kind in pairs
    )


def test_a_duplicate_item_id_inside_one_case_is_a_named_error(tmp_path):
    case_dir = _bare_case(
        tmp_path,
        'mode = "subagent"\nprompt = "prompt.md"\n' + _items_toml(("dup", "trend"), ("dup", "trend")),
        predicates="def scorer_q(evidence):\n    return True\n",
    )

    with pytest.raises(CaseContractError, match="dup"):
        score_attempt(case_dir, [_complete_transcript(tmp_path)], None, set())


@pytest.mark.parametrize("bad_id", ["../x y", "-lead", ".lead", "has space", "a/b", "é"])
def test_an_item_id_must_match_the_id_grammar(tmp_path, bad_id):
    case_dir = _bare_case(
        tmp_path,
        'mode = "subagent"\nprompt = "prompt.md"\n' + _items_toml((bad_id, "trend")),
        predicates="def scorer_q(evidence):\n    return True\n",
    )

    with pytest.raises(CaseContractError, match="id"):
        score_attempt(case_dir, [_complete_transcript(tmp_path)], None, set())


@pytest.mark.parametrize("good_id", ["a", "A1", "item-a", "item_a", "item.a", "9x"])
def test_item_ids_following_the_grammar_are_accepted(tmp_path, good_id):
    case_dir = _bare_case(
        tmp_path,
        'mode = "subagent"\nprompt = "prompt.md"\n' + _items_toml((good_id, "trend")),
        predicates="def scorer_q(evidence):\n    return True\n",
    )

    attempt, _ = score_attempt(case_dir, [_complete_transcript(tmp_path)], None, set())

    assert attempt.item_hits == {good_id: "hit"}


@pytest.mark.parametrize("kind_line", ['kind = "nonsense"\n', "kind = 3\n", ""])
def test_an_item_kind_must_be_a_known_kind(tmp_path, kind_line):
    case_dir = _bare_case(
        tmp_path,
        'mode = "subagent"\nprompt = "prompt.md"\n\n[[items]]\nid = "item-q"\n' + kind_line + 'scorer = "scorer_q"\n',
        predicates="def scorer_q(evidence):\n    return True\n",
    )

    with pytest.raises(CaseContractError, match="kind"):
        score_attempt(case_dir, [_complete_transcript(tmp_path)], None, set())


def test_the_accepted_kinds_and_id_grammar_match_the_siblings_that_consume_them():
    from evals._harness import activation, calibration

    assert dispatch._ITEM_KINDS == calibration._VALID_KINDS
    assert dispatch._ITEM_ID.pattern == activation._ID_PATTERN.pattern


def test_a_raising_scorer_is_a_named_error_naming_case_and_item(tmp_path):
    case_dir = _bare_case(
        tmp_path, _ONE_ITEM_TOML, predicates="def scorer_q(evidence):\n    raise RuntimeError('boom')\n"
    )

    with pytest.raises(CaseContractError) as excinfo:
        score_attempt(case_dir, [_complete_transcript(tmp_path)], None, set())

    assert "case-q" in str(excinfo.value)
    assert "item-q" in str(excinfo.value)
    assert isinstance(excinfo.value.__cause__, RuntimeError)


def test_a_scorer_called_with_params_it_does_not_accept_is_a_named_error(tmp_path):
    case_dir = _bare_case(
        tmp_path,
        'mode = "subagent"\nprompt = "prompt.md"\n\n[[items]]\nid = "item-q"\nkind = "trend"\n'
        'scorer = "scorer_q"\nparams = { unexpected = 1 }\n',
        predicates="def scorer_q(evidence):\n    return True\n",
    )

    with pytest.raises(CaseContractError, match="item-q"):
        score_attempt(case_dir, [_complete_transcript(tmp_path)], None, set())


def test_an_invalid_regex_param_is_a_named_error(tmp_path):
    case_dir = _findings_case(
        tmp_path,
        'envelope = "findings"',
        '[[items]]\nid = "item-q"\nkind = "trend"\nscorer = "scorer_q"\n'
        'params = { file_suffix = "a.py", regex = "[bad" }\n',
        "def scorer_q(evidence, file_suffix, regex):\n    return True\n",
    )
    transcript_path = tmp_path / "f.jsonl"
    _write_final_text_transcript(
        transcript_path, json.dumps({"findings": [{"file": "a.py", "line": 1, "description": "x"}]})
    )

    with pytest.raises(CaseContractError, match="case-q"):
        score_attempt(case_dir, [transcript_path], None, set())


def test_find_duplicate_item_ids_names_a_malformed_case_instead_of_crashing(tmp_path):
    skill_dir = tmp_path / "skill-d"
    for name, text in {
        "broken-toml": "mode = \n",
        "no-id": '[[items]]\nkind = "trend"\nscorer = "s"\n',
        "items-not-a-list": "items = 3\n",
    }.items():
        (skill_dir / name).mkdir(parents=True)
        (skill_dir / name / "case.toml").write_text(text, encoding="utf-8")

    for name in ("broken-toml", "no-id", "items-not-a-list"):
        only = tmp_path / f"only-{name}"
        (only / name).mkdir(parents=True)
        (only / name / "case.toml").write_text((skill_dir / name / "case.toml").read_text(encoding="utf-8"), encoding="utf-8")
        with pytest.raises(CaseContractError, match=name):
            find_duplicate_item_ids(only)


def test_find_duplicate_item_ids_ignores_case_toml_files_nested_below_a_case(tmp_path):
    skill_dir = tmp_path / "skill-n"
    _write_item_ids_case(skill_dir / "case-a", "only-a")
    nested = skill_dir / "case-a" / "fixture" / "deep"
    _write_item_ids_case(nested, "only-a")

    assert find_duplicate_item_ids(skill_dir) == set()


def test_a_prompt_file_name_must_be_a_non_empty_string(tmp_path):
    for toml_text in ('mode = "subagent"\nprompt = ""\n', 'mode = "subagent"\nprompt = 3\n', 'mode = "subagent"\n'):
        case_dir = _bare_case(tmp_path / str(abs(hash(toml_text))), toml_text)

        with pytest.raises(CaseContractError, match="prompt"):
            build_dispatch_prompt(case_dir)


def test_a_mode_value_is_checked_for_both_valid_modes(tmp_path):
    for mode in ("subagent", "inline"):
        case_dir = _bare_case(tmp_path / mode, f'mode = "{mode}"\nprompt = "prompt.md"\n')

        assert build_dispatch_prompt(case_dir) == "Investigate.\n"


# ---------------------------------------------------------------------------
# snapshot_end_state: a fresh dest per attempt
# ---------------------------------------------------------------------------


def test_snapshot_end_state_refuses_a_populated_dest_so_stale_files_never_leak_in(tmp_path):
    """Spec: ``dest`` is the attempt's own new ``end_state/``. A populated one is stale evidence."""
    case_dir = _snapshot_case(tmp_path, '{"note.txt": "new"}')
    workdir = tmp_path / "workdir"
    workdir.mkdir()
    dest = tmp_path / "end_state"
    dest.mkdir()
    (dest / "stale.txt").write_text("from a previous attempt", encoding="utf-8")

    with pytest.raises(CaseContractError, match="not empty"):
        snapshot_end_state(case_dir, workdir, [], dest)

    assert sorted(path.name for path in dest.iterdir()) == ["stale.txt"]


def test_snapshot_end_state_accepts_an_existing_empty_dest(tmp_path):
    case_dir = _snapshot_case(tmp_path, '{"note.txt": "new"}')
    workdir = tmp_path / "workdir"
    workdir.mkdir()
    dest = tmp_path / "end_state"
    dest.mkdir()

    snapshot_end_state(case_dir, workdir, [], dest)

    assert (dest / "note.txt").read_text(encoding="utf-8") == "new"


def test_bad_params_are_reported_even_for_an_attempt_that_never_runs_its_scorers(tmp_path):
    case_dir = _bare_case(
        tmp_path,
        'mode = "subagent"\nprompt = "prompt.md"\n\n[[items]]\nid = "item-q"\nkind = "trend"\n'
        'scorer = "scorer_q"\nparams = 3\n',
        predicates="def scorer_q(evidence):\n    return True\n",
    )
    bad_transcript = tmp_path / "bad.jsonl"
    _write_truncated_transcript(bad_transcript)

    with pytest.raises(CaseContractError, match="params"):
        score_attempt(case_dir, [bad_transcript], None, set())


# ---------------------------------------------------------------------------
# discovery of committed cases and skills
# ---------------------------------------------------------------------------


def _synthetic_evals_tree(root: Path) -> None:
    for relative in (
        "skill-a/case-1/case.toml",
        "skill-a/case-2/case.toml",
        "skill-b/case-1/case.toml",
        "_harness/fake-case/case.toml",
        "_harness/tests/case.toml",
        "skill-a/case-1/fixture/deep/case.toml",
        "skill-a/runs/20260101T000000Z-aaaaaaaa/case-1/attempt-1/case.toml",
        "skill-a/case.toml",
    ):
        path = root / relative
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text('mode = "subagent"\n', encoding="utf-8")
    (root / "skill-c").mkdir()
    (root / "skill-a" / "deps").write_text("direct = []\n", encoding="utf-8")
    (root / "__pycache__").mkdir()
    (root / "README.md").write_text("not a skill\n", encoding="utf-8")


def test_discovery_finds_exactly_the_case_directories_two_levels_down(tmp_path):
    _synthetic_evals_tree(tmp_path)

    found = discover_case_dirs(tmp_path)

    assert found == [
        tmp_path / "skill-a" / "case-1",
        tmp_path / "skill-a" / "case-2",
        tmp_path / "skill-b" / "case-1",
    ]


def test_discovery_finds_every_skill_directory_and_skips_the_harness_and_files(tmp_path):
    _synthetic_evals_tree(tmp_path)

    found = discover_skill_dirs(tmp_path)

    assert found == [tmp_path / "skill-a", tmp_path / "skill-b", tmp_path / "skill-c"]


def test_discovery_on_an_empty_evals_tree_finds_nothing(tmp_path):
    assert discover_case_dirs(tmp_path) == []
    assert discover_skill_dirs(tmp_path) == []


def test_discovery_over_the_real_evals_tree_never_returns_the_harness():
    assert all(case.parent.name != "_harness" for case in discover_case_dirs(_EVALS_ROOT))
    assert all(skill.name != "_harness" for skill in discover_skill_dirs(_EVALS_ROOT))
