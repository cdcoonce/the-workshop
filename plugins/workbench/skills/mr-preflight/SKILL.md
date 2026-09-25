---
name: mr-preflight
description: Catches stale references before a GitLab MR opens: names a diff renamed that code, SQL or docs still use. Use when creating an MR into dev, when create-mr refuses with an mr-preflight hit, or to waive or permanently ignore an old name.
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
merge-base with `origin/dev` and refuses to open the MR while an unwaived hit
remains. It fails closed when `origin/dev` is missing; fetch it and retry.
Other targets are not swept.

### Reading a hit

```text
sql/audit/01_tables.sql:17: LEGACY_SCHEMA (renamed to LEGACY_SCHEMA_RAW in dbt_project.yml)
```

The old name, where it survives, what replaced it and where the rename
happened. Fix the reference at that path and line, commit, and create the MR
again, or waive it if the old name is meant to stay. Every unwaived hit blocks.

### Waiving a hit

Some old names are correct where they are: a changelog entry, an ADR, a
migration that must keep reading the retired schema. Waive them in the MR
description, inside its sweep block:

```markdown
<!-- mr-preflight:sweep:begin -->

- waive LEGACY_SCHEMA CHANGELOG.md: historical entry, describes the old schema

<!-- mr-preflight:sweep:end -->
```

- **Form:** `- waive TOKEN path: reason`, one per line. `path` is
  repo-relative and exact; backtick it if it holds a space
  (``- waive LEGACY_SCHEMA `docs/Old Notes.md`: quoted design``). The reason
  is required. A path holding a newline, tab, other control character, `"` or `\`
  is reported quoted the way git quotes it (`"docs/new\nline.md"`); waive it
  in that quoted form, exactly as reported.
- **Scope:** a waiver covers every hit of `TOKEN` in that one `path`, whatever
  line it is on, so editing the file above the hit never invalidates it. The
  same name in any other file, even one with the same basename, still blocks.
- **Malformed lines block.** A line that starts like a waiver but does not
  match the form is reported as `malformed waiver:` and blocks, because its
  author believes it waives something. A near miss on the prefix (`* waive`,
  `-waive`, `- Waive`) counts too when the rest of the line is a valid
  waiver; a sentence that merely starts with the word does not.
- **Markers own the block.** Each marker must sit alone on its line, once. A
  missing, repeated or reversed marker is a setup error, never read as "no
  waivers".

`create-mr` reads the waivers from the description file it is given and, when
the branch renamed something, sends the MR with the rendered block, so the
reviewer sees every rename, waiver and reason. It renders into a copy: your
description file is not rewritten. A branch that renamed nothing, with no
block in its description, goes out exactly as written.

### Ignoring permanent noise

A waiver is per MR. Noise every MR would waive again, such as a changelog or
migration history, belongs in a committed `.mr-preflight.toml` at the
repository root:

```toml
ignore_paths = ["CHANGELOG.md", "docs/adr/**"]
ignore_tokens = ["schema_version"]
```

- **`ignore_paths`** are globs over repo-relative paths, matched the way git
  matches path globs: `*`, `?` and `[...]` (negated by `!` or `^`) stay
  inside one directory, so `*.md` is the root's Markdown only, and a whole
  `**` spans any depth (`docs/adr/**`, `**/CHANGELOG.md`). The whole path
  must match, so `docs/adr` or `docs/adr/` ignores nothing, and case counts.
  `\` escapes, `[[:digit:]]`-style classes and an unclosed `[` are refused
  as a setup error, since they would not match what git matches.
  Hits in these paths are dropped before waivers are read.
- **`ignore_tokens`** are exact names that are never chased. A branch whose
  only renames are ignored tokens counts as renaming nothing.
- **Committed only.** The file is read from the swept head's tree, like
  everything the sweep searches, so an ignore that exists only on your disk
  or in the index does nothing. Commit it first. Only the root's file is
  read, and only it is left out of the sweep: its lines are not uses of the
  names they list, so adding, editing or moving it never hides a rename, and
  it never blocks on one. A `.mr-preflight.toml` in a subdirectory is
  ordinary content.
- **Creep stays visible.** Every run that the file changed prints, clean or
  not:

  ```text
  mr-preflight: .mr-preflight.toml suppressed 3 hit(s) in ignored paths and skipped 1 renamed token(s).
  ```

- **Missing means no ignores; anything unusable is a setup error** (exit
  `2`, naming the file): invalid TOML, a key other than these two, a value
  that is not a list of strings, a directory or symlink in its place, or a
  Python older than 3.11 (reading it needs `tomllib`; a repo without the file
  sweeps on any Python 3).

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
setup error such as an unresolvable base or a malformed `.mr-preflight.toml`.
A crash inside the sweep also exits `2`, so it is never read as references to fix.

With the MR description, waived hits print as `waived:` and only the rest
block. `--update` rewrites the description's sweep block in place, appending
one if there is none: the renames, each unwaived hit as a `- [ ]` to-do, and
every waiver line, malformed ones included, carried forward as written. When
the branch renamed nothing and there is no block, the file is left alone.
Everything outside the block is left byte for byte. Anything else inside the
block is the tool's and is replaced. The file is replaced in one step, so a
failed write leaves the original intact.

```bash
python3 "<skill base directory>/scripts/mr_preflight.py" sweep --base origin/dev --description description.md --update
```

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
