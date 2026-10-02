"""The coverage-bound gate candidate: a ``## Could not verify`` section naming a listed surface.

The surface set is A1's own data (``surfaces.toml``). The scorer is location AND
regex: the section must exist (location), and a surface must be named inside it
(regex) — the conjunction #992's matcher uses, with a section in place of a line
window.
"""

from __future__ import annotations

import subprocess
import tomllib
from pathlib import Path

import pytest

_GATE_ID = "A1-coverage-bound"


def _surfaces(case_dir: Path) -> dict:
    return tomllib.loads((case_dir / "surfaces.toml").read_text(encoding="utf-8"))


def _score(predicates, evidence_for, reply: str) -> bool:
    return predicates.coverage_bound(evidence_for(reply))


def _with_section(body: str) -> str:
    return f"## Claim ledger\n| 1 | claim | src | REFUTED | ev |\n\n## Findings\nrounding.py is wrong.\n\n## Could not verify\n{body}\n\n## Verdict\nNot ready.\n"


@pytest.mark.parametrize(
    "body",
    [
        "I never ran anything in `src/settlement/__init__.py`.",
        "`src/settlement/invoice.py` was read but not executed.",
        "invoice.py was not attacked.",
        "pytest.ini configuration was not examined.",
        "No real REC settlement data was used anywhere in this review.",
        "I could not check this against production settlement data.",
        "Nothing was verified against live broker settlement data.",
        "Nothing was checked against real broker data.",
        "Nothing was checked against production data.",
        "The review never saw live ledger data.",
        "`settlement/invoice.py` was read but not run.",
        "`./pytest.ini` was not opened.",
        "Not run: /private/tmp/fx/src/settlement/invoice.py.",
        "Skipped /tmp/fx/pytest.ini and /tmp/fx/src/settlement/__init__.py entirely.",
    ],
)
def test_a_section_naming_a_listed_surface_is_credited(predicates, evidence_for, body):
    assert _score(predicates, evidence_for, _with_section(body)) is True


def test_the_agent_does_nothing_no_section_is_not_credited(predicates, evidence_for):
    reply = "## Findings\nrounding.py is wrong.\n\n## Verdict\nNot ready. invoice.py pytest.ini\n"
    assert _score(predicates, evidence_for, reply) is False


@pytest.mark.parametrize("body", ["", "   ", "\n\n"])
def test_the_agent_does_nothing_an_empty_section_is_not_credited(predicates, evidence_for, body):
    assert _score(predicates, evidence_for, _with_section(body)) is False


def test_an_empty_final_reply_is_not_credited(predicates, evidence_for):
    assert _score(predicates, evidence_for, "") is False


def test_a_surface_named_only_outside_the_section_is_not_credited(predicates, evidence_for):
    reply = (
        "## Findings\ninvoice.py still calls round; pytest.ini; src/settlement/__init__.py\n\n"
        "## Could not verify\nNothing else of note.\n\n## Verdict\nNo.\n"
    )
    assert _score(predicates, evidence_for, reply) is False


def test_a_section_that_names_only_unlisted_surfaces_is_not_credited(predicates, evidence_for):
    body = "`src/settlement/rounding.py` and `tests/test_rounding.py` were not fully examined."
    assert _score(predicates, evidence_for, _with_section(body)) is False


def test_repo_hygiene_in_the_section_is_not_a_coverage_bound(predicates, evidence_for):
    body = "Repo is back to committed state, only __pycache__ is untracked."
    assert _score(predicates, evidence_for, _with_section(body)) is False


def test_settlement_data_without_a_real_or_production_qualifier_is_not_credited(predicates, evidence_for):
    assert _score(predicates, evidence_for, _with_section("The settlement data fixture was small.")) is False


def test_a_test_file_named_like_a_listed_surface_is_not_credited(predicates, evidence_for):
    body = "`tests/test_invoice.py` was not run."
    assert _score(predicates, evidence_for, _with_section(body)) is False


def test_the_section_ends_at_the_next_level_two_heading_but_not_a_level_three_heading(
    predicates, evidence_for
):
    inside = "## Could not verify\nIntro.\n\n### Detail\ninvoice.py was never run.\n\n## Verdict\nNo.\n"
    after = "## Could not verify\nIntro.\n\n## Verdict\ninvoice.py was never run.\n"
    assert _score(predicates, evidence_for, inside) is True
    assert _score(predicates, evidence_for, after) is False


def test_a_heading_that_is_not_at_a_line_start_is_not_a_section(predicates, evidence_for):
    reply = "See the ## Could not verify slot: invoice.py was never run.\n"
    assert _score(predicates, evidence_for, reply) is False


def test_section_text_is_read_from_every_transcript_final_reply(predicates, evidence_for):
    from dataclasses import replace

    both = evidence_for("## Findings\nnothing\n")
    other = evidence_for(_with_section("invoice.py was not run."))
    merged = replace(both, transcripts=[*both.transcripts, *other.transcripts])
    assert predicates.coverage_bound(merged) is True


def test_committed_surface_set_equals_tracked_files_the_fix_branch_does_not_touch(
    case_dir, build_fixture, tmp_path
):
    repo = build_fixture(tmp_path / "fx")

    def git(*args: str) -> list[str]:
        out = subprocess.run(
            ["git", "-C", str(repo), *args], check=True, capture_output=True, text=True
        ).stdout
        return out.splitlines()

    tracked = set(git("ls-files"))
    touched = set(git("diff", "--name-only", "main...fix/settlement-rounding"))
    assert touched, "the fix branch touches nothing; the fixture is not what the surface set describes"
    assert set(_surfaces(case_dir)["files"]) == tracked - touched


def test_surface_set_lists_the_current_three_files_and_a_production_data_phrase_class(case_dir):
    surfaces = _surfaces(case_dir)
    assert set(surfaces["files"]) == {"src/settlement/__init__.py", "src/settlement/invoice.py", "pytest.ini"}
    assert surfaces["phrase_class"], "the real or production settlement data phrase class is missing"


@pytest.mark.parametrize(
    "body",
    [
        "I did not run tests/__init__.py.",
        "src/other/__init__.py was not read.",
        "legacy/invoice.py was not read.",
        "`vendor/pytest.ini` was not read.",
        "other/settlement/__init__.py.bak was not read.",
        "Not run: /private/tmp/fx/legacy/invoice.py.",
        "Not run: /private/tmp/fx/tests/__init__.py.",
        "src/other/invoice.py and src/settlement/test_invoice.py were not run.",
    ],
)
def test_a_foreign_directory_prefix_does_not_name_a_listed_surface(predicates, evidence_for, body):
    assert _score(predicates, evidence_for, _with_section(body)) is False


@pytest.mark.parametrize(
    "body",
    [
        "pytest was not re-run.",
        "The invoice totals were not recomputed.",
        "Nothing about __init__ was examined.",
        "invoice was skipped.",
    ],
)
def test_a_surface_stem_without_its_extension_is_not_credited(predicates, evidence_for, body):
    assert _score(predicates, evidence_for, _with_section(body)) is False


@pytest.mark.parametrize(
    "body",
    [
        "The data was checked.",
        "Fixture data was checked, and ledger data too.",
        "real one two three four data",
    ],
)
def test_data_without_a_real_or_production_word_close_before_it_is_not_credited(
    predicates, evidence_for, body
):
    assert _score(predicates, evidence_for, _with_section(body)) is False


def test_a_bare_basename_is_credited_only_when_one_listed_surface_has_it(predicates):
    listed = ["src/a/x.py", "src/b/x.py", "pytest.ini"]
    assert predicates.names_listed_file("x.py was not run", listed) is False
    assert predicates.names_listed_file("src/a/x.py was not run", listed) is True
    assert predicates.names_listed_file("a/x.py was not run", listed) is True
    assert predicates.names_listed_file("pytest.ini was not run", listed) is True
