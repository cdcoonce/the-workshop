"""Tests for encoding corruption detection in Markdown.

This module tests the detection and fixing of UTF-8 encoding issues
where characters appear corrupted (e.g., Ã— instead of ×).
"""

from markdown_analyzer import analyze_markdown
from models import Severity
from tests.mojibake import mojibake


class TestEncodingCorruptionDetection:
    """Tests for detecting UTF-8 encoding corruption."""

    def test_detect_multiplication_sign_corruption(self):
        """Test detection of corrupted multiplication sign (Ã— → ×)."""
        content = "# Formula\n\nGeneration " + mojibake("×") + " Contract Price"
        result = analyze_markdown(content)

        encoding_issues = [
            i for i in result.issues
            if i.rule_id == "MD050" and "encoding" in i.message.lower()
        ]
        assert len(encoding_issues) >= 1
        assert encoding_issues[0].severity == Severity.ERROR

    def test_detect_checkmark_corruption(self):
        """Test detection of corrupted checkmark (âœ" → ✓)."""
        content = "# Status\n\n| Done | Task |\n|------|------|\n| " + mojibake("✓") + " | Item |"
        result = analyze_markdown(content)

        encoding_issues = [
            i for i in result.issues
            if i.rule_id == "MD050" and "encoding" in i.message.lower()
        ]
        assert len(encoding_issues) >= 1
        assert "checkmark symbol" in encoding_issues[0].message

    def test_detect_box_drawing_corruption(self):
        """Test detection of corrupted box-drawing characters."""
        content = "# Diagram\n\n```\n\xe2\x94\x8c\xe2\x94\x80\xe2\x94\x80\xe2\x94\x80\xe2\x94\x90\n\xe2\x94\x82 Box \xe2\x94\x82\n\xe2\x94\x94\xe2\x94\x80\xe2\x94\x80\xe2\x94\x80\xe2\x94\x98\n```"
        result = analyze_markdown(content)

        encoding_issues = [
            i for i in result.issues
            if i.rule_id == "MD050" and "encoding" in i.message.lower()
        ]
        assert len(encoding_issues) >= 1

    def test_detect_arrow_corruption(self):
        """Test detection of corrupted arrow symbols (â† → ←)."""
        content = "# Flow\n\nData " + mojibake("←") + " Source"
        result = analyze_markdown(content)

        encoding_issues = [
            i for i in result.issues
            if i.rule_id == "MD050"
        ]
        assert len(encoding_issues) >= 1
        assert "arrow symbol" in encoding_issues[0].message

    def test_detect_dash_corruption(self):
        """Test detection of corrupted em-dash (â€" → —)."""
        content = "# Title\n\nThis " + mojibake("—") + " that"
        result = analyze_markdown(content)

        encoding_issues = [
            i for i in result.issues
            if i.rule_id == "MD050"
        ]
        assert len(encoding_issues) >= 1
        assert "dash character" in encoding_issues[0].message
        assert encoding_issues[0].suggested_fix.fixed_code == "This — that"

    def test_detect_bullet_corruption(self):
        """Test detection of corrupted bullet points (â€¢ → •)."""
        bullet = mojibake("•")
        content = f"# List\n\n{bullet} Item one\n{bullet} Item two"
        result = analyze_markdown(content)

        encoding_issues = [
            i for i in result.issues
            if i.rule_id == "MD050"
        ]
        assert len(encoding_issues) >= 1
        assert "bullet point" in encoding_issues[0].message
        assert encoding_issues[0].suggested_fix.fixed_code == "• Item one"

    def test_no_false_positives_clean_content(self):
        """Test that clean content doesn't trigger encoding issues."""
        content = "# Clean Document\n\nThis is normal text with proper Unicode."
        result = analyze_markdown(content)

        encoding_issues = [
            i for i in result.issues
            if i.rule_id == "MD050"
        ]
        assert len(encoding_issues) == 0

    def test_suggested_fix_provided(self):
        """Test that encoding issues have suggested fixes."""
        content = "# Formula\n\nValue " + mojibake("×") + " 10"
        result = analyze_markdown(content)

        encoding_issues = [
            i for i in result.issues
            if i.rule_id == "MD050"
        ]
        assert len(encoding_issues) >= 1
        assert encoding_issues[0].suggested_fix is not None
        # The fix should contain the proper character (×)
        assert "×" in encoding_issues[0].suggested_fix.fixed_code
        assert "Value × 10" in encoding_issues[0].suggested_fix.fixed_code

    def test_multiple_corruptions_same_line(self):
        """Test detection of multiple corruptions on same line."""
        # A × B → C (multiplication and arrow)
        content = "# Math\n\nA " + mojibake("×") + " B " + mojibake("→") + " C"
        result = analyze_markdown(content)

        encoding_issues = [
            i for i in result.issues
            if i.rule_id == "MD050"
        ]
        # Should find corruptions (at least one per line)
        assert len(encoding_issues) >= 1
        assert encoding_issues[0].suggested_fix.fixed_code == "A × B → C"

    def test_corruption_in_table(self):
        """Test detection of corruption in markdown tables."""
        mul = mojibake("×")
        dash = mojibake("—")
        content = f"""# Revenue

| Component | Formula |
|-----------|---------|
| Revenue | Generation {mul} Price |
| Cost | Hub {dash} Node |
"""
        result = analyze_markdown(content)

        encoding_issues = [
            i for i in result.issues
            if i.rule_id == "MD050"
        ]
        assert len(encoding_issues) >= 1

    def test_fix_is_auto_fixable(self):
        """Test that encoding fixes are marked as auto-fixable."""
        content = "# Test\n\nDone " + mojibake("✓")
        result = analyze_markdown(content)

        encoding_issues = [
            i for i in result.issues
            if i.rule_id == "MD050"
        ]
        assert len(encoding_issues) >= 1
        assert encoding_issues[0].suggested_fix is not None
        assert encoding_issues[0].suggested_fix.auto_fixable is True
        assert encoding_issues[0].suggested_fix.fixed_code == "Done ✓"


class TestEncodingCorruptionPatterns:
    """Tests for specific encoding corruption patterns."""

    def test_multiplication_pattern(self):
        """Test multiplication sign corruption."""
        content = "# Test\n\nText with " + mojibake("×") + " symbol"
        result = analyze_markdown(content)
        encoding_issues = [i for i in result.issues if i.rule_id == "MD050"]
        assert len(encoding_issues) >= 1

    def test_division_pattern(self):
        """Test division sign corruption."""
        content = "# Test\n\nText with " + mojibake("÷") + " symbol"
        result = analyze_markdown(content)
        encoding_issues = [i for i in result.issues if i.rule_id == "MD050"]
        assert len(encoding_issues) >= 1

    def test_copyright_pattern(self):
        """Test copyright sign corruption."""
        content = "# Test\n\nText with " + mojibake("©") + " symbol"
        result = analyze_markdown(content)
        encoding_issues = [i for i in result.issues if i.rule_id == "MD050"]
        assert len(encoding_issues) >= 1

    def test_registered_pattern(self):
        """Test registered sign corruption."""
        content = "# Test\n\nText with " + mojibake("®") + " symbol"
        result = analyze_markdown(content)
        encoding_issues = [i for i in result.issues if i.rule_id == "MD050"]
        assert len(encoding_issues) >= 1

    def test_box_drawing_patterns(self):
        """Test box-drawing character corruption patterns."""
        # Box drawing: ┌── (corrupted as â"Œâ"€â"€)
        content = "# Diagram\n\n```\n\xe2\x94\x8c\xe2\x94\x80\xe2\x94\x80\n```"
        result = analyze_markdown(content)

        encoding_issues = [
            i for i in result.issues
            if i.rule_id == "MD050"
        ]
        assert len(encoding_issues) >= 1


class TestEncodingFixApplication:
    """Tests for applying encoding fixes."""

    def test_fix_replaces_corruption(self):
        """Test that the fix correctly replaces corrupted text."""
        content = "# Formula\n\nGeneration " + mojibake("×") + " Contract Price"
        result = analyze_markdown(content)

        encoding_issues = [
            i for i in result.issues
            if i.rule_id == "MD050"
        ]
        assert len(encoding_issues) >= 1

        fix = encoding_issues[0].suggested_fix
        assert fix is not None
        # The fixed code should contain the proper multiplication sign
        assert "×" in fix.fixed_code
        # And not contain the corrupted sequence
        assert mojibake("×") not in fix.fixed_code

    def test_context_shows_corrupted_line(self):
        """Test that issue context shows the corrupted line."""
        corrupted = mojibake("×")
        content = f"# Test\n\nBad line with {corrupted} here"
        result = analyze_markdown(content)

        encoding_issues = [
            i for i in result.issues
            if i.rule_id == "MD050"
        ]
        assert len(encoding_issues) >= 1
        assert encoding_issues[0].context is not None
        # Context should contain the original corrupted text
        assert corrupted in encoding_issues[0].context


class TestRealWorldCorruption:
    """Tests based on real-world corruption examples."""

    def test_table_with_multiplication(self):
        """Test table with corrupted multiplication signs (from user example)."""
        mul = mojibake("×")
        content = f"""# Revenue Components

| Revenue Component | Formula | When It Applies |
|-------------------|---------|-----------------|
| Contract Revenue | Generation {mul} Contract Price | Fixed-price PPAs |
| Merchant Revenue | Generation {mul} Spot Price | Uncontracted energy |
| Basis Cost | (Hub Price - Node Price) {mul} Generation | VPPAs |
"""
        result = analyze_markdown(content)
        encoding_issues = [i for i in result.issues if i.rule_id == "MD050"]
        assert len(encoding_issues) >= 1
        # Each row with Ã— should be detected
        assert len(encoding_issues) >= 3

    def test_formula_calculation(self):
        """Test corrupted formula calculation (from user example)."""
        mul = mojibake("×")
        dash = mojibake("—")
        content = f"""# Example Calculation

Swap Settlement = (Fixed {dash} Index) {mul} Volume
               = ($45 {dash} $38) {mul} 10,000
               = $70,000
"""
        result = analyze_markdown(content)
        encoding_issues = [i for i in result.issues if i.rule_id == "MD050"]
        assert len(encoding_issues) >= 1

    def test_enterprise_matrix_checkmarks(self):
        """Test table with corrupted checkmarks (from user example)."""
        tick = mojibake("✓")
        content = f"""# Enterprise Bus Matrix

| Business Process | Facility | Date |
|------------------|----------|------|
| Daily Generation | {tick} | {tick} |
| Hourly Basis | {tick} | {tick} |
"""
        result = analyze_markdown(content)
        encoding_issues = [i for i in result.issues if i.rule_id == "MD050"]
        assert len(encoding_issues) >= 1

    def test_box_diagram(self):
        """Test corrupted ASCII box diagram (from user example)."""
        content = """# MCP Protocol Layers

```
\xe2\x94\x8c\xe2\x94\x80\xe2\x94\x80\xe2\x94\x80\xe2\x94\x80\xe2\x94\x80\xe2\x94\x80\xe2\x94\x80\xe2\x94\x80\xe2\x94\x80\xe2\x94\x80\xe2\x94\x80\xe2\x94\x80\xe2\x94\x80\xe2\x94\x80\xe2\x94\x80\xe2\x94\x90
\xe2\x94\x82   Application    \xe2\x94\x82  \xe2\x86\x90 Claude
\xe2\x94\x9c\xe2\x94\x80\xe2\x94\x80\xe2\x94\x80\xe2\x94\x80\xe2\x94\x80\xe2\x94\x80\xe2\x94\x80\xe2\x94\x80\xe2\x94\x80\xe2\x94\x80\xe2\x94\x80\xe2\x94\x80\xe2\x94\x80\xe2\x94\x80\xe2\x94\x80\xe2\x94\xa4
\xe2\x94\x82   MCP Client     \xe2\x94\x82
\xe2\x94\x94\xe2\x94\x80\xe2\x94\x80\xe2\x94\x80\xe2\x94\x80\xe2\x94\x80\xe2\x94\x80\xe2\x94\x80\xe2\x94\x80\xe2\x94\x80\xe2\x94\x80\xe2\x94\x80\xe2\x94\x80\xe2\x94\x80\xe2\x94\x80\xe2\x94\x80\xe2\x94\x98
```
"""
        result = analyze_markdown(content)
        encoding_issues = [i for i in result.issues if i.rule_id == "MD050"]
        # Should detect box drawing corruption
        assert len(encoding_issues) >= 1
