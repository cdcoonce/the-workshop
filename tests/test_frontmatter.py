"""Direct unit tests for ``_parse_frontmatter`` in smoke_test.py.

``_parse_frontmatter`` hand-rolls a tiny YAML subset (top-level scalars,
inline lists, and one level of nested dicts via indentation detection).
These tests exercise its edge cases directly, rather than only indirectly
through the agent smoke tests.
"""

from scripts.smoke_test import _parse_frontmatter


class TestParseFrontmatterNone:
    """Inputs that should yield ``None``."""

    def test_no_frontmatter_returns_none(self) -> None:
        assert _parse_frontmatter("# Just a heading\n\nSome body text.\n") is None

    def test_unterminated_frontmatter_returns_none(self) -> None:
        # Opening "---" but no closing delimiter.
        assert _parse_frontmatter("---\nname: foo\nrole: bar\n") is None

    def test_empty_frontmatter_returns_none(self) -> None:
        assert _parse_frontmatter("---\n---\n") is None

    def test_whitespace_only_frontmatter_returns_none(self) -> None:
        assert _parse_frontmatter("---\n   \n\n---\n") is None


class TestParseFrontmatterScalars:
    """Top-level ``key: value`` scalar pairs."""

    def test_single_scalar(self) -> None:
        assert _parse_frontmatter("---\nname: tdd-implementer\n---\n") == {
            "name": "tdd-implementer"
        }

    def test_multiple_scalars(self) -> None:
        result = _parse_frontmatter(
            "---\nname: code-reviewer\ndescription: reviews code\nrole: reviewer\n---\n"
        )
        assert result == {
            "name": "code-reviewer",
            "description": "reviews code",
            "role": "reviewer",
        }

    def test_value_whitespace_is_trimmed(self) -> None:
        assert _parse_frontmatter("---\nname:    spaced-out   \n---\n") == {
            "name": "spaced-out"
        }


class TestParseFrontmatterInlineLists:
    """Inline ``key: [a, b, c]`` lists."""

    def test_inline_list_parses_into_python_list(self) -> None:
        assert _parse_frontmatter("---\nskills: [tdd, commit, debug]\n---\n") == {
            "skills": ["tdd", "commit", "debug"]
        }

    def test_inline_list_trims_whitespace_and_drops_empties(self) -> None:
        # Leading/trailing spaces around items plus a stray trailing comma
        # (which yields an empty element) must be cleaned up.
        assert _parse_frontmatter("---\nskills: [ a ,  b , c , ]\n---\n") == {
            "skills": ["a", "b", "c"]
        }

    def test_empty_inline_list(self) -> None:
        assert _parse_frontmatter("---\nskills: []\n---\n") == {"skills": []}


class TestParseFrontmatterNestedDict:
    """One level of nesting: ``skills:`` then indented sub-keys."""

    def test_nested_dict_block(self) -> None:
        text = (
            "---\n"
            "name: tdd-implementer\n"
            "role: implementer\n"
            "skills:\n"
            "  add: [tdd, commit]\n"
            "  remove: []\n"
            "---\n"
        )
        assert _parse_frontmatter(text) == {
            "name": "tdd-implementer",
            "role": "implementer",
            "skills": {"add": ["tdd", "commit"], "remove": []},
        }

    def test_nested_scalar_sub_value(self) -> None:
        text = "---\nmeta:\n  author: charles\n---\n"
        assert _parse_frontmatter(text) == {"meta": {"author": "charles"}}


class TestParseFrontmatterQuotedValues:
    """Quoted scalars and list items have their surrounding quotes stripped."""

    def test_double_quoted_scalar(self) -> None:
        assert _parse_frontmatter('---\nname: "code-reviewer"\n---\n') == {
            "name": "code-reviewer"
        }

    def test_single_quoted_scalar(self) -> None:
        assert _parse_frontmatter("---\nrole: 'reviewer'\n---\n") == {
            "role": "reviewer"
        }

    def test_quoted_inline_list_items(self) -> None:
        assert _parse_frontmatter('---\nskills: ["tdd", "commit"]\n---\n') == {
            "skills": ["tdd", "commit"]
        }

    def test_quoted_nested_sub_scalar(self) -> None:
        text = "---\nmeta:\n  author: 'charles'\n---\n"
        assert _parse_frontmatter(text) == {"meta": {"author": "charles"}}

    def test_quoted_nested_list_items(self) -> None:
        text = '---\nskills:\n  add: ["tdd", "commit"]\n  remove: []\n---\n'
        assert _parse_frontmatter(text) == {
            "skills": {"add": ["tdd", "commit"], "remove": []}
        }

    def test_unquoted_values_unaffected(self) -> None:
        assert _parse_frontmatter("---\nname: code-reviewer\n---\n") == {
            "name": "code-reviewer"
        }


class TestParseFrontmatterCommentsAndSpacing:
    """Lists alongside comment lines and extra spacing parse correctly."""

    def test_standalone_comment_line_is_ignored(self) -> None:
        text = "---\nname: foo\n# this is a comment line\nskills: [a, b]\n---\n"
        assert _parse_frontmatter(text) == {"name": "foo", "skills": ["a", "b"]}

    def test_inline_list_with_extra_spaces(self) -> None:
        # Extra spaces after the colon and between items must not corrupt items.
        assert _parse_frontmatter("---\nskills:    [ tdd ,   commit ]\n---\n") == {
            "skills": ["tdd", "commit"]
        }

    def test_blank_lines_within_frontmatter_are_skipped(self) -> None:
        text = "---\nname: foo\n\nrole: bar\n\n---\n"
        assert _parse_frontmatter(text) == {"name": "foo", "role": "bar"}
