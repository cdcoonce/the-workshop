"""A2's dispatch prompts: no leakage of acceptance.md, and a plain no-skill reviewer.

The inline run dispatches three lens agents, each given the text
``build_dispatch_prompt`` returns. The no-skill arm is ONE plain reviewer given
``build_no_skill_prompt``'s output: one agent, one pass over the whole diff, no
lens split. None of adversarial-review's own words (``SKILL.md``,
``references/*.md``) may reach it, or the baseline would measure the skill.

Both guards are shown to bite: a synthetic copy of the case whose prompt really
embeds a line of the private text is refused or flagged.
"""

from __future__ import annotations

import re
import shutil
import unicodedata
from pathlib import Path

import pytest

from evals._harness.dispatch import (
    AcceptanceLeakError,
    build_dispatch_prompt,
    build_no_skill_prompt,
    find_acceptance_leaks,
)

_SKILL_DIR = "plugins/workbench/skills/adversarial-review"
_NO_SKILL_INSTRUCTION = "Do not invoke any skill while completing this task."
_MIN_TOKENS = 4  # a shared run shorter than this is boilerplate, as in the harness's own leak guard
_TOKEN = re.compile(r"[^\W_]+")


def _tokens(text: str) -> list[str]:
    folded = unicodedata.normalize("NFKC", text).casefold()
    return _TOKEN.findall("".join(ch for ch in folded if unicodedata.category(ch) != "Cf"))


def _skill_texts(repo_root: Path) -> dict[str, str]:
    root = repo_root / _SKILL_DIR
    paths = [root / "SKILL.md", *sorted((root / "references").glob("*.md"))]
    assert len(paths) >= 2
    return {path.relative_to(root).as_posix(): path.read_text(encoding="utf-8") for path in paths}


def skill_text_hits(text: str, skill_texts: dict[str, str]) -> list[str]:
    """Where *text* carries a line of the skill's own files, in either direction.

    A skill line of at least four tokens that sits anywhere in *text*, and a
    text line of at least four tokens that is a contiguous piece of a skill
    file, both count. Tokens are casefolded alphanumerics, so markdown, quote
    style and re-wrapping change nothing.
    """
    hits = []
    text_lines = [_tokens(line) for line in text.splitlines()]
    text_stream = "\0" + "\0".join(token for line in text_lines for token in line) + "\0"
    for name, body in skill_texts.items():
        skill_lines = [_tokens(line) for line in body.splitlines()]
        skill_stream = "\0" + "\0".join(token for line in skill_lines for token in line) + "\0"
        for number, tokens in enumerate(skill_lines, start=1):
            if len(tokens) >= _MIN_TOKENS and "\0" + "\0".join(tokens) + "\0" in text_stream:
                hits.append(f"{name} line {number} appears in the text")
        for number, tokens in enumerate(text_lines, start=1):
            if len(tokens) >= _MIN_TOKENS and "\0" + "\0".join(tokens) + "\0" in skill_stream:
                hits.append(f"text line {number} reproduces {name}")
    return hits


def _long_line(text: str, *, minimum: int = 8) -> str:
    """The first body line of *text* with at least *minimum* tokens and no markdown table pipes."""
    for line in text.splitlines():
        if len(_tokens(line)) >= minimum and "|" not in line and not line.startswith("#"):
            return line
    raise AssertionError("no long line")


@pytest.fixture
def copied_case(case_dir, tmp_path):
    """A copy of A2 under ``<tmp>/adversarial-review/A2``, so the rostered skill name is the real one."""
    dest = tmp_path / "adversarial-review" / "A2"
    shutil.copytree(case_dir, dest, ignore=shutil.ignore_patterns("case_tests", "ab_raws", "__pycache__"))
    return dest


# --- the checker itself bites ------------------------------------------------------


def test_the_skill_text_checker_flags_a_real_skill_md_line(repo_root):
    skill = _skill_texts(repo_root)
    line = _long_line(skill["SKILL.md"])
    assert skill_text_hits(f"Please review this.\n{line}\n", skill)


def test_the_skill_text_checker_flags_a_real_references_line_even_rewrapped_and_bulleted(repo_root):
    skill = _skill_texts(repo_root)
    line = _long_line(skill["references/pr-lens-review.md"])
    assert skill_text_hits(f"- {line}", skill)
    assert skill_text_hits(f"> {line.upper()}", skill)


def test_the_skill_text_checker_is_quiet_on_a_plain_request(repo_root):
    assert skill_text_hits("Review this diff and report defects as JSON.", _skill_texts(repo_root)) == []


# --- the no-skill arm is one plain reviewer ------------------------------------------


def test_the_no_skill_prompt_is_the_case_prompt_plus_the_fixed_instruction(case_dir):
    prompt = (case_dir / "prompt.md").read_text(encoding="utf-8").strip()
    assert build_no_skill_prompt(case_dir) == f"{prompt}\n\n{_NO_SKILL_INSTRUCTION}\n"


def test_the_no_skill_prompt_names_no_skill(case_dir, repo_root):
    text = build_no_skill_prompt(case_dir).replace(_NO_SKILL_INSTRUCTION, "")
    assert not re.search(r"\bskills?\b", text, re.IGNORECASE)
    assert "adversarial-review" not in text.lower() and "adversarial review" not in text.lower()
    for skill_dir in (repo_root / "plugins/workbench/skills").iterdir():
        if "-" in skill_dir.name:
            assert skill_dir.name not in text, skill_dir.name


def test_the_no_skill_prompt_contains_no_line_of_the_skills_own_files(case_dir, repo_root):
    assert skill_text_hits(build_no_skill_prompt(case_dir), _skill_texts(repo_root)) == []


def test_the_dispatch_prompt_contains_no_line_of_the_skills_own_files_either(case_dir, repo_root):
    assert skill_text_hits(build_dispatch_prompt(case_dir), _skill_texts(repo_root)) == []


def test_a_prompt_that_really_embeds_a_skill_line_is_flagged_in_the_no_skill_output(copied_case, repo_root):
    skill = _skill_texts(repo_root)
    for name in ("SKILL.md", "references/pr-lens-review.md", "references/discipline.md"):
        prompt = copied_case / "prompt.md"
        original = prompt.read_text(encoding="utf-8")
        prompt.write_text(original + "\n" + _long_line(skill[name]) + "\n", encoding="utf-8")
        assert skill_text_hits(build_no_skill_prompt(copied_case), skill), name
        prompt.write_text(original, encoding="utf-8")
    assert skill_text_hits(build_no_skill_prompt(copied_case), skill) == []


def test_the_no_skill_arm_is_a_single_whole_diff_pass_with_no_lens_split(case_dir):
    text = build_no_skill_prompt(case_dir)
    assert not re.search(r"\blens(es)?\b|\bparallel\b|\brefuter|\bagents\b|\bsubagent", text, re.IGNORECASE)
    assert text.count("Reply with a single JSON object") == 1
    assert "diff.patch" in text and "spec.md" in text


def test_the_case_prompt_gives_every_lens_the_same_whole_review_request(case_dir):
    """All three lens agents get one text; the narrowing is the conductor's, from the skill."""
    assert build_dispatch_prompt(case_dir) == (case_dir / "prompt.md").read_text(encoding="utf-8")


# --- #995's dispatch-prompt-leakage guard passes, and is not vacuous here --------------


def test_no_dispatch_prompt_carries_acceptance_text(case_dir):
    for prompt in (build_dispatch_prompt(case_dir), build_no_skill_prompt(case_dir)):
        assert find_acceptance_leaks(case_dir, prompt) == []


def test_acceptance_md_exists_and_is_not_the_prompt(case_dir):
    acceptance = (case_dir / "acceptance.md").read_text(encoding="utf-8")
    assert acceptance.strip() and acceptance != (case_dir / "prompt.md").read_text(encoding="utf-8")


def test_a_prompt_that_really_embeds_an_acceptance_line_is_refused_by_both_builders(copied_case):
    acceptance = (copied_case / "acceptance.md").read_text(encoding="utf-8")
    line = _long_line(acceptance)
    prompt = copied_case / "prompt.md"
    prompt.write_text(prompt.read_text(encoding="utf-8") + "\n" + line + "\n", encoding="utf-8")
    with pytest.raises(AcceptanceLeakError):
        build_dispatch_prompt(copied_case)
    with pytest.raises(AcceptanceLeakError):
        build_no_skill_prompt(copied_case)


# --- the prompt is a plain whole-diff request that points at two files only --------------


def test_the_prompt_names_exactly_the_two_review_files_by_explicit_path(case_dir):
    prompt = (case_dir / "prompt.md").read_text(encoding="utf-8")
    named = set(re.findall(r"[\w./-]+\.(?:md|patch|json|py|toml|txt|jsonl)\b", prompt))
    assert named == {"spec.md", "diff.patch"}
    assert "`spec.md`" in prompt and "`diff.patch`" in prompt


def test_the_prompt_never_mentions_the_answer_key_or_the_raws(case_dir):
    prompt = (case_dir / "prompt.md").read_text(encoding="utf-8")
    for word in ("defects", "ground truth", "answer", "acceptance", "calibration", "ab_raws", "fixture", "injected", "doctored"):
        assert word not in prompt.lower(), word


def test_the_prompt_enumerates_no_category_of_defect(case_dir):
    """A plain request: listing what to look for would hand the no-skill baseline the lens checklist."""
    prompt = (case_dir / "prompt.md").read_text(encoding="utf-8").lower()
    for phrase in ("style", "naming", "preference", "scope", "unrequested", "never asked", "would not catch",
                   "tests that", "requirements", "report only", "defects only", "failure scenario"):
        assert phrase not in prompt, phrase


def test_acceptance_tells_the_calibration_run_to_copy_only_the_two_review_files(case_dir):
    acceptance = (case_dir / "acceptance.md").read_text(encoding="utf-8")
    assert "defects.json" in acceptance
    assert re.search(r"copy only[^\n]*diff\.patch[^\n]*spec\.md", acceptance), "must say to copy only diff.patch and spec.md"
    assert re.search(r"never[^\n]*(defects\.json)", acceptance)
