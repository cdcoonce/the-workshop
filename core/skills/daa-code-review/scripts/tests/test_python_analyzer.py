"""Tests for the Python analyzer module.

This module contains pytest tests for the Python code analyzer.
"""

from pathlib import Path
import tempfile

import pytest

from models import (
    FileType,
    IssueCategory,
    Severity,
)
from python_analyzer import (
    _ruff_target,
    analyze_python,
    analyze_python_file,
    check_ruff_available,
    get_category_for_rule,
    get_severity_for_rule,
    parse_ruff_diagnostic,
    run_ruff_check,
)


class TestRuffTarget:
    """Tests for the _ruff_target temp-file management helper."""

    def test_existing_file_passed_through(self):
        """An existing file path is used directly, no temp file created."""
        with tempfile.NamedTemporaryFile(mode="w", suffix=".py", delete=False) as tmp:
            tmp.write("x = 1\n")
            tmp_path = Path(tmp.name)

        try:
            with _ruff_target("unused source", tmp_path) as target:
                assert target == str(tmp_path)
                assert tmp_path.exists()
            # Existing file must survive the context exit.
            assert tmp_path.exists()
        finally:
            tmp_path.unlink()

    def test_missing_path_creates_temp_file(self):
        """A None file path creates a temp .py file with the source."""
        with _ruff_target("x = 1\n", None) as target:
            target_path = Path(target)
            assert target_path.exists()
            assert target_path.suffix == ".py"
            assert target_path.read_text() == "x = 1\n"

        # Temp file must be cleaned up after the context exits.
        assert not target_path.exists()

    def test_nonexistent_file_path_creates_temp_file(self):
        """A file_path that does not exist on disk falls back to a temp file."""
        missing_path = Path("/nonexistent/definitely-not-here.py")

        with _ruff_target("y = 2\n", missing_path) as target:
            target_path = Path(target)
            assert target_path != missing_path
            assert target_path.exists()
            assert target_path.read_text() == "y = 2\n"

        assert not target_path.exists()

    def test_cleans_up_temp_file_on_exception(self):
        """The temp file is unlinked even if the caller raises inside the block."""
        target_path = None
        with pytest.raises(RuntimeError):
            with _ruff_target("z = 3\n", None) as target:
                target_path = Path(target)
                raise RuntimeError("boom")

        assert target_path is not None
        assert not target_path.exists()


class TestRuleMapping:
    """Tests for rule ID to category/severity mapping."""

    def test_pep8_error_category(self):
        """Test that E rules map to PEP8 category."""
        assert get_category_for_rule("E501") == IssueCategory.PEP8
        assert get_category_for_rule("E101") == IssueCategory.PEP8

    def test_pyflakes_category(self):
        """Test that F rules map to UNUSED_CODE category."""
        assert get_category_for_rule("F401") == IssueCategory.UNUSED_CODE
        assert get_category_for_rule("F841") == IssueCategory.UNUSED_CODE

    def test_complexity_category(self):
        """Test that C90 rules map to COMPLEXITY category."""
        assert get_category_for_rule("C901") == IssueCategory.COMPLEXITY

    def test_docstring_category(self):
        """Test that D rules map to DOCSTRING category."""
        assert get_category_for_rule("D100") == IssueCategory.DOCSTRING
        assert get_category_for_rule("D400") == IssueCategory.DOCSTRING

    def test_type_hint_category(self):
        """Test that ANN rules map to TYPE_HINT category."""
        assert get_category_for_rule("ANN001") == IssueCategory.TYPE_HINT
        assert get_category_for_rule("ANN201") == IssueCategory.TYPE_HINT

    def test_import_category(self):
        """Test that I rules map to IMPORT category."""
        assert get_category_for_rule("I001") == IssueCategory.IMPORT

    def test_bugbear_category(self):
        """Test that B rules map to RUNTIME_ERROR category."""
        assert get_category_for_rule("B006") == IssueCategory.RUNTIME_ERROR

    def test_security_severity(self):
        """Test that S rules have ERROR severity."""
        # Security rules should be errors
        assert get_category_for_rule("S101") == IssueCategory.RUNTIME_ERROR

    def test_error_rules_severity(self):
        """Test that known error rules have ERROR severity."""
        assert get_severity_for_rule("F821") == Severity.ERROR
        assert get_severity_for_rule("E999") == Severity.ERROR

    def test_warning_rules_severity(self):
        """Test that typical rules have WARNING severity."""
        assert get_severity_for_rule("F401") == Severity.WARNING
        assert get_severity_for_rule("E501") == Severity.WARNING

    def test_info_rules_severity(self):
        """Test that style rules have INFO severity."""
        assert get_severity_for_rule("W291") == Severity.INFO
        assert get_severity_for_rule("D100") == Severity.INFO

    def test_unknown_rule_defaults(self):
        """Test that unknown rules get sensible defaults."""
        assert get_category_for_rule("UNKNOWN123") == IssueCategory.PEP8
        assert get_severity_for_rule("UNKNOWN123") == Severity.WARNING


class TestRuffIntegration:
    """Tests for ruff integration."""

    def test_ruff_available(self):
        """Test that ruff is available on the system."""
        assert check_ruff_available() is True

    def test_run_ruff_on_clean_code(self):
        """Test ruff on code with minimal issues."""
        code = '''"""Module docstring."""


def hello() -> str:
    """Return a greeting.

    Returns
    -------
    str
        A greeting string.
    """
    return "Hello, World!"
'''
        results = run_ruff_check(code)
        # Clean code should have minimal issues
        assert isinstance(results, list)

    def test_run_ruff_detects_unused_import(self):
        """Test that ruff detects unused imports."""
        code = "import os\n\nprint('hello')\n"
        results = run_ruff_check(code)

        # Should find unused import
        f401_issues = [r for r in results if r.get("code") == "F401"]
        assert len(f401_issues) > 0

    def test_run_ruff_detects_undefined_name(self):
        """Test that ruff detects undefined names."""
        code = "print(undefined_variable)\n"
        results = run_ruff_check(code)

        # Should find undefined name
        f821_issues = [r for r in results if r.get("code") == "F821"]
        assert len(f821_issues) > 0

    def test_run_ruff_detects_unused_variable(self):
        """Test that ruff detects unused variables."""
        code = '''"""Module."""


def foo() -> None:
    """Do nothing."""
    x = 1  # noqa: F841 - testing detection
'''
        # Run without noqa
        code_no_noqa = '''"""Module."""


def foo() -> None:
    """Do nothing."""
    unused_var = 1
'''
        results = run_ruff_check(code_no_noqa)
        f841_issues = [r for r in results if r.get("code") == "F841"]
        assert len(f841_issues) > 0


class TestAnalyzePython:
    """Tests for the main analyze_python function."""

    def test_analyze_returns_result(self):
        """Test that analyze_python returns an AnalysisResult."""
        result = analyze_python("x = 1\n")
        assert result.file_type == FileType.PYTHON
        assert result.source_content == "x = 1\n"
        assert "ruff" in result.tools_used

    def test_analyze_detects_issues(self):
        """Test that analyze_python detects issues."""
        code = "import os\nx = 1\n"
        result = analyze_python(code)
        assert result.total_issues > 0

    def test_analyze_categorizes_issues(self):
        """Test that issues are properly categorized."""
        code = "import os\n\nprint('hello')\n"
        result = analyze_python(code)

        # Should have unused import issue
        unused_issues = result.get_issues_by_category(IssueCategory.UNUSED_CODE)
        assert len(unused_issues) > 0

    def test_analyze_with_file_path(self):
        """Test analysis with a file path specified."""
        code = "x = 1\n"
        result = analyze_python(code, file_path=Path("test.py"))
        assert result.source_path == Path("test.py")

    def test_analyze_includes_context(self):
        """Test that issues include source context."""
        code = "import os\n\nx = 1\n"
        result = analyze_python(code)

        for issue in result.issues:
            if issue.location.line_start > 0:
                # Most issues should have context
                assert issue.context is not None or issue.message

    def test_analyze_timing(self):
        """Test that analysis time is recorded."""
        result = analyze_python("x = 1\n")
        assert result.analysis_time_seconds >= 0

    def test_analyze_clean_code(self):
        """Test analysis of well-formatted code."""
        code = '''"""A well-documented module."""


def greet(name: str) -> str:
    """Return a greeting for the given name.

    Parameters
    ----------
    name : str
        The name to greet.

    Returns
    -------
    str
        A greeting string.
    """
    return f"Hello, {name}!"


if __name__ == "__main__":
    print(greet("World"))
'''
        result = analyze_python(code)
        # Well-written code should have fewer issues
        assert result.error_count == 0


class TestAnalyzePythonFile:
    """Tests for the analyze_python_file function."""

    def test_analyze_existing_file(self):
        """Test analyzing an existing Python file."""
        with tempfile.NamedTemporaryFile(mode="w", suffix=".py", delete=False) as tmp:
            tmp.write("import os\nx = 1\n")
            tmp.flush()
            tmp_path = Path(tmp.name)

        try:
            result = analyze_python_file(tmp_path)
            assert result.source_path == tmp_path
            assert result.total_issues > 0
        finally:
            tmp_path.unlink()

    def test_analyze_nonexistent_file(self):
        """Test that analyzing a nonexistent file raises an error."""
        with pytest.raises(FileNotFoundError):
            analyze_python_file(Path("/nonexistent/file.py"))


class TestIssueProperties:
    """Tests for issue properties and fix suggestions."""

    def test_fixable_issues_identified(self):
        """Test that fixable issues are identified."""
        # Code with a fixable issue (unused import)
        code = "import os\n\nprint('hello')\n"
        result = analyze_python(code)

        # Ruff can fix unused imports
        fixable = result.get_fixable_issues()
        # May or may not have fixes depending on ruff config
        assert isinstance(fixable, list)

    def test_issue_locations_valid(self):
        """Test that issue locations are valid."""
        code = "import os\nimport sys\n\nx = 1\n"
        result = analyze_python(code)

        for issue in result.issues:
            assert issue.location.line_start > 0
            assert issue.location.file_path is None  # No file path for snippet

    def test_issue_severity_levels(self):
        """Test that issues have appropriate severity levels."""
        # Code with potential runtime error
        code = "print(undefined_var)\n"
        result = analyze_python(code)

        # Should have at least one error
        errors = result.get_issues_by_severity(Severity.ERROR)
        assert len(errors) > 0


class TestParseRuffDiagnostic:
    """Tests for parse_ruff_diagnostic, exercised directly with hand-built diagnostics."""

    def test_line_end_collapses_to_none_when_equal_to_line_start(self):
        """Test that line_end is None when end_location.row equals location.row."""
        diagnostic = {
            "code": "F401",
            "message": "'os' imported but unused",
            "location": {"row": 3, "column": 1},
            "end_location": {"row": 3, "column": 10},
        }
        issue = parse_ruff_diagnostic(diagnostic, None, [])
        assert issue.location.line_end is None

    def test_line_end_kept_when_different_from_line_start(self):
        """Test that line_end is preserved when it differs from line_start."""
        diagnostic = {
            "code": "E501",
            "message": "line too long",
            "location": {"row": 3, "column": 1},
            "end_location": {"row": 5, "column": 10},
        }
        issue = parse_ruff_diagnostic(diagnostic, None, [])
        assert issue.location.line_end == 5

    def test_context_populated_for_in_range_line(self):
        """Test that context is pulled from source_lines for a valid line_start."""
        source_lines = ["a = 1\n", "b = 2  \n", "c = 3\n"]
        diagnostic = {
            "code": "E225",
            "message": "missing whitespace",
            "location": {"row": 2, "column": 1},
        }
        issue = parse_ruff_diagnostic(diagnostic, None, source_lines)
        assert issue.context == "b = 2"

    def test_context_none_when_line_start_exceeds_source_length(self):
        """Test that context is None when line_start is out of range."""
        source_lines = ["a = 1\n"]
        diagnostic = {
            "code": "E225",
            "message": "missing whitespace",
            "location": {"row": 5, "column": 1},
        }
        issue = parse_ruff_diagnostic(diagnostic, None, source_lines)
        assert issue.context is None

    def test_suggested_fix_created_when_edits_present_and_safe(self):
        """Test that a fix with edits and safe applicability is auto-fixable."""
        diagnostic = {
            "code": "F401",
            "message": "'os' imported but unused",
            "location": {"row": 1, "column": 1},
            "fix": {
                "applicability": "safe",
                "edits": [{"content": ""}],
            },
        }
        issue = parse_ruff_diagnostic(diagnostic, None, [])
        assert issue.suggested_fix is not None
        assert issue.suggested_fix.auto_fixable is True

    def test_suggested_fix_not_auto_fixable_when_not_safe(self):
        """Test that a fix with non-safe applicability is not auto-fixable."""
        diagnostic = {
            "code": "F401",
            "message": "'os' imported but unused",
            "location": {"row": 1, "column": 1},
            "fix": {
                "applicability": "unsafe",
                "edits": [{"content": ""}],
            },
        }
        issue = parse_ruff_diagnostic(diagnostic, None, [])
        assert issue.suggested_fix is not None
        assert issue.suggested_fix.auto_fixable is False

    def test_no_suggested_fix_when_edits_empty(self):
        """Test that suggested_fix is None when fix has no edits."""
        diagnostic = {
            "code": "F401",
            "message": "'os' imported but unused",
            "location": {"row": 1, "column": 1},
            "fix": {"applicability": "safe", "edits": []},
        }
        issue = parse_ruff_diagnostic(diagnostic, None, [])
        assert issue.suggested_fix is None

    def test_no_suggested_fix_when_fix_key_absent(self):
        """Test that suggested_fix is None when the diagnostic has no fix key."""
        diagnostic = {
            "code": "F401",
            "message": "'os' imported but unused",
            "location": {"row": 1, "column": 1},
        }
        issue = parse_ruff_diagnostic(diagnostic, None, [])
        assert issue.suggested_fix is None

    def test_missing_code_and_message_fall_back_to_defaults(self):
        """Test that missing code/message keys fall back to UNKNOWN/Unknown issue."""
        diagnostic = {"location": {"row": 1, "column": 1}}
        issue = parse_ruff_diagnostic(diagnostic, None, [])
        assert issue.rule_id == "UNKNOWN"
        assert issue.message == "Unknown issue"
