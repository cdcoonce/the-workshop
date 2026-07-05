"""Tests for the Markdown analyzer module.

This module contains pytest tests for the Markdown documentation analyzer.
"""

from pathlib import Path
import tempfile

import pytest

from models import FileType, Severity
from markdown_analyzer import (
    analyze_markdown,
    analyze_markdown_file,
)


class TestMarkdownAnalyzerHeadings:
    """Tests for heading structure analysis."""

    def test_document_starts_with_h1(self):
        """Test that documents should start with h1."""
        content = "## Not an h1\n\nSome content"
        result = analyze_markdown(content)

        md041_issues = [i for i in result.issues if i.rule_id == "MD041"]
        assert len(md041_issues) == 1
        assert md041_issues[0].severity == Severity.WARNING

    def test_document_with_proper_h1(self):
        """Test that proper h1 doesn't trigger warning."""
        content = "# Proper Title\n\nSome content"
        result = analyze_markdown(content)

        md041_issues = [i for i in result.issues if i.rule_id == "MD041"]
        assert len(md041_issues) == 0

    def test_multiple_h1_headings(self):
        """Test detection of multiple h1 headings."""
        content = "# First Title\n\n# Second Title\n\nContent"
        result = analyze_markdown(content)

        md025_issues = [i for i in result.issues if i.rule_id == "MD025"]
        assert len(md025_issues) == 1

    def test_skipped_heading_levels(self):
        """Test detection of skipped heading levels."""
        content = "# Title\n\n### Skipped h2\n\nContent"
        result = analyze_markdown(content)

        md001_issues = [i for i in result.issues if i.rule_id == "MD001"]
        assert len(md001_issues) == 1
        assert "skipped" in md001_issues[0].message.lower()

    def test_proper_heading_sequence(self):
        """Test that proper heading sequence passes."""
        content = "# Title\n\n## Section\n\n### Subsection\n\nContent"
        result = analyze_markdown(content)

        md001_issues = [i for i in result.issues if i.rule_id == "MD001"]
        assert len(md001_issues) == 0

    def test_duplicate_headings(self):
        """Test detection of duplicate headings."""
        content = "# Title\n\n## Section\n\n## Section\n\nContent"
        result = analyze_markdown(content)

        md024_issues = [i for i in result.issues if i.rule_id == "MD024"]
        assert len(md024_issues) == 1
        assert md024_issues[0].severity == Severity.INFO

    def test_duplicate_headings_across_levels(self):
        """Test that duplicate heading text is flagged regardless of level."""
        content = "# Title\n\n## Setup\n\n### Setup\n\nContent"
        result = analyze_markdown(content)

        md024_issues = [i for i in result.issues if i.rule_id == "MD024"]
        assert len(md024_issues) == 1
        assert md024_issues[0].severity == Severity.INFO


class TestMarkdownAnalyzerHeadingsInCodeBlocks:
    """Heading checks must ignore '#' lines inside fenced code blocks."""

    _HEADING_RULES = ("MD041", "MD025", "MD001", "MD024", "MD022")

    def test_headings_only_inside_code_fence_produce_no_findings(self):
        """A doc whose only '#' lines live in a ``` fence yields no heading findings."""
        content = (
            "Intro text with no real headings.\n"
            "\n"
            "```python\n"
            "# config section\n"
            "# another comment\n"
            "## nested comment\n"
            "```\n"
            "\n"
            "Outro text.\n"
        )
        result = analyze_markdown(content)

        heading_issues = [
            i for i in result.issues if i.rule_id in self._HEADING_RULES
        ]
        assert heading_issues == [], (
            f"expected no heading findings, got "
            f"{[(i.rule_id, i.message) for i in heading_issues]}"
        )

    def test_real_headings_still_detected_with_adjacent_code_fence(self):
        """Real headings are still analyzed; an in-fence '#' does not add a phantom h1."""
        content = (
            "# Title\n"
            "\n"
            "```python\n"
            "# a comment, not a heading\n"
            "```\n"
            "\n"
            "### Skipped\n"
            "\n"
            "Body.\n"
        )
        result = analyze_markdown(content)

        # The real h1->h3 jump is still flagged (real headings ARE processed)...
        md001 = [i for i in result.issues if i.rule_id == "MD001"]
        assert len(md001) == 1
        # ...but the in-fence '# a comment' must not count as a second h1.
        md025 = [i for i in result.issues if i.rule_id == "MD025"]
        assert md025 == []

    def test_missing_blank_line_after_heading_ignores_in_fence(self):
        """MD022 fires for a real heading but not for a '#' line inside a fence."""
        content = (
            "# Title\n"
            "\n"
            "```python\n"
            "# not a heading\n"
            "x = 1\n"
            "```\n"
            "\n"
            "## Real Heading\n"
            "immediately followed text\n"
        )
        result = analyze_markdown(content)

        md022 = [i for i in result.issues if i.rule_id == "MD022"]
        # Exactly one: the real "## Real Heading" with no blank line after it.
        assert len(md022) == 1
        assert md022[0].location.line_start == 8

    def test_heading_inline_code_is_preserved_not_masked(self):
        """Inline code in a real heading must survive: distinct headings that
        differ only inside `backticks` are not false MD024 duplicates."""
        content = "# Use `foo()`\n\n## Use `bar()`\n\nBody.\n"
        result = analyze_markdown(content)

        # If inline code were blanked, both would normalize to "use" -> duplicate.
        md024 = [i for i in result.issues if i.rule_id == "MD024"]
        assert md024 == []

    def test_crlf_fenced_code_is_masked(self):
        """Fences in CRLF (Windows) files are masked too — '#' lines inside them
        must not become phantom headings."""
        content = (
            "# Title\r\n"
            "\r\n"
            "```py\r\n"
            "# comment\r\n"
            "```\r\n"
            "\r\n"
            "## After\r\n"
            "text\r\n"
        )
        result = analyze_markdown(content)

        # '# comment' inside the fence must not register as a second h1.
        md025 = [i for i in result.issues if i.rule_id == "MD025"]
        assert md025 == []

    def test_non_word_language_token_fence_is_masked(self):
        """A fence whose language tag has non-word chars (c++, f#, objective-c)
        is still masked."""
        content = "# T\n\n```c++\n# not a heading\n```\n\n## After\ntext\n"
        result = analyze_markdown(content)

        md025 = [i for i in result.issues if i.rule_id == "MD025"]
        assert md025 == []

    def test_tilde_fence_is_masked(self):
        """~~~ tilde fences are masked like ``` fences (#248)."""
        content = (
            "# Title\n"
            "\n"
            "~~~python\n"
            "# not a heading\n"
            "# another\n"
            "~~~\n"
            "\n"
            "## After\n"
            "text\n"
        )
        result = analyze_markdown(content)

        md025 = [i for i in result.issues if i.rule_id == "MD025"]
        assert md025 == []
        # in-fence '#' lines must not trip MD022 either; only the real
        # '## After' (line 8, followed by non-blank 'text') should fire.
        md022 = [i for i in result.issues if i.rule_id == "MD022"]
        assert len(md022) == 1
        assert md022[0].location.line_start == 8

    def test_tilde_fence_crlf_is_masked(self):
        """~~~ fences are masked on CRLF files too (#248)."""
        content = (
            "# Title\r\n\r\n~~~py\r\n# not a heading\r\n~~~\r\n\r\n## After\r\ntext\r\n"
        )
        result = analyze_markdown(content)

        assert [i for i in result.issues if i.rule_id == "MD025"] == []

    def test_backtick_fence_inside_tilde_fence_is_masked(self):
        """A ``` fence shown inside a ~~~ fence: the inner '#' is still masked
        (matched-delimiter handling, not a naive alternation) (#248)."""
        content = (
            "# Title\n"
            "\n"
            "~~~markdown\n"
            "```python\n"
            "# inner comment\n"
            "```\n"
            "~~~\n"
            "\n"
            "## After\n"
            "text\n"
        )
        result = analyze_markdown(content)

        assert [i for i in result.issues if i.rule_id == "MD025"] == []

    def test_indented_code_block_is_never_a_heading_source(self):
        """Indented code ('#' at column >=4) is already never a heading —
        HEADING_PATTERN requires column 0 — so no phantom-heading findings
        arise. Regression lock documenting the non-issue (#248)."""
        content = (
            "# Title\n\nintro\n\n    # indented comment\n    # more\n\n## After\ntext\n"
        )
        result = analyze_markdown(content)

        assert [i for i in result.issues if i.rule_id == "MD025"] == []
        assert [i for i in result.issues if i.rule_id == "MD041"] == []


class TestMarkdownAnalyzerLinks:
    """Tests for link analysis."""

    def test_empty_link_text(self):
        """Test detection of empty link text."""
        content = "# Title\n\n[](https://example.com)"
        result = analyze_markdown(content)

        md054_issues = [i for i in result.issues if i.rule_id == "MD054"]
        assert len(md054_issues) >= 1

    def test_empty_link_url(self):
        """Test detection of empty link URL."""
        content = "# Title\n\n[Click here]()"
        result = analyze_markdown(content)

        md042_issues = [i for i in result.issues if i.rule_id == "MD042"]
        assert len(md042_issues) == 1
        assert md042_issues[0].severity == Severity.ERROR

    def test_valid_link(self):
        """Test that valid links pass."""
        content = "# Title\n\n[Example](https://example.com)"
        result = analyze_markdown(content)

        link_issues = [
            i for i in result.issues if i.rule_id in ("MD042", "MD054", "MD055")
        ]
        assert len(link_issues) == 0

    def test_broken_relative_link(self):
        """Test detection of broken relative links."""
        with tempfile.TemporaryDirectory() as tmpdir:
            tmppath = Path(tmpdir)
            md_file = tmppath / "test.md"
            md_file.write_text("# Title\n\n[Link](nonexistent.md)")

            result = analyze_markdown_file(md_file)

            md055_issues = [i for i in result.issues if i.rule_id == "MD055"]
            assert len(md055_issues) == 1
            assert "not found" in md055_issues[0].message.lower()

    def test_titled_link_to_existing_file_is_not_broken(self):
        """Test that a link title suffix doesn't cause a false-positive broken link."""
        with tempfile.TemporaryDirectory() as tmpdir:
            tmppath = Path(tmpdir)
            (tmppath / "guide.md").write_text("# Guide")
            md_file = tmppath / "test.md"
            md_file.write_text('# Title\n\n[docs](guide.md "My Title")')

            result = analyze_markdown_file(md_file)

            md055_issues = [i for i in result.issues if i.rule_id == "MD055"]
            assert md055_issues == []

    def test_query_string_link_to_existing_file_is_not_broken(self):
        """Test that a query string suffix doesn't cause a false-positive broken link."""
        with tempfile.TemporaryDirectory() as tmpdir:
            tmppath = Path(tmpdir)
            (tmppath / "guide.md").write_text("# Guide")
            md_file = tmppath / "test.md"
            md_file.write_text("# Title\n\n[docs](guide.md?v=2)")

            result = analyze_markdown_file(md_file)

            md055_issues = [i for i in result.issues if i.rule_id == "MD055"]
            assert md055_issues == []

    def test_uri_scheme_links_are_not_broken_relative_links(self):
        """Test that URI scheme links are not checked as local files."""
        with tempfile.TemporaryDirectory() as tmpdir:
            tmppath = Path(tmpdir)
            md_file = tmppath / "test.md"
            md_file.write_text(
                "# Title\n\n"
                "[Phone](tel:+15551234)\n"
                "[FTP](ftp://example.com/file.txt)\n"
                "[Mail](mailto:test@example.com)\n"
                "[Anchor](#section)\n"
                "[Root](/docs/page.md)\n"
                "[Missing](missing.md)\n"
            )

            result = analyze_markdown_file(md_file)

            md055_issues = [i for i in result.issues if i.rule_id == "MD055"]
            assert len(md055_issues) == 1
            assert "missing.md" in md055_issues[0].message


class TestMarkdownAnalyzerImages:
    """Tests for image analysis."""

    def test_missing_alt_text(self):
        """Test detection of missing alt text."""
        content = "# Title\n\n![](image.png)"
        result = analyze_markdown(content)

        md045_issues = [i for i in result.issues if i.rule_id == "MD045"]
        assert len(md045_issues) == 1
        assert md045_issues[0].severity == Severity.WARNING

    def test_image_with_alt_text(self):
        """Test that images with alt text pass."""
        content = "# Title\n\n![Alt description](image.png)"
        result = analyze_markdown(content)

        alt_issues = [i for i in result.issues if i.rule_id == "MD045"]
        assert len(alt_issues) == 0

    def test_image_only_document_has_no_link_findings(self):
        """Test that image syntax isn't re-flagged by the link checker."""
        with tempfile.TemporaryDirectory() as tmpdir:
            tmppath = Path(tmpdir)
            md_file = tmppath / "test.md"
            md_file.write_text("# Title\n\n![](missing.png)")

            result = analyze_markdown_file(md_file)

            md055_issues = [i for i in result.issues if i.rule_id == "MD055"]
            assert md055_issues == []

            md045_issues = [i for i in result.issues if i.rule_id == "MD045"]
            assert len(md045_issues) == 1

            md056_issues = [i for i in result.issues if i.rule_id == "MD056"]
            assert len(md056_issues) == 1

    def test_root_relative_image_is_not_broken_image(self):
        """Test that root-relative image paths are not checked as local files."""
        with tempfile.TemporaryDirectory() as tmpdir:
            tmppath = Path(tmpdir)
            md_file = tmppath / "test.md"
            md_file.write_text(
                "# Title\n\n![Logo](/assets/logo.png)\n![Missing](missing.png)\n"
            )

            result = analyze_markdown_file(md_file)

            md056_issues = [i for i in result.issues if i.rule_id == "MD056"]
            assert len(md056_issues) == 1
            assert "missing.png" in md056_issues[0].message


class TestMarkdownAnalyzerReferenceLinks:
    """Tests for reference link analysis."""

    def test_undefined_reference_link(self):
        """Test detection of undefined reference links."""
        content = "# Title\n\n[Link][undefined]"
        result = analyze_markdown(content)

        md052_issues = [i for i in result.issues if i.rule_id == "MD052"]
        assert len(md052_issues) == 1

    def test_defined_reference_link(self):
        """Test that defined reference links pass."""
        content = "# Title\n\n[Link][ref]\n\n[ref]: https://example.com"
        result = analyze_markdown(content)

        ref_issues = [i for i in result.issues if i.rule_id == "MD052"]
        assert len(ref_issues) == 0

    def test_code_subscript_in_fenced_block_not_flagged(self):
        """Test that double-subscript code in a fenced block isn't flagged."""
        content = "# Title\n\n```py\nmatrix[0][1]\n```\n"
        result = analyze_markdown(content)

        md052_issues = [i for i in result.issues if i.rule_id == "MD052"]
        assert len(md052_issues) == 0

    def test_code_subscript_in_inline_code_not_flagged(self):
        """Test that double-subscript code in an inline code span isn't flagged."""
        content = "# Title\n\nUse `grid[i][j]` to access the cell."
        result = analyze_markdown(content)

        md052_issues = [i for i in result.issues if i.rule_id == "MD052"]
        assert len(md052_issues) == 0

    def test_undefined_reference_link_line_number_after_code_block(self):
        """Test that line numbers stay correct when a code block precedes a real link."""
        content = "# Title\n\n```py\nmatrix[0][1]\n```\n\n[Link][undefined]\n"
        result = analyze_markdown(content)

        md052_issues = [i for i in result.issues if i.rule_id == "MD052"]
        assert len(md052_issues) == 1
        assert md052_issues[0].location.line_start == 7


class TestMarkdownAnalyzerFormatting:
    """Tests for formatting analysis."""

    def test_trailing_whitespace(self):
        """Test detection of trailing whitespace."""
        content = "# Title\n\nSome text with trailing   \n\nMore text"
        result = analyze_markdown(content)

        md009_issues = [i for i in result.issues if i.rule_id == "MD009"]
        assert len(md009_issues) >= 1
        assert md009_issues[0].severity == Severity.INFO

    def test_trailing_two_spaces_is_intentional_line_break(self):
        """Test that exactly two trailing spaces are not flagged."""
        content = "# Title\n\nSome text with a line break  \nMore text"
        result = analyze_markdown(content)

        md009_issues = [i for i in result.issues if i.rule_id == "MD009"]
        assert len(md009_issues) == 0

    def test_trailing_tab_combination_is_flagged(self):
        """Test that a tab-containing two-char trailing run is not treated as a line break."""
        content = "# Title\n\nSome text with trailing\t\t\nMore text"
        result = analyze_markdown(content)

        md009_issues = [i for i in result.issues if i.rule_id == "MD009"]
        assert len(md009_issues) >= 1

    def test_multiple_blank_lines(self):
        """Test detection of multiple consecutive blank lines."""
        content = "# Title\n\n\n\nContent with too many blank lines"
        result = analyze_markdown(content)

        md012_issues = [i for i in result.issues if i.rule_id == "MD012"]
        assert len(md012_issues) >= 1

    def test_missing_blank_after_heading(self):
        """Test detection of missing blank line after heading."""
        content = "# Title\nNo blank line after heading"
        result = analyze_markdown(content)

        md022_issues = [i for i in result.issues if i.rule_id == "MD022"]
        assert len(md022_issues) >= 1


class TestMarkdownAnalyzerCodeBlocks:
    """Tests for code block analysis."""

    def test_code_block_without_language(self):
        """Test detection of code blocks without language identifier."""
        content = "# Title\n\n```\nsome code\n```"
        result = analyze_markdown(content)

        md040_issues = [i for i in result.issues if i.rule_id == "MD040"]
        assert len(md040_issues) == 1

    def test_code_block_with_language(self):
        """Test that code blocks with language pass."""
        content = "# Title\n\n```python\nprint('hello')\n```"
        result = analyze_markdown(content)

        md040_issues = [i for i in result.issues if i.rule_id == "MD040"]
        assert len(md040_issues) == 0


class TestMarkdownAnalyzeFunction:
    """Tests for the main analyze_markdown function."""

    def test_returns_analysis_result(self):
        """Test that function returns AnalysisResult."""
        result = analyze_markdown("# Title\n\nContent")
        assert result.file_type == FileType.MARKDOWN

    def test_includes_source_content(self):
        """Test that result includes source content."""
        content = "# Title\n\nContent"
        result = analyze_markdown(content)
        assert result.source_content == content

    def test_includes_tools_used(self):
        """Test that result includes tools used."""
        result = analyze_markdown("# Title\n\nContent")
        assert "markdown-analyzer" in result.tools_used

    def test_records_analysis_time(self):
        """Test that analysis time is recorded."""
        result = analyze_markdown("# Title\n\nContent")
        assert result.analysis_time_seconds >= 0

    def test_with_file_path(self):
        """Test analysis with file path specified."""
        result = analyze_markdown("# Title", file_path=Path("test.md"))
        assert result.source_path == Path("test.md")


class TestMarkdownAnalyzeFile:
    """Tests for the analyze_markdown_file function."""

    def test_analyze_existing_file(self):
        """Test analyzing an existing Markdown file."""
        with tempfile.NamedTemporaryFile(mode="w", suffix=".md", delete=False) as tmp:
            tmp.write("## No h1\n\nContent")
            tmp.flush()
            tmp_path = Path(tmp.name)

        try:
            result = analyze_markdown_file(tmp_path)
            assert result.source_path == tmp_path
            assert result.total_issues > 0
        finally:
            tmp_path.unlink()

    def test_analyze_nonexistent_file(self):
        """Test that analyzing a nonexistent file raises an error."""
        with pytest.raises(FileNotFoundError):
            analyze_markdown_file(Path("/nonexistent/file.md"))


class TestMarkdownAnalyzerSuggestedFixes:
    """Tests for suggested fixes."""

    def test_fix_for_heading_level(self):
        """Test that heading level issues have suggested fixes."""
        content = "### Skipped to h3\n\nContent"
        result = analyze_markdown(content)

        md041_issues = [i for i in result.issues if i.rule_id == "MD041"]
        assert len(md041_issues) > 0
        assert md041_issues[0].suggested_fix is not None
        assert md041_issues[0].suggested_fix.auto_fixable

    def test_fix_for_multiple_blank_lines(self):
        """Test that multiple blank lines have suggested fix."""
        content = "# Title\n\n\n\nContent"
        result = analyze_markdown(content)

        md012_issues = [i for i in result.issues if i.rule_id == "MD012"]
        assert len(md012_issues) > 0
        assert md012_issues[0].suggested_fix is not None
        assert md012_issues[0].suggested_fix.fixed_code == "\n\n"


class TestCleanMarkdown:
    """Tests with clean Markdown content."""

    def test_clean_document(self):
        """Test that a well-formed document has minimal issues."""
        content = """# My Document

This is a well-formed Markdown document.

## Section One

Some content here with a [valid link](https://example.com).

## Section Two

More content with properly formatted code:

```python
print("Hello, World!")
```

### Subsection

Final content.
"""
        result = analyze_markdown(content)
        # Well-formed content should have few or no errors
        assert result.error_count == 0
