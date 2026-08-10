# Authoring Conventions

Cross-cutting rules for anyone writing or modifying the daa-code-review analyzer
scripts (`markdown_analyzer.py`, `python_analyzer.py`, `scripts/smoke_test.py`).
These exist because the same class of bug keeps recurring as one-off patches; the
convention is the fix that stops the recurrence.

## Scripts

| Script                 | Purpose                                           |
| ---------------------- | ------------------------------------------------- |
| `models.py`            | Data structures (Issue, Severity, AnalysisResult) |
| `python_analyzer.py`   | Python analysis with ruff                         |
| `markdown_analyzer.py` | Markdown quality checks                           |
| `report_generator.py`  | Console and Markdown report generation            |

## URI / scheme detection

Any validator that must decide _"is this an external, non-local URI?"_ — link
checkers, image checkers, reference-link resolvers — MUST make that decision by
matching the RFC 3986 scheme grammar, never by enumerating known prefixes.

**Canonical pattern** (defined once, in `markdown_analyzer.py`):

```python
URI_SCHEME_PATTERN = re.compile(r"^[a-zA-Z][a-zA-Z0-9+.-]*:")
```

A target is an external URI if `URI_SCHEME_PATTERN.match(target)` is truthy. A
target is a _local/relative_ candidate (and must still be resolved and flagged if
broken) only when it has **no** scheme **and** is not one of the two remaining
local forms:

```python
if (
    self.base_path
    and not URI_SCHEME_PATTERN.match(target)
    and not target.startswith("#")   # in-page anchor
    and not target.startswith("/")   # root-relative
):
    # ... resolve against base_path; flag if the file does not exist
```

**Do not** write `target.startswith(("http://", "https://", "mailto:"))` or any
similar hand-maintained prefix list. Enumeration is why the codebase accreted a
run of "also skip `mailto:`", "also skip `tel:`", "also skip `ftp:`" fixes — each
new scheme is a new bug until someone remembers to add it. The regex admits every
current and future scheme (`tel:`, `ftp:`, `data:`, `slack:`, …) by construction.

**Still flag, regardless of the above:** in-page anchors that point nowhere,
root-relative paths, and genuinely broken relative links. The scheme test only
decides _"skip as external"_; it must not suppress real local-link breakage.

**Affected surfaces — keep them consistent:**

- `markdown_analyzer._check_links` — uses `URI_SCHEME_PATTERN` (correct; the
  reference implementation).
- `markdown_analyzer._check_images` — still tests
  `startswith(("http://", "https://", "data:"))`. This is the exact enumeration
  this convention forbids and silently mis-flags image sources like `tel:`/`ftp:`;
  it should migrate to `URI_SCHEME_PATTERN`.
- `scripts/smoke_test.py` link validation — must use the same scheme test so the
  smoke gate and the analyzer never disagree about what counts as external.

Motivating change: PR #142 replaced a hardcoded prefix list in the
broken-relative-link check with this scheme regex.

## Hand-rolled frontmatter parsers

Prefer a real YAML parser (`yaml.safe_load`) when the environment allows it. A
line-based, dependency-free parser is acceptable _only_ as a deliberate fallback,
and when you write one it MUST correctly handle all of the following — or it will
validate malformed frontmatter as valid and pass the bug straight through the gate:

- **Block scalars**: `>` (folded) and `|` (literal), including chomping and indent
  indicators (`>-`, `|+`, `|2`). The value is the folded/literal text of the
  following indented lines — **not** the indicator character. Storing the literal
  `">"` as the value (so `description: >` validates as the string `">"`) is the
  specific regression this rule exists to prevent.
- **Quoted values**: strip a single matching pair of surrounding `"` or `'` before
  using the value.
- **Comments**: strip inline (`key: value  # note`) and full-line (`# note`)
  comments — but not a `#` inside a quoted string or block-scalar body.

A subtle failure mode to test for: inside a folded block scalar, a line that
contains a colon (`a: b`) is scalar _content_, not a nested key — a naive
`"key: value".split(":")` will mis-parse it as a sub-key.

**Required test whenever a frontmatter parser is added or modified:** at least one
fixture exercising a folded/block-scalar value (ideally one whose folded body
contains a colon and a `#`), asserting the parsed value is the folded text, not the
indicator.

Motivating change: PR #105, whose parser first stored the literal block-scalar
indicator and mis-parsed a colon-bearing folded line as a sub-key, requiring a
follow-up correction.
