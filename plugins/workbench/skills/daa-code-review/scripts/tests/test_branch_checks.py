"""Tests for branch_checks: the diff-aware runner and its JSON report."""

import json
import subprocess
import sys
from pathlib import Path
from types import SimpleNamespace

import pytest

import branch_checks as bc
from branch_checks import Context, ToolError, safe_run

SECRET = "hunter2-Sup3rS3cret-LITERAL"


def cp(stdout: str = "", stderr: str = "", rc: int = 0) -> subprocess.CompletedProcess:
    return subprocess.CompletedProcess([], rc, stdout, stderr)


class FakeRun:
    """Injectable subprocess seam: first route whose needle is in the command wins."""

    def __init__(self, routes: dict[str, subprocess.CompletedProcess | Exception]):
        self.routes = routes
        self.calls: list[list[str]] = []

    def __call__(self, cmd: list[str], cwd: Path):
        self.calls.append(cmd)
        joined = " ".join(cmd)
        for needle, result in self.routes.items():
            if needle in joined:
                if isinstance(result, Exception):
                    raise result
                return result
        raise AssertionError(f"unexpected command: {joined}")


def make_ctx(tmp_path: Path, changed: dict, routes: dict | None = None, **kw) -> Context:
    return Context(tmp_path.resolve(), changed, run=FakeRun(routes or {}), **kw)


def by_tool(report: dict) -> dict:
    return {c["tool"]: c for c in report["checks"]}


def git(repo: Path, *args: str) -> str:
    return subprocess.run(
        ["git", "-c", "user.name=t", "-c", "user.email=t@example.com",
         "-c", "commit.gpgsign=false", *args],
        cwd=repo, capture_output=True, text=True, check=True,
    ).stdout


@pytest.fixture
def repo(tmp_path: Path) -> Path:
    git(tmp_path, "init", "-q", "-b", "main")
    (tmp_path / "keep.py").write_text("a = 1\nb = 2\nc = 3\n")
    (tmp_path / "gone.py").write_text("x = 1\n")
    git(tmp_path, "add", "-A")
    git(tmp_path, "commit", "-qm", "base")
    git(tmp_path, "checkout", "-q", "-b", "feature")
    return tmp_path


def commit(repo: Path, msg: str = "change") -> None:
    git(repo, "add", "-A")
    git(repo, "commit", "-qm", msg)


class TestChangedLines:
    def test_new_file_counts_every_line_and_edit_counts_only_edited_lines(self, repo):
        (repo / "keep.py").write_text("a = 1\nb = 22\nc = 3\n")
        (repo / "new.py").write_text("p = 1\nq = 2\nr = 3\n")
        commit(repo)
        changed = bc.changed_lines(repo, "main")
        assert changed["new.py"] == {1, 2, 3}
        assert changed["keep.py"] == {2}

    def test_deleted_files_are_not_reviewed(self, repo):
        (repo / "gone.py").unlink()
        commit(repo)
        assert "gone.py" not in bc.changed_lines(repo, "main")

    def test_empty_new_file_is_listed_with_no_lines(self, repo):
        (repo / "empty.py").write_text("")
        commit(repo)
        assert bc.changed_lines(repo, "main")["empty.py"] == set()

    def test_target_moving_after_the_branch_point_is_not_counted(self, repo):
        (repo / "mine.py").write_text("m = 1\n")
        commit(repo)
        git(repo, "checkout", "-q", "main")
        (repo / "theirs.py").write_text("t = 1\n")
        (repo / "keep.py").write_text("a = 1\nb = 2\nc = 33\n")
        commit(repo, "target moved")
        git(repo, "checkout", "-q", "feature")
        assert set(bc.changed_lines(repo, "main")) == {"mine.py"}

    def test_uncommitted_edits_are_reviewed(self, repo):
        """A pre-commit review sees staged and unstaged work, not only commits."""
        (repo / "keep.py").write_text("a = 1\nb = 2\nc = 33\n")
        git(repo, "add", "keep.py")
        (repo / "gone.py").write_text("x = 1\ny = 2\n")
        changed = bc.changed_lines(repo, "main")
        assert changed == {"keep.py": {3}, "gone.py": {2}}

    def test_untracked_files_count_every_line_and_ignored_files_are_skipped(self, repo):
        (repo / ".gitignore").write_text("*.log\n")
        commit(repo, "ignore logs")
        (repo / "fresh.py").write_text("p = 1\nq = 2\n")
        (repo / "noise.log").write_text("x\n")
        changed = bc.changed_lines(repo, "main")
        assert changed["fresh.py"] == {1, 2}
        assert "noise.log" not in changed

    def test_unknown_target_raises(self, repo):
        with pytest.raises(ToolError):
            bc.changed_lines(repo, "no-such-ref")


class TestMainExitCodes:
    def test_invalid_target_exits_2_with_no_report(self, repo, capsys):
        assert bc.main(["--target", "no-such-ref", "--worktree", str(repo)]) == 2
        assert capsys.readouterr().out == ""

    def test_missing_worktree_exits_2(self, tmp_path, capsys):
        assert bc.main(["--target", "main", "--worktree", str(tmp_path / "nope")]) == 2
        assert capsys.readouterr().out == ""

    def test_directory_that_is_not_a_repo_exits_2(self, tmp_path, capsys):
        assert bc.main(["--target", "main", "--worktree", str(tmp_path)]) == 2

    def test_completed_run_exits_0_even_when_checks_fail(self, repo, capsys):
        (repo / "bad.yml").write_text("a: [unclosed\n")
        commit(repo)
        def real_git_else_canned(cmd, cwd):
            if cmd[0] == "git":
                return bc.run_command(cmd, cwd)
            return cp("[]")

        assert bc.main(["--target", "main", "--worktree", str(repo)], run=real_git_else_canned) == 0
        report = json.loads(capsys.readouterr().out)
        assert report["changed_files"] == ["bad.yml"]


class TestBootstrapFiles:
    def test_lists_only_touched_bootstrap_files(self, tmp_path):
        changed = {"pyproject.toml": {1}, "sub/Makefile": {2}, "src/app.py": {1}, "uv.lock": set()}
        report = bc.build_report(make_ctx(tmp_path, changed), "main", False)
        assert report["bootstrap_files_changed"] == ["pyproject.toml", "sub/Makefile", "uv.lock"]


class TestNotRun:
    def test_no_changed_files_gives_a_kind_specific_reason(self, tmp_path):
        report = bc.build_report(make_ctx(tmp_path, {}), "main", True)
        checks = by_tool(report)
        assert checks["ruff-lint"]["reason"] == "no changed Python files"
        assert checks["ruff-format"]["reason"] == "no changed Python files"
        assert checks["sqlfluff"]["reason"] == "no changed SQL files"
        assert checks["markdown"]["reason"] == "no changed Markdown files"
        assert checks["yaml"]["reason"] == "no changed YAML files"
        assert checks["bandit"]["reason"] == "no changed non-test Python files"
        assert {c["status"] for c in report["checks"] if c["tool"] != "pytest"} == {"not_run"}

    def test_project_tools_need_the_flag(self, tmp_path):
        report = bc.build_report(make_ctx(tmp_path, {}), "main", False)
        checks = by_tool(report)
        assert (checks["pytest"]["status"], checks["pytest"]["reason"]) == ("not_run", "needs --run-project-tools")
        assert (checks["mypy"]["status"], checks["mypy"]["reason"]) == ("not_run", "needs --run-project-tools")

    def test_test_only_changes_skip_non_test_checks(self, tmp_path):
        ctx = make_ctx(tmp_path, {"tests/test_x.py": {1}})
        assert bc.check_bandit(ctx).status == "not_run"
        assert bc.check_pydoclint(ctx).status == "not_run"
        assert bc.check_docstring_layout(ctx).status == "not_run"


class TestIsolation:
    def test_tool_crash_is_error_not_pass(self, tmp_path):
        ctx = make_ctx(tmp_path, {"a.py": {1}}, {"bandit": ToolError("bandit is not installed")})
        result = safe_run("bandit", bc.check_bandit, ctx)
        assert (result.status, result.reason) == ("error", "bandit is not installed")

    def test_unexpected_exception_is_error_and_other_checks_still_run(self, tmp_path):
        routes = {"bandit": RuntimeError("boom"), "pydoclint": cp(""), "ruff": cp("[]")}
        ctx = make_ctx(tmp_path, {"a.py": {1}}, routes,
                       analyze_python=lambda p: SimpleNamespace(tools_used=["ruff"], issues=[]))
        checks = by_tool(bc.build_report(ctx, "main", False))
        assert checks["bandit"]["status"] == "error"
        assert "boom" in checks["bandit"]["reason"]
        assert checks["pydoclint"]["status"] == "pass"

    def test_non_json_tool_output_is_error(self, tmp_path):
        ctx = make_ctx(tmp_path, {"a.py": {1}}, {"bandit": cp("Traceback ...", rc=1)})
        assert safe_run("bandit", bc.check_bandit, ctx).status == "error"

    def test_ruff_unavailable_to_the_analyzer_is_error(self, tmp_path):
        ctx = make_ctx(tmp_path, {"a.py": {1}},
                       analyze_python=lambda p: SimpleNamespace(tools_used=[], issues=[]))
        assert safe_run("ruff-lint", bc.check_ruff_lint, ctx).status == "error"


def bandit_report(**overrides) -> str:
    result = {
        "filename": "./src/app.py", "line_number": 3, "test_id": "B105",
        "issue_severity": "LOW", "issue_confidence": "MEDIUM",
        "issue_text": f"Possible hardcoded password: '{SECRET}'",
        "code": f"3 PASSWORD = '{SECRET}'\n",
    }
    result.update(overrides)
    return json.dumps({"results": [result], "errors": []})


class TestBandit:
    def test_secret_never_appears_anywhere_in_the_report(self, tmp_path):
        ctx = make_ctx(tmp_path, {"src/app.py": {3}}, {"bandit": cp(bandit_report(), rc=1)})
        report = bc.build_report(ctx, "main", False)
        assert SECRET not in json.dumps(report)
        finding = by_tool(report)["bandit"]["findings"][0]
        assert finding["message"] == "possible hardcoded credential; value redacted"
        assert "code" not in finding
        assert finding["file"] == "src/app.py"
        assert finding["on_changed_line"] is True

    @pytest.mark.parametrize("test_id", ["B105", "B106", "B107"])
    def test_all_credential_tests_are_redacted_and_at_least_major(self, tmp_path, test_id):
        out = bandit_report(test_id=test_id, issue_severity="LOW", issue_confidence="LOW")
        finding = bc.check_bandit(make_ctx(tmp_path, {"src/app.py": {3}}, {"bandit": cp(out, rc=1)})).findings[0]
        assert finding["severity"] == "major"
        assert SECRET not in json.dumps(finding)

    def test_non_credential_message_is_kept(self, tmp_path):
        out = bandit_report(test_id="B602", issue_text="subprocess call with shell=True")
        finding = bc.check_bandit(make_ctx(tmp_path, {"src/app.py": {3}}, {"bandit": cp(out, rc=1)})).findings[0]
        assert finding["message"] == "subprocess call with shell=True"

    @pytest.mark.parametrize(
        ("severity", "confidence", "expected"),
        [
            ("HIGH", "HIGH", "blocker"),
            ("HIGH", "MEDIUM", "blocker"),
            ("HIGH", "LOW", "major"),
            ("MEDIUM", "HIGH", "major"),
            ("MEDIUM", "LOW", "major"),
            ("LOW", "HIGH", "minor"),
        ],
    )
    def test_severity_mapping(self, tmp_path, severity, confidence, expected):
        out = bandit_report(test_id="B602", issue_severity=severity, issue_confidence=confidence)
        finding = bc.check_bandit(make_ctx(tmp_path, {"src/app.py": {3}}, {"bandit": cp(out, rc=1)})).findings[0]
        assert finding["severity"] == expected

    def test_high_credential_finding_is_not_downgraded_to_major(self, tmp_path):
        out = bandit_report(issue_severity="HIGH", issue_confidence="HIGH")
        finding = bc.check_bandit(make_ctx(tmp_path, {"src/app.py": {3}}, {"bandit": cp(out, rc=1)})).findings[0]
        assert finding["severity"] == "blocker"

    def test_finding_off_the_changed_lines_is_flagged(self, tmp_path):
        ctx = make_ctx(tmp_path, {"src/app.py": {10}}, {"bandit": cp(bandit_report(), rc=1)})
        assert bc.check_bandit(ctx).findings[0]["on_changed_line"] is False

    def test_scan_errors_with_no_findings_is_error(self, tmp_path):
        out = json.dumps({"results": [], "errors": [{"filename": "src/app.py", "reason": "syntax"}]})
        result = bc.check_bandit(make_ctx(tmp_path, {"src/app.py": {1}}, {"bandit": cp(out)}))
        assert result.status == "error"


class TestSqlfluff:
    def sql_ctx(self, tmp_path, payload, **routes):
        return make_ctx(tmp_path, {"models/a.sql": {1}}, {"sqlfluff": cp(json.dumps(payload), rc=1)})

    def test_parse_failure_is_error_naming_the_file_not_a_finding(self, tmp_path):
        payload = [{"filepath": "models/a.sql", "violations": [
            {"code": "PRS", "start_line_no": 1, "description": "Line 1, Position 1: Found unparsable section"}]}]
        result = bc.check_sqlfluff(self.sql_ctx(tmp_path, payload))
        assert result.status == "error"
        assert result.findings == []
        assert "models/a.sql" in result.reason

    def test_templating_failure_is_error(self, tmp_path):
        payload = [{"filepath": "models/a.sql", "violations": [{"code": "TMP", "description": "x"}]}]
        assert bc.check_sqlfluff(self.sql_ctx(tmp_path, payload)).status == "error"

    def test_lint_violations_are_minor_findings(self, tmp_path):
        payload = [{"filepath": "models/a.sql", "violations": [
            {"code": "LT01", "start_line_no": 1, "description": "spacing"}]}]
        result = bc.check_sqlfluff(self.sql_ctx(tmp_path, payload))
        assert result.status == "fail"
        assert (result.findings[0]["severity"], result.findings[0]["rule_id"]) == ("minor", "LT01")
        assert result.findings[0]["on_changed_line"] is True

    def test_snowflake_dialect_only_when_repo_has_no_config(self, tmp_path):
        ctx = self.sql_ctx(tmp_path, [])
        bc.check_sqlfluff(ctx)
        assert "--dialect" in ctx.run.calls[0] and "snowflake" in ctx.run.calls[0]
        (tmp_path / ".sqlfluff").write_text("[sqlfluff]\ndialect = bigquery\n")
        ctx2 = self.sql_ctx(tmp_path, [])
        bc.check_sqlfluff(ctx2)
        assert "--dialect" not in ctx2.run.calls[0]


FORMAT_DIFF = """\
--- a.py
+++ a.py
@@ -1,3 +1,3 @@
 keep = 1
-x   = 2
+x = 2
 end = 3
--- b.py
+++ b.py
@@ -5,2 +5,2 @@
-y   = 1
+y = 1
 z = 2
"""


class TestRuffFormat:
    def fmt_ctx(self, tmp_path, changed):
        return make_ctx(tmp_path, changed, {"format": cp(FORMAT_DIFF, rc=1)})

    def test_difference_only_on_unchanged_lines_passes_as_pre_existing(self, tmp_path):
        result = bc.check_ruff_format(self.fmt_ctx(tmp_path, {"a.py": {1, 3}, "b.py": {1}}))
        assert (result.status, result.reason, result.findings) == ("pass", "pre-existing", [])

    def test_context_lines_do_not_count_as_touched(self, tmp_path):
        # line 1 and 3 are context in the hunk for a.py; only line 2 is rewritten
        assert bc.check_ruff_format(self.fmt_ctx(tmp_path, {"a.py": {1, 3}, "b.py": {9}})).status == "pass"

    def test_touching_a_changed_line_gives_one_minor_finding_for_the_whole_run(self, tmp_path):
        result = bc.check_ruff_format(self.fmt_ctx(tmp_path, {"a.py": {2}, "b.py": {5}}))
        assert result.status == "fail"
        assert len(result.findings) == 1
        finding = result.findings[0]
        assert (finding["severity"], finding["on_changed_line"]) == ("minor", True)
        assert "a.py" in finding["message"] and "b.py" in finding["message"]

    def test_pure_insertion_touches_the_lines_around_it(self, tmp_path):
        diff = "--- c.py\n+++ c.py\n@@ -4,2 +4,3 @@\n a\n+inserted\n b\n"
        assert bc.format_differences(diff) == [("c.py", {4, 5})]

    def test_clean_run_has_no_reason(self, tmp_path):
        ctx = make_ctx(tmp_path, {"a.py": {1}}, {"format": cp("", rc=0)})
        result = bc.check_ruff_format(ctx)
        assert (result.status, result.reason) == ("pass", "")

    def test_ruff_usage_failure_is_not_a_pass(self, tmp_path):
        ctx = make_ctx(tmp_path, {"a.py": {1}}, {"format": cp("", "bad flag", rc=2)})
        assert safe_run("ruff-format", bc.check_ruff_format, ctx).status == "error"


class TestRuffFormatRealGit:
    def test_pre_existing_misformat_passes_but_a_new_one_fails(self, repo, capsys):
        (repo / "keep.py").write_text("a   = 1\nb = 2\nc = 3\n")
        git(repo, "checkout", "-q", "main")
        (repo / "keep.py").write_text("a   = 1\nb = 2\nc = 3\n")
        commit(repo, "misformatted base")
        git(repo, "checkout", "-q", "-B", "feature")
        (repo / "keep.py").write_text("a   = 1\nb = 2\nc = 3\n\n\ndef ok():\n    return 1\n")
        commit(repo)
        ctx = Context(repo.resolve(), bc.changed_lines(repo, "main"))
        result = bc.check_ruff_format(ctx)
        assert (result.status, result.reason) == ("pass", "pre-existing")

        (repo / "keep.py").write_text("a   = 1\nb = 2\nc = 3\n\n\ndef ok():\n    return   1\n")
        commit(repo, "new misformat")
        ctx = Context(repo.resolve(), bc.changed_lines(repo, "main"))
        assert bc.check_ruff_format(ctx).status == "fail"


class TestPydoclintAndDocstrings:
    def test_dropped_codes_are_filtered_and_kept_codes_are_minor(self, tmp_path):
        out = (
            "src/a.py\n"
            "    10: DOC101: Function `f` has 1 argument in signature but docstring lacks it\n"
            "    11: DOC105: argument type hints do not match\n"
            "    12: DOC108: type hints missing\n"
            "    13: DOC605: other\n"
            "    14: DOC201: Function `f` does not have a return section\n"
        )
        result = bc.check_pydoclint(make_ctx(tmp_path, {"src/a.py": {10}}, {"pydoclint": cp(out, rc=1)}))
        assert [f["rule_id"] for f in result.findings] == ["DOC101", "DOC201"]
        assert {f["severity"] for f in result.findings} == {"minor"}
        assert [f["on_changed_line"] for f in result.findings] == [True, False]

    def test_docstring_layout_uses_numpy_convention_on_non_test_files(self, tmp_path):
        diag = [{"filename": str(tmp_path / "src/a.py"), "code": "D205",
                 "message": "1 blank line required", "location": {"row": 4, "column": 1}}]
        ctx = make_ctx(tmp_path, {"src/a.py": {4}, "tests/test_a.py": {1}}, {"ruff": cp(json.dumps(diag), rc=1)})
        result = bc.check_docstring_layout(ctx)
        cmd = ctx.run.calls[0]
        assert "numpy" in " ".join(cmd) and "D" in cmd
        assert "tests/test_a.py" not in cmd and "src/a.py" in cmd
        assert (result.findings[0]["rule_id"], result.findings[0]["severity"]) == ("D205", "minor")
        assert result.findings[0]["file"] == "src/a.py"
        assert result.findings[0]["on_changed_line"] is True


class TestYaml:
    def test_parse_error_is_a_blocker_at_the_error_line(self, tmp_path):
        pytest.importorskip("yaml")
        (tmp_path / "bad.yml").write_text("ok: 1\nlist: [unclosed\nnext: 2\n")
        (tmp_path / "good.yaml").write_text("a: 1\n---\nb: 2\n")
        ctx = make_ctx(tmp_path, {"bad.yml": {2}, "good.yaml": {1}})
        result = bc.check_yaml(ctx)
        assert result.status == "fail"
        assert len(result.findings) == 1
        finding = result.findings[0]
        assert finding["file"] == "bad.yml"
        assert finding["severity"] == "blocker"
        assert finding["line"] == 3

    def test_valid_yaml_passes(self, tmp_path):
        pytest.importorskip("yaml")
        (tmp_path / "good.yml").write_text("a: 1\n")
        assert bc.check_yaml(make_ctx(tmp_path, {"good.yml": {1}})).status == "pass"

    def test_custom_tags_are_not_parse_errors(self, tmp_path):
        """GitLab's ``!reference`` and other application tags are valid YAML."""
        pytest.importorskip("yaml")
        (tmp_path / ".gitlab-ci.yml").write_text(
            "job:\n  script:\n    - !reference [.setup, script]\n  env: !ENV ${HOME}\n"
        )
        result = bc.check_yaml(make_ctx(tmp_path, {".gitlab-ci.yml": {1}}))
        assert (result.status, result.findings) == ("pass", [])

    def test_missing_pyyaml_is_error_not_pass(self, tmp_path, monkeypatch):
        (tmp_path / "good.yml").write_text("a: 1\n")
        monkeypatch.setitem(sys.modules, "yaml", None)
        result = safe_run("yaml", bc.check_yaml, make_ctx(tmp_path, {"good.yml": {1}}))
        assert (result.status, result.reason) == ("error", "pyyaml is not installed")


class TestMarkdownAndRuffLintReuse:
    def test_markdown_analyzer_findings_carry_changed_line_flag(self, tmp_path):
        (tmp_path / "n.md").write_text("# Title\n\n### Skipped\n\nText.\n")
        result = bc.check_markdown(make_ctx(tmp_path, {"n.md": {3}}))
        hit = [f for f in result.findings if f["line"] == 3]
        assert hit and hit[0]["on_changed_line"] is True
        assert result.status == "fail"
        off = bc.check_markdown(make_ctx(tmp_path, {"n.md": {1}}))
        assert [f["on_changed_line"] for f in off.findings if f["line"] == 3] == [False]

    def test_ruff_lint_reports_unused_import_and_ignores_format_issues(self, tmp_path):
        (tmp_path / "m.py").write_text("import os\nx   = 1\n")
        result = bc.check_ruff_lint(make_ctx(tmp_path, {"m.py": {1, 2}}))
        assert "F401" in {f["rule_id"] for f in result.findings}
        assert "FORMAT" not in {f["rule_id"] for f in result.findings}

    def test_ruff_lint_credential_is_major_and_redacted(self, tmp_path):
        (tmp_path / "m.py").write_text(f'password = "{SECRET}"\n')
        report = bc.build_report(make_ctx(tmp_path, {"m.py": {1}}), "main", False)
        found = [f for f in by_tool(report)["ruff-lint"]["findings"] if f["rule_id"] == "S105"]
        assert found and found[0]["severity"] == "major"
        assert SECRET not in json.dumps(report)


PYTEST_OUT = (
    "..F.E\n"
    "=========================== short test summary info ============================\n"
    f"FAILED tests/test_a.py::test_x - AssertionError: {SECRET}\n"
    "ERROR tests/test_b.py::test_y - fixture 'z' not found\n"
    "1 failed, 2 passed, 1 error in 0.12s\n"
)


class TestProjectTools:
    def proj(self, tmp_path, routes, files=None):
        (tmp_path / "pyproject.toml").write_text("[project]\nname='x'\n")
        return make_ctx(tmp_path, files or {"a.py": {1}}, routes)

    def test_pytest_keeps_ids_and_summary_only(self, tmp_path):
        ctx = self.proj(tmp_path, {"pytest": cp(PYTEST_OUT, rc=1)})
        report = bc.build_report(ctx, "main", True)
        pytest_call = next(c for c in ctx.run.calls if "pytest" in c)
        assert pytest_call[:5] == ["uv", "run", "python", "-m", "pytest"]
        result = by_tool(report)["pytest"]
        assert result["status"] == "fail"
        assert result["reason"] == "1 failed, 2 passed, 1 error in 0.12s"
        assert [f["message"] for f in result["findings"]] == [
            "failing test: tests/test_a.py::test_x", "failing test: tests/test_b.py::test_y"]
        assert {f["severity"] for f in result["findings"]} == {"blocker"}
        assert SECRET not in json.dumps(report)

    def test_pytest_pass(self, tmp_path):
        ctx = self.proj(tmp_path, {"pytest": cp("...\n3 passed in 0.1s\n")})
        result = bc.check_pytest(ctx)
        assert (result.status, result.findings) == ("pass", [])

    def test_pytest_nonzero_without_failing_ids_is_error_not_pass(self, tmp_path):
        ctx = self.proj(tmp_path, {"pytest": cp("usage: pytest ...\n", rc=4)})
        assert bc.check_pytest(ctx).status == "error"

    def test_tool_missing_from_project_is_not_run(self, tmp_path):
        ctx = self.proj(tmp_path, {"mypy": cp("", "No module named mypy", rc=1)})
        result = bc.check_mypy(ctx)
        assert (result.status, result.reason) == ("not_run", "mypy is not a project dependency")

    def test_mypy_errors_are_blockers_with_changed_line_flag(self, tmp_path):
        out = ("a.py:3: error: Incompatible return value type\n"
               "a.py:3: note: see docs\n"
               "a.py:9: error: Name 'q' is not defined\n")
        result = bc.check_mypy(self.proj(tmp_path, {"mypy": cp(out, rc=1)}, {"a.py": {3}}))
        assert result.status == "fail"
        assert [(f["line"], f["on_changed_line"], f["severity"]) for f in result.findings] == [
            (3, True, "blocker"), (9, False, "blocker")]

    def test_mypy_crash_exit_without_errors_is_error(self, tmp_path):
        result = bc.check_mypy(self.proj(tmp_path, {"mypy": cp("", "Traceback", rc=2)}))
        assert result.status == "error"


class TestEndToEnd:
    def test_stdout_is_one_json_object_with_the_documented_shape(self, repo, capsys):
        (repo / "src").mkdir()
        (repo / "src" / "app.py").write_text(f'PASSWORD = "{SECRET}"\n')
        (repo / "pyproject.toml").write_text("[project]\nname = 'x'\n")
        commit(repo)

        def runner(cmd, cwd):
            if cmd[0] == "git":
                return bc.run_command(cmd, cwd)
            if "bandit" in cmd:
                return cp(bandit_report(filename="src/app.py", line_number=1), rc=1)
            if cmd[0] == "uvx":
                return cp("")
            return bc.run_command(cmd, cwd)

        code = bc.main(["--target", "main", "--worktree", str(repo)], run=runner)
        out = capsys.readouterr().out
        assert code == 0
        assert SECRET not in out
        report = json.loads(out)
        assert set(report) >= {"target", "changed_files", "bootstrap_files_changed", "checks"}
        assert report["bootstrap_files_changed"] == ["pyproject.toml"]
        assert set(report["changed_files"]) == {"pyproject.toml", "src/app.py"}
        for check in report["checks"]:
            assert set(check) == {"tool", "scope", "status", "reason", "findings"}
            assert check["status"] in {"pass", "fail", "not_run", "error"}
            for f in check["findings"]:
                assert set(f) == {"file", "line", "rule_id", "severity", "message", "on_changed_line"}
        assert by_tool(report)["bandit"]["findings"][0]["on_changed_line"] is True
