"""No triggering prompt may name its own rostered skill.

A triggering item measures whether a skill fires on a natural request. A prompt that says
the skill's name would hand the agent the answer, so this reads the prompt of A3, T-trig and
C-trig and refuses any that contains the rostered skill's name.

The match is deliberately wide. Case, hyphens, underscores and runs of whitespace are all
folded together, so ``Adversarial_Review`` and ``adversarial   review`` count as the name,
and the name is searched as a substring, so ``tdd`` is caught inside any word and ``commit``
inside ``committed``. A narrower rule would let a prompt name the skill by a spelling the
rule did not think of; the price is that these prompts must avoid even the ordinary word.
"""

from __future__ import annotations

import re
import tomllib
from pathlib import Path

import pytest

_EVALS = Path(__file__).resolve().parents[3]
_CASES = {
    "adversarial-review": "A3",
    "tdd": "T-trig",
    "commit": "C-trig",
}


def _fold(text: str) -> str:
    return re.sub(r"[\s_-]+", " ", text.lower()).strip()


def names_skill(prompt: str, skill: str) -> bool:
    """Whether *prompt* names *skill*, ignoring case and hyphen, underscore and space spelling."""
    return _fold(skill) in _fold(prompt)


def _prompt(skill: str, case: str) -> str:
    case_dir = _EVALS / skill / case
    case_toml = tomllib.loads((case_dir / "case.toml").read_text(encoding="utf-8"))
    return (case_dir / case_toml["prompt"]).read_text(encoding="utf-8")


@pytest.mark.parametrize(("skill", "case"), sorted(_CASES.items()))
def test_a_triggering_prompt_does_not_contain_its_own_skills_name(skill, case):
    prompt = _prompt(skill, case)
    assert prompt.strip(), f"{case}: empty prompt"
    assert not names_skill(prompt, skill), f"{case}'s prompt names {skill!r}"


@pytest.mark.parametrize(("skill", "case"), sorted(_CASES.items()))
def test_each_case_names_its_own_skill_through_its_directory_and_item_params(skill, case):
    case_toml = tomllib.loads((_EVALS / skill / case / "case.toml").read_text(encoding="utf-8"))
    assert [item["params"]["skill"] for item in case_toml["items"]] == [skill]


@pytest.mark.parametrize(
    ("skill", "prompt"),
    [
        ("adversarial-review", "Please run adversarial-review on this branch."),
        ("adversarial-review", "Please run ADVERSARIAL-REVIEW on this branch."),
        ("adversarial-review", "Can you do an adversarial review before I merge?"),
        ("adversarial-review", "Use the Adversarial_Review skill."),
        ("adversarial-review", "Give it an adversarial\n  review."),
        ("tdd", "Build this with TDD."),
        ("tdd", "Build it tdd-style."),
        ("tdd", "Fix it, tdd."),
        ("commit", "Please Commit these."),
        ("commit", "Make a COMMIT of my work."),
        ("commit", "Everything should be committed by tonight."),
        ("commit", "Use /commit for this."),
    ],
)
def test_the_checker_flags_a_prompt_that_names_the_skill(skill, prompt):
    assert names_skill(prompt, skill) is True


@pytest.mark.parametrize(
    ("skill", "prompt"),
    [
        ("adversarial-review", "Check this branch over before I merge it."),
        ("tdd", "Build this test-first."),
        ("commit", "Check in my changes and write a good message."),
        ("commit", "Save my work."),
    ],
)
def test_the_checker_passes_a_prompt_that_does_not_name_the_skill(skill, prompt):
    assert names_skill(prompt, skill) is False
