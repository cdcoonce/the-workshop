"""Tests for the analyzers' JSON command-line interface."""

import json
import os
import subprocess
import sys
from pathlib import Path

import pytest

SCRIPTS = Path(__file__).resolve().parent.parent
PY_CLI = SCRIPTS / "python_analyzer.py"
MD_CLI = SCRIPTS / "markdown_analyzer.py"

UNUSED_IMPORT_PY = "import os\n"
CLEAN_PY = '# Copyright 2026 Example\n"""Module docstring."""\n\nVALUE = 1\n'
SKIPPED_HEADING_MD = "# Title\n\n### Skipped\n\nText.\n"
CLEAN_MD = "# Title\n\n## Section\n\nText.\n"


def run_cli(script: Path, *args: str, env: dict | None = None) -> subprocess.CompletedProcess:
    return subprocess.run(
        [sys.executable, str(script), *args],
        capture_output=True,
        text=True,
        cwd=SCRIPTS,
        check=False,
        env=env,
    )


def assert_read_failure(proc: subprocess.CompletedProcess, bad: Path) -> None:
    assert proc.returncode == 2
    assert proc.stdout == ""
    assert f"error: cannot read {bad}" in proc.stderr
    assert "Traceback" not in proc.stderr


@pytest.fixture
def binary_file(tmp_path: Path) -> Path:
    path = tmp_path / "binary.dat"
    path.write_bytes(b"\xff\xfe\x00\x80 not utf-8\n")
    return path


@pytest.fixture
def py_file(tmp_path: Path) -> Path:
    path = tmp_path / "sample.py"
    path.write_text(UNUSED_IMPORT_PY, encoding="utf-8")
    return path


@pytest.fixture
def md_file(tmp_path: Path) -> Path:
    path = tmp_path / "sample.md"
    path.write_text(SKIPPED_HEADING_MD, encoding="utf-8")
    return path


class TestPythonAnalyzerCli:
    def test_json_reports_known_issue_with_line(self, py_file: Path):
        proc = run_cli(PY_CLI, str(py_file), "--json")
        assert proc.returncode == 0, proc.stderr
        data = json.loads(proc.stdout)
        assert len(data) == 1
        entry = data[0]
        assert entry["file"] == str(py_file)
        assert entry["file_type"] == "python"
        f401 = [i for i in entry["issues"] if i["rule_id"] == "F401"]
        assert len(f401) == 1
        issue = f401[0]
        assert issue["line"] == 1
        assert issue["severity"] in {"error", "warning", "info"}
        assert issue["category"] == "unused_code"
        assert issue["message"]

    def test_clean_file_has_no_issues_and_exits_zero(self, tmp_path: Path):
        (tmp_path / "__init__.py").write_text("", encoding="utf-8")
        path = tmp_path / "clean.py"
        path.write_text(CLEAN_PY, encoding="utf-8")
        proc = run_cli(PY_CLI, str(path), "--json")
        assert proc.returncode == 0
        assert json.loads(proc.stdout)[0]["issues"] == []

    def test_exit_zero_even_with_findings(self, py_file: Path):
        assert run_cli(PY_CLI, str(py_file), "--json").returncode == 0

    def test_missing_path_exits_2_with_stderr_and_empty_stdout(self, tmp_path: Path):
        proc = run_cli(PY_CLI, str(tmp_path / "nope.py"), "--json")
        assert proc.returncode == 2
        assert proc.stdout == ""
        assert "nope.py" in proc.stderr

    def test_plain_text_mode_prints_a_line_per_issue(self, py_file: Path):
        proc = run_cli(PY_CLI, str(py_file))
        assert proc.returncode == 0
        assert "F401" in proc.stdout
        assert not proc.stdout.lstrip().startswith("[")


class TestMarkdownAnalyzerCli:
    def test_json_reports_known_issue_with_line(self, md_file: Path):
        proc = run_cli(MD_CLI, str(md_file), "--json")
        assert proc.returncode == 0, proc.stderr
        data = json.loads(proc.stdout)
        assert len(data) == 1
        entry = data[0]
        assert entry["file"] == str(md_file)
        assert entry["file_type"] == "markdown"
        hits = [i for i in entry["issues"] if i["line"] == 3 and "heading" in i["message"].lower()]
        assert hits, entry["issues"]
        assert {"severity", "category", "line", "message", "rule_id"} <= set(hits[0])

    def test_clean_file_has_no_issues_and_exits_zero(self, tmp_path: Path):
        path = tmp_path / "clean.md"
        path.write_text(CLEAN_MD, encoding="utf-8")
        proc = run_cli(MD_CLI, str(path), "--json")
        assert proc.returncode == 0
        assert json.loads(proc.stdout)[0]["issues"] == []

    def test_multiple_paths_yield_results_in_input_order(self, tmp_path: Path, md_file: Path):
        clean = tmp_path / "clean.md"
        clean.write_text(CLEAN_MD, encoding="utf-8")
        proc = run_cli(MD_CLI, str(clean), str(md_file), "--json")
        data = json.loads(proc.stdout)
        assert [d["file"] for d in data] == [str(clean), str(md_file)]
        assert data[0]["issues"] == []
        assert data[1]["issues"] != []

    def test_missing_path_exits_2_with_stderr_and_empty_stdout(self, tmp_path: Path, md_file: Path):
        proc = run_cli(MD_CLI, str(md_file), str(tmp_path / "nope.md"), "--json")
        assert proc.returncode == 2
        assert proc.stdout == ""
        assert "nope.md" in proc.stderr

    def test_plain_text_mode_prints_a_line_per_issue(self, md_file: Path):
        proc = run_cli(MD_CLI, str(md_file))
        assert proc.returncode == 0
        assert f"{md_file}:3" in proc.stdout


class TestMissingRuff:
    def test_cli_exits_3_with_stderr_and_empty_stdout_when_ruff_absent(
        self, tmp_path: Path
    ):
        empty_bin = tmp_path / "empty-bin"
        empty_bin.mkdir()
        env = {**os.environ, "PATH": str(empty_bin)}
        bad = tmp_path / "broken.py"
        bad.write_text("def (:\n", encoding="utf-8")
        proc = run_cli(PY_CLI, str(bad), "--json", env=env)
        assert proc.returncode == 3
        assert proc.stdout == ""
        assert "ruff not available" in proc.stderr


class TestUnreadableInputs:
    @pytest.mark.parametrize("cli", [PY_CLI, MD_CLI], ids=["python", "markdown"])
    def test_non_utf8_file_exits_2_without_traceback(self, cli: Path, binary_file: Path):
        assert_read_failure(run_cli(cli, str(binary_file), "--json"), binary_file)

    @pytest.mark.parametrize("cli", [PY_CLI, MD_CLI], ids=["python", "markdown"])
    def test_mixed_good_and_bad_prints_nothing_to_stdout(
        self, cli: Path, binary_file: Path, tmp_path: Path
    ):
        good = tmp_path / ("good.py" if cli == PY_CLI else "good.md")
        good.write_text(CLEAN_PY if cli == PY_CLI else CLEAN_MD, encoding="utf-8")
        assert_read_failure(
            run_cli(cli, str(good), str(binary_file), "--json"), binary_file
        )

    @pytest.mark.skipif(
        sys.platform == "win32" or (hasattr(os, "geteuid") and os.geteuid() == 0),
        reason="chmod 000 cannot deny reads on Windows or as root",
    )
    @pytest.mark.parametrize("cli", [PY_CLI, MD_CLI], ids=["python", "markdown"])
    def test_permission_denied_file_exits_2_without_traceback(
        self, cli: Path, tmp_path: Path
    ):
        locked = tmp_path / "locked.txt"
        locked.write_text("x = 1\n", encoding="utf-8")
        locked.chmod(0o000)
        try:
            assert_read_failure(run_cli(cli, str(locked), "--json"), locked)
        finally:
            locked.chmod(0o600)
