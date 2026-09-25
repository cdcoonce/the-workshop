---
name: mr-preflight
description: Catches stale references before a GitLab MR opens: names a diff renamed that code, SQL or docs still use. Use when creating an MR into dev, when create-mr refuses with an mr-preflight hit, or when a doc still names an old schema or function.
---

# MR preflight

Deterministic checks that run before a merge request exists, so the defects a
reviewer would otherwise find mechanically never reach review.

## The reference sweep

A rename lands in one file while a SQL script, a runbook or a config elsewhere
keeps the old name. Anyone following the stale doc builds the retired thing.
The sweep finds every identifier the branch renamed and reports each reference
to the old name that survives at `HEAD`.

It runs automatically: `gitlab-mr-create` sweeps every MR into `dev` from the
merge-base with `origin/dev` and refuses to open the MR while a hit remains.
It fails closed when `origin/dev` is missing; fetch it and retry. Other
targets are not swept.

### Reading a hit

```text
sql/audit/01_tables.sql:17: LEGACY_SCHEMA (renamed to LEGACY_SCHEMA_RAW in dbt_project.yml)
```

The old name, where it survives, what replaced it and where the rename
happened. Fix the reference at that path and line, commit, and create the MR
again. Every hit blocks.

### What counts as a rename

- **Paired lines only.** Within a hunk, removed lines are compared with the
  added lines that follow them, position by position. A name on the removed
  line that is absent from its partner is renamed.
- **Distinctive names only.** The name must contain `_`, `.` or an internal
  capital, be at least 6 characters, and not be a dunder. `rows` or `a_b`
  would match too much unrelated text to mean anything.
- **Moved is not renamed.** A name the diff adds on any other line is still in
  use, so its references stand.
- **A deletion is not a rename.** Removing a call with no replacement line
  never chases the function it called.
- **Qualified names chase their parts.** Rewriting `LEGACY_SCHEMA.prices`
  chases the bare `LEGACY_SCHEMA`, so a `USE SCHEMA` line elsewhere is found.
  A dotted name with no distinctive part (`pkg.module`) is chased whole.

Matches are whole words (`git grep -w`) over the committed `HEAD` tree of the
whole repository, wherever it is run from, so `LEGACY_SCHEMA_RAW` never counts
as `LEGACY_SCHEMA` and uncommitted edits are invisible. Binary files are
skipped.

## Running it by hand

From the repository, before creating the MR or in any git repo:

```bash
python3 "<skill base directory>/scripts/mr_preflight.py" sweep --base origin/dev
```

Exit `0` is clean, `1` means surviving references (listed on stdout), `2` is a
setup error such as an unresolvable base.

`<skill base directory>` is the absolute path this skill's loader announces
(`Base directory for this skill: /…/skills/mr-preflight`). Expand it inline.
It is not a shell variable, and `$CLAUDE_PLUGIN_ROOT` exists only in hooks, so
a path built from it fails. A bare `scripts/mr_preflight.py` fails too, because
`cwd` is the target repository.

## Boundaries

- Behavioral drift, where a doc describes behavior that changed without any
  name changing, is out of reach of a name sweep. Use `adversarial-review`.
- Edge-case correctness is judgment, not a sweep. Use `adversarial-review`.
- Only `gitlab-mr-create` enforces the sweep. On GitHub, run it by hand.
