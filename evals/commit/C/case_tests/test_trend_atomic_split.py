"""C-atomic-split (trend): at least two single-unit commits, one per unit."""

from __future__ import annotations

import pytest

from commit_c_support import GOOD_COMMANDS, item_params, evidence_from

PRICING = "invoice/pricing.py\ntests/test_pricing.py\n"
NAMES = "names/normalize.py\ntests/test_names.py\n"


@pytest.fixture
def units(case_toml):
    return item_params(case_toml, "C-atomic-split")["units"]


def _score(predicates, tmp_path, files, units):
    logs = [f"{'a' * 39}{i}\nfeat: x\n\n" for i in range(len(files))]
    return predicates.atomic_split(
        evidence_from(tmp_path, commands=GOOD_COMMANDS, logs=logs, files=files), units=units
    )


def test_one_commit_per_unit_is_met(predicates, tmp_path, units):
    assert _score(predicates, tmp_path, [PRICING, NAMES], units) is True


def test_the_order_of_the_commits_does_not_matter(predicates, tmp_path, units):
    assert _score(predicates, tmp_path, [NAMES, PRICING], units) is True


def test_one_commit_with_both_units_is_missed(predicates, tmp_path, units):
    assert _score(predicates, tmp_path, [PRICING + NAMES], units) is False


def test_one_commit_per_unit_plus_a_mixed_one_is_still_a_split(predicates, tmp_path, units):
    assert _score(predicates, tmp_path, [PRICING, NAMES, PRICING + NAMES], units) is True


def test_a_unit_split_across_its_own_commits_is_not_a_split_of_two_units(predicates, tmp_path, units):
    files = ["invoice/pricing.py\n", "tests/test_pricing.py\n"]
    assert _score(predicates, tmp_path, files, units) is False


def test_a_single_unit_commit_alone_is_missed(predicates, tmp_path, units):
    assert _score(predicates, tmp_path, [PRICING], units) is False


def test_a_commit_touching_a_file_outside_every_unit_is_not_single_unit(predicates, tmp_path, units):
    files = [PRICING + "README.md\n", NAMES + "README.md\n"]
    assert _score(predicates, tmp_path, files, units) is False


def test_a_directory_prefix_covers_new_files_in_the_unit(predicates, tmp_path, units):
    files = ["invoice/discounts.py\ntests/test_pricing.py\n", "names/titles.py\n"]
    assert _score(predicates, tmp_path, files, units) is True


def test_a_prefix_without_a_slash_does_not_match_a_sibling_name(predicates, tmp_path, units):
    files = ["invoices/other.py\n", "namesake/other.py\n"]
    assert _score(predicates, tmp_path, files, units) is False


def test_zero_new_commits_misses_the_trend_too(predicates, tmp_path, units):
    assert _score(predicates, tmp_path, [], units) is False


def test_units_come_from_the_params_not_from_module_constants(predicates, tmp_path):
    custom = [["x/"], ["y/"]]
    assert _score(predicates, tmp_path, ["x/a.py\n", "y/b.py\n"], custom) is True
    assert _score(predicates, tmp_path, [PRICING, NAMES], custom) is False


def test_commit_ten_and_up_are_read(predicates, tmp_path, units):
    files = ["README.md\n"] * 9 + [PRICING, NAMES]
    assert _score(predicates, tmp_path, files, units) is True
