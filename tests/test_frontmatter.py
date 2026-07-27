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

    def test_inline_comment_is_stripped_from_scalar(self) -> None:
        text = "---\nname: agent-name # Must match directory name\n---\n"
        assert _parse_frontmatter(text) == {"name": "agent-name"}

    def test_inline_comment_is_stripped_from_inline_list(self) -> None:
        text = "---\nadd: [a, b] # note\n---\n"
        assert _parse_frontmatter(text) == {"add": ["a", "b"]}

    def test_full_line_comment_with_colon_is_ignored(self) -> None:
        text = "---\nname: foo\n# TODO: revisit\nrole: bar\n---\n"
        assert _parse_frontmatter(text) == {"name": "foo", "role": "bar"}


class TestParseFrontmatterBlockScalar:
    """YAML block scalars (``>`` folded and ``|`` literal) fold indented
    continuation lines into a single space-joined string.
    """

    def test_folded_block_scalar_spans_multiple_lines(self) -> None:
        # Mirrors core/skills/commit/SKILL.md's `description: >` style.
        text = (
            "---\n"
            "name: commit\n"
            "description: >\n"
            "  Git commit workflow with enforced conventional commit style. Use when Claude\n"
            "  needs to stage and commit changes, craft commit messages, or the user asks to\n"
            "  commit, make a commit, or save their work.\n"
            "---\n"
        )
        assert _parse_frontmatter(text) == {
            "name": "commit",
            "description": (
                "Git commit workflow with enforced conventional commit style. Use when Claude "
                "needs to stage and commit changes, craft commit messages, or the user asks to "
                "commit, make a commit, or save their work."
            ),
        }

    def test_literal_block_scalar_folds_same_as_folded(self) -> None:
        # The parser doesn't distinguish `|` from `>`; both fold onto one line.
        text = "---\ndescription: |\n  line one\n  line two\n---\n"
        assert _parse_frontmatter(text) == {"description": "line one line two"}

    def test_block_scalar_as_last_field_before_closing_delimiter(self) -> None:
        text = (
            "---\n"
            "name: security-review\n"
            "description: >\n"
            "  Security code review for vulnerabilities with confidence-based reporting.\n"
            "  Use when the user asks for a security review.\n"
            "---\n"
        )
        assert _parse_frontmatter(text) == {
            "name": "security-review",
            "description": (
                "Security code review for vulnerabilities with confidence-based reporting. "
                "Use when the user asks for a security review."
            ),
        }


class TestParseFrontmatterClosingDelimiterLineAnchored:
    """The closing ``---`` must be matched on its own line, not as a
    substring inside a field value (e.g. an em-dash-style separator).
    """

    def test_value_containing_triple_dash_does_not_truncate_parsing(self) -> None:
        text = (
            "---\n"
            "name: foo\n"
            "description: some text --- with a dash-break in it\n"
            "---\n"
            "Body\n"
        )
        assert _parse_frontmatter(text) == {
            "name": "foo",
            "description": "some text --- with a dash-break in it",
        }

    def test_closing_delimiter_with_trailing_spaces(self) -> None:
        text = "---\nname: foo\n---   \nBody\n"
        assert _parse_frontmatter(text) == {"name": "foo"}
