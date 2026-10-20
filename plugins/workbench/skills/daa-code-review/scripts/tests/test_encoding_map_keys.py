"""Per-section pins for ENCODING_CORRUPTION_MAP keys (parent issue #777).

Every key must equal ``mojibake(<target character>)``: the cp1252-mojibake a
real UTF-8 file produces, not a hand-typed Latin-1-style literal. Each row is
``(target character, expected map value, old wrong key or None)``; the value
column is pinned so a key change cannot silently change a fix.
"""

import pytest

from markdown_analyzer import ENCODING_CORRUPTION_MAP, analyze_markdown
from tests.mojibake import mojibake

# #1269: two-byte (Latin-1 range) entries. Only the multiplication sign was
# wrong (0x97 is an em dash in cp1252); the rest are pinned against regression.
TWO_BYTE_ROWS = [
    ("×", "×", "\xc3\x97"),
    ("÷", "÷", None),
    ("±", "±", None),
    ("°", "°", None),
    ("µ", "µ", None),
    ("©", "©", None),
    ("®", "®", None),
    ("£", "£", None),
    ("¥", "¥", None),
    ("½", "½", None),
    ("¼", "¼", None),
    ("¾", "¾", None),
    ("²", "²", None),
    ("³", "³", None),
    (" ", " ", None),
    ("«", "«", None),
    ("»", "»", None),
    ("§", "§", None),
    ("¶", "¶", None),
]


class TestTwoByteKeys:
    """#1269: the Latin-1-range section keys are real mojibake."""

    @pytest.mark.parametrize(("target", "value", "old_key"), TWO_BYTE_ROWS)
    def test_key_is_mojibake_of_target(self, target, value, old_key):
        assert ENCODING_CORRUPTION_MAP[mojibake(target)] == value

    @pytest.mark.parametrize(
        "old_key", [r for _, _, r in TWO_BYTE_ROWS if r is not None]
    )
    def test_old_wrong_key_is_gone(self, old_key):
        assert old_key not in ENCODING_CORRUPTION_MAP

    def test_real_multiplication_mojibake_is_flagged_and_fixed(self):
        content = "# Formula\n\n" + mojibake("Generation × Price") + "\n"
        issues = [i for i in analyze_markdown(content).issues if i.rule_id == "MD050"]
        assert len(issues) == 1
        assert "multiplication sign" in issues[0].message
        assert issues[0].suggested_fix.fixed_code == "Generation × Price"

    @pytest.mark.parametrize("char", ["©", "®", "÷"])
    def test_latin1_range_descriptions(self, char):
        content = "# T\n\nx " + mojibake(char) + " y\n"
        issues = [i for i in analyze_markdown(content).issues if i.rule_id == "MD050"]
        assert len(issues) == 1
        assert issues[0].suggested_fix.fixed_code == f"x {char} y"


# #1270: comparison operators and arrows; every key was wrong. ← and ⇐ end in
# the undefined byte 0x90, so they exercise the helper's C1-control rule.
COMPARISON_ARROW_ROWS = [
    ("≠", "≠", "\xe2\x89\xa0"),
    ("≤", "≤", "\xe2\x89\xa4"),
    ("≥", "≥", "\xe2\x89\xa5"),
    ("≈", "≈", "\xe2\x89\x88"),
    ("←", "←", "\xe2\x86\x90"),
    ("→", "→", "\xe2\x86\x92"),
    ("↑", "↑", "\xe2\x86\x91"),
    ("↓", "↓", "\xe2\x86\x93"),
    ("↔", "↔", "\xe2\x86\x94"),
    ("⇐", "⇐", "\xe2\x87\x90"),
    ("⇒", "⇒", "\xe2\x87\x92"),
]


class TestComparisonAndArrowKeys:
    """#1270: comparison and arrow keys are real mojibake."""

    @pytest.mark.parametrize(("target", "value", "old_key"), COMPARISON_ARROW_ROWS)
    def test_key_is_mojibake_of_target(self, target, value, old_key):
        assert ENCODING_CORRUPTION_MAP[mojibake(target)] == value

    @pytest.mark.parametrize("old_key", [r[2] for r in COMPARISON_ARROW_ROWS])
    def test_old_wrong_key_is_gone(self, old_key):
        assert old_key not in ENCODING_CORRUPTION_MAP

    @pytest.mark.parametrize(("char", "fragment"), [("→", "arrow symbol"), ("≤", "≤")])
    def test_real_mojibake_is_flagged_and_fixed(self, char, fragment):
        content = "# T\n\n" + mojibake(f"a {char} b") + "\n"
        issues = [i for i in analyze_markdown(content).issues if i.rule_id == "MD050"]
        assert len(issues) == 1
        assert fragment in issues[0].message
        assert issues[0].suggested_fix.fixed_code == f"a {char} b"

    @pytest.mark.parametrize("char", ["←", "↑", "↓", "↔"])
    def test_single_byte_arrows_describe_as_arrow_symbol(self, char):
        content = "# T\n\n" + mojibake(char) + "\n"
        issues = [i for i in analyze_markdown(content).issues if i.rule_id == "MD050"]
        assert "arrow symbol" in issues[0].message
