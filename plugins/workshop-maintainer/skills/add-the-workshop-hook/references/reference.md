# Add The Workshop Hook — Design Questions

Deferred design questions from building the core hooks. Resolved ones are kept
with their answer rather than deleted — the reasoning is why the current shape
is the current shape, and a question left looking open invites re-litigating a
decision already made.

## Shared helper extraction — RESOLVED (#328, 2026-07-23)

**Question:** worth extracting the duplicated `git_dir()` /
`working_tree_signature()` / `head_sha()` helpers into a shared module once a
4th hook needs them, or does the self-contained convention win?

**Answer: extracted.** A 4th consumer arrived (`audit-config-change.py`, for
`git_dir`) and the copies had already drifted — `working_tree_signature`
returned `""` in two hooks and `None` in a third. They now live in
`core/hooks/_git_baseline.py`, imported as a sibling: `run-hook.sh` runs
`python3 hooks/scripts/<name>`, so `sys.path[0]` is that directory.

Three things the extraction turned up, worth knowing before touching it:

- **Standardizing on `None` is not free.** `snapshot-subagent-start` writes the
  signature into a state file that `verify-subagent-evidence` reads back as a
  string and compares. `None` would serialize as `"None"`, never match, and
  silently disable the evidence check. Both hooks normalize with `or ""` at the
  serialization boundary; a test pins it.
- **An underscore-prefixed module under `core/hooks/` is not a hook.** Hook
  discovery in `build_docs` globs `*.py` and demands an event-naming docstring;
  the fail-open scan would assert a contract a library was never subject to and
  pass trivially. Both skip the prefix.
- **Guard the import** with `except ImportError: sys.exit(0)` — a stale or
  partial install must no-op, not crash the user's tool path.

## Cross-tool portability is unverified — STILL OPEN

No CoCo/Codex test harness exists in this repo. Portability is an inference from
a prior bug fix (`aaf2229`), not something re-verified per new hook, and every
hook shipped since — including `_git_baseline.py` and the fail-open contract —
has been validated against Claude Code only.

The specific unknowns are tracked in `ROADMAP.md`: hook stdin payload shape,
ordering and exit-code handling, skill auto-discovery, and whether a
`settings.json` equivalent exists. They need answers from outside this repo
before they become an implementation task.
