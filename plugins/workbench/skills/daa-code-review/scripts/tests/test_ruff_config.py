"""Tests that python_analyzer honours the repo's ruff config and fits severities."""

from pathlib import Path

import pytest

from models import Severity
from python_analyzer import analyze_python_file, get_severity_for_rule


BUGGY = "import os\nx = 1; y = 2\n\n\ndef f(a=[]):\n    return a\n"


def rule_ids(path: Path) -> set[str]:
    return {issue.rule_id for issue in analyze_python_file(path).issues}


def issues_for(path: Path, rule: str):
    return [i for i in analyze_python_file(path).issues if i.rule_id == rule]


class TestRepoConfigWins:
    def test_pyproject_select_replaces_the_default_rule_set(self, tmp_path: Path):
        (tmp_path / "pyproject.toml").write_text(
            '[tool.ruff.lint]\nselect = ["E"]\n', encoding="utf-8"
        )
        src = tmp_path / "mod.py"
        src.write_text(BUGGY, encoding="utf-8")
        ids = rule_ids(src)
        assert "E702" in ids
        assert "F401" not in ids
        assert "B006" not in ids

    def test_ruff_toml_in_ancestor_directory_governs_nested_file(self, tmp_path: Path):
        (tmp_path / "ruff.toml").write_text('[lint]\nselect = ["E"]\n', encoding="utf-8")
        nested = tmp_path / "pkg" / "sub"
        nested.mkdir(parents=True)
        src = nested / "mod.py"
        src.write_text(BUGGY, encoding="utf-8")
        ids = rule_ids(src)
        assert "E702" in ids
        assert "F401" not in ids
        assert "B006" not in ids

    def test_pyproject_without_tool_ruff_table_is_not_a_config(self, tmp_path: Path):
        (tmp_path / "pyproject.toml").write_text(
            '[project]\nname = "x"\nversion = "0"\n', encoding="utf-8"
        )
        src = tmp_path / "mod.py"
        src.write_text(BUGGY, encoding="utf-8")
        ids = rule_ids(src)
        assert "F401" in ids
        assert "B006" in ids


class TestNoConfigFallback:
    def test_defaults_plus_bugbear_and_bandit_not_all_rules(self, tmp_path: Path):
        src = tmp_path / "mod.py"
        src.write_text("import os\n\n\ndef f(a=[]):\n    return a\n", encoding="utf-8")
        ids = rule_ids(src)
        assert "F401" in ids
        assert "B006" in ids
        assert "D103" not in ids
        assert "ANN001" not in ids


class TestAssertSeverityInTests:
    @pytest.mark.parametrize(
        "relpath",
        [
            "tests/test_x.py",
            "test_x.py",
            "x_test.py",
            "conftest.py",
            "tests/helpers.py",
            "pkg/tests/sub/util.py",
        ],
    )
    def test_assert_in_test_file_is_info(self, tmp_path: Path, relpath: str):
        src = tmp_path / relpath
        src.parent.mkdir(parents=True, exist_ok=True)
        src.write_text("assert 1 == 1\n", encoding="utf-8")
        found = issues_for(src, "S101")
        assert found
        assert {i.severity for i in found} == {Severity.INFO}

    @pytest.mark.parametrize("relpath", ["src/mod.py", "testing/mod.py", "contest.py"])
    def test_assert_outside_test_files_is_warning(self, tmp_path: Path, relpath: str):
        src = tmp_path / relpath
        src.parent.mkdir(parents=True, exist_ok=True)
        src.write_text("assert 1 == 1\n", encoding="utf-8")
        found = issues_for(src, "S101")
        assert found
        assert {i.severity for i in found} == {Severity.WARNING}

    def test_other_error_rules_are_not_downgraded_in_test_files(self):
        assert get_severity_for_rule("F821", Path("tests/test_x.py")) == Severity.ERROR

    def test_severity_without_a_path_is_warning(self):
        assert get_severity_for_rule("S101") == Severity.WARNING


class TestBanditSeverity:
    @pytest.mark.parametrize("rule", ["S603", "S607", "S101", "S105"])
    def test_bandit_rules_are_warning_not_blocking(self, rule: str):
        assert get_severity_for_rule(rule) == Severity.WARNING

    @pytest.mark.parametrize("rule", ["F821", "F822", "F823", "E999"])
    def test_runtime_defects_stay_error(self, rule: str):
        assert get_severity_for_rule(rule) == Severity.ERROR

    def test_subprocess_call_is_warning_end_to_end(self, tmp_path: Path):
        src = tmp_path / "mod.py"
        src.write_text(
            "import subprocess\n\nsubprocess.run(['ls'], check=False)\n",
            encoding="utf-8",
        )
        found = issues_for(src, "S607")
        assert found
        assert {i.severity for i in found} == {Severity.WARNING}
