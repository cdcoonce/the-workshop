# Issue #123 — gate note: unrelated pre-existing test failures

## Implementation status

Done. `scripts/smoke_test.py` now strips an optional markdown link title (the
whitespace-delimited text after the path, e.g. `[text](./file.md "Title")`)
before resolving the link target, via a shared `_link_path()` helper used by
both the SKILL.md and AGENT.md link-validation loops. Paths wrapped in
`<...>` (which may legitimately contain spaces) are left intact. Tests added
in `tests/test_smoke.py` cover: a titled link to an existing file passing,
and a titled link to a missing file failing with only the path (not the
title) in the error message, for both SKILL.md and AGENT.md.

## Gate note

A full `pytest` run on this branch also reports 4 failures that are **not**
touched by this change and pre-exist on `HEAD` (commit `4010d37`) with no
uncommitted modifications to the files involved:

- `tests/test_build.py::TestBuildPluginSkills::test_build_copies_specific_core_skills`
- `tests/test_build.py::TestBuildPluginDocs::test_build_copies_agent_matching_doc`
- `tests/test_build.py::TestBuildPluginDocs::test_build_agent_matching_doc_has_content`
- `tests/test_validation.py::TestValidation::test_missing_core_skill_in_list_raises_error`

Root cause (confirmed by reading `scripts/build_preset.py`, unmodified by
this slice): `core.skills` as a list (vs. the literal string `"all"`) is
never copied, there is no docs-copying step for `core/docs/*.md` into
`dist/<preset>/docs/`, and manifest validation never checks list-form
`core.skills` entries against `core/skills/`. These look like an
unfinished, separately-scoped feature whose tests were committed ahead of
the implementation — verified via `git diff HEAD -- tests/test_build.py
tests/test_validation.py scripts/build_preset.py tests/conftest.py`, which
is empty.

Per repo convention (no opportunistic fixes, changes scoped to the issue's
acceptance criteria), I have not touched `scripts/build_preset.py` or its
tests. Flagging here rather than silently expanding scope — these 4
failures should be tracked and fixed under a separate issue.

Separately: this sandboxed session blocks all `Bash` execution of
interpreters (`python3`, `pytest`, `uv run`, even `python3 -m py_compile`)
with "This command requires approval" and no path to grant it, so I could
not execute the test gate myself in this session. The fix was verified by
static code review only (shared-helper placement, call sites in both link
loops, whitespace-split semantics, `<...>`-wrapped path exemption).
