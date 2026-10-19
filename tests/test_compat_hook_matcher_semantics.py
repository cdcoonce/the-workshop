"""COMPATIBILITY.md records how hook matchers are evaluated (anchored vs search)."""

from pathlib import Path

TEXT = (Path(__file__).resolve().parent.parent / "COMPATIBILITY.md").read_text()


def test_claude_code_matcher_semantics_recorded_with_source() -> None:
    assert "#### Matcher semantics" in TEXT
    section = TEXT[TEXT.index("#### Matcher semantics") :]
    section = section[: section.index("\n### ")]
    assert "https://code.claude.com/docs/en/hooks" in section
    assert "unanchored" in section
    assert "^Edit$" in section
    assert "Cortex" in section and "unverified" in section
