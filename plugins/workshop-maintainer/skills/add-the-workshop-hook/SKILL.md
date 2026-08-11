---
name: add-the-workshop-hook
description: >
  Design and ship a new hook in this repo (the-workshop) — fetch the exact
  event schema, write a stdlib-only fail-open script, TDD it against real
  subprocess+git behavior, declare its wiring so the stamper picks it up, and
  push to both GitHub and GitLab. Use when adding a new Claude Code hook (Stop,
  SubagentStop, ConfigChange, SessionStart, etc.) under
  plugins/workbench/hooks/scripts/.
---

# Add The Workshop Hook

Maintainer skill for this repo. Follow these 7 steps in order — they were
derived from building `verify-tests-before-stop` (Stop), the
`snapshot-subagent-start`/`verify-subagent-evidence` pair
(SubagentStart/SubagentStop), and `audit-config-change` (ConfigChange), which
all followed this same recipe.

## 1. Fetch the exact event schema before designing anything

Don't assume the input/output shape from memory or the general hooks guide —
`WebFetch` `code.claude.com/docs/en/hooks` for the specific event (input
fields, matcher values, decision/output format, caveats about what's _not_
available, e.g. `ConfigChange` gives no content diff, `SessionStart` cannot
block). Design decisions should trace back to a real constraint the schema
revealed, not an assumption.

## 2. Design for fail-open and cross-tool portability up front

Every hook in this repo is stdlib-only Python and must degrade safely:
malformed stdin, missing fields, no git repo, missing binaries — all exit 0
rather than blocking on ambiguity.

Every hook lives in exactly one place: `plugins/workbench/hooks/scripts/`.
Shared logic goes in a sibling module there (e.g. `_git_baseline.py`):
`run-hook.sh` runs `python3 hooks/scripts/<name>`, so a plain `import`
resolves. Guard it with `except ImportError: sys.exit(0)` so a partial install
no-ops rather than crashing the tool path. (#328 replaced the older "fully
self-contained, no cross-hook imports" rule after three helpers had been copied
into four hooks.)

What keeps a helper out of the wiring is the **absence of a `WORKSHOP_HOOK`
declaration**, not its leading underscore — a module that declares nothing is a
library. See step 6.

Portability across Claude Code, Cortex
Code (CoCo), and Codex means: reuse the existing `run-hook.sh` shim
(`$CLAUDE_PLUGIN_ROOT` fallback via `BASH_SOURCE` resolution), and avoid
Claude-Code-only features (`type: "agent"` hooks, fields like
`stop_hook_active`/`session_id` that other tools may never send — treat their
absence as a safe default, never a crash).

## 3. Think about whether "unchanged since last check" needs a content-aware signature

`git status --porcelain` alone only reports path-status flags, not content —
a file already flagged modified stays flagged identically even if its content
changes again. If a hook caches "nothing changed" to skip expensive work,
hash actual file bytes for every listed path, not just the status line.

## 4. Think about whether a point-in-time check is even sufficient

A clean working tree at hook-fire time doesn't prove nothing happened — e.g.
a subagent can legitimately commit its own work between start and stop,
leaving the tree clean. If the check needs a "did X happen since Y" answer,
pair a start-of-lifecycle snapshot hook (state file under
`<git-dir>/the-workshop-<name>-gate/`) with the stop-of-lifecycle
comparison hook, rather than trying to infer history from one snapshot.

## 5. TDD against real subprocess + real git, not mocks

Every existing hook test (`tests/test_*_hook*.py`) drives the hook as an
actual subprocess via
`subprocess.run([sys.executable, str(hook_path)], input=json.dumps(payload), ...)`
against a scratch `tmp_path` git repo (`git init` + `git config
user.email/user.name`), not a mocked git module. Cover: malformed stdin
fails open, the no-op path, the blocking/warning path, and the "should NOT
trigger" path for every plausible false-positive.

## 6. Declare the wiring in the hook itself, then stamp

Wiring is filesystem-driven: **dropping the script into
`plugins/workbench/hooks/scripts/` and declaring its event _is_ the
registration.** There is no per-plugin hook list to update, no base settings
file to edit, and no composition step to rerun — all three died with the flat
reorg (#656).

Give the module a top-level literal:

```python
WORKSHOP_HOOK = {"event": "Stop"}
```

`event` is required; `matcher` and `runner` are optional. `scripts/stamp.py`
reads it **statically with `ast`** and never imports the module — these scripts
read stdin and exit at import time, so importing them would hang the stamper. A
module with no `WORKSHOP_HOOK` is a shared library and stays out of the wiring
(that, not the leading underscore, is what excludes `_git_baseline.py`).
The declaration must be a literal dict; a computed value fails loudly by name.

Then run `make stamp`. It rewrites every generated path from hand-written truth
— `hooks/hooks.json`, the marketplace index, and `docs/reference/` — from your
declaration plus the hook's docstring. Generated files are tracked, not
gitignored: commit them alongside the hook or step 7 fails.

## 7. Run the full gate, not just the new test file

Run `make test` — lint, the root suite, every auto-discovered skill-script
suite, the machinery suite, and `stamp --check`, which re-renders the path map
in memory and fails **naming the file and printing a diff** on anything
committed stale. If it reports stale output, you skipped `make stamp` in step 6.

Pass the base you are actually merging into: `make test VERSION_BASE=origin/dev`
for a PR into `dev`. The Makefile defaults to `origin/main`, so a bare `make
test` can pass locally on a version bump that CI correctly rejects, because
`dev` has already moved ahead of `main`.

Then commit with a message stating the _why_ (the constraint from step 1, the
tradeoff from steps 3/4) and follow CLAUDE.md's branch policy: **branch off
`dev`, PR into `dev`.** Never push to `main` directly. `origin` is GitHub and
is this repo's own integration point; GitLab is a separate downstream copy —
sync it afterward with `sync-gitlab-dev`, not as part of landing this hook.
Confirm remotes with `git remote -v` rather than assuming.

Hooks ship in workbench, which people already have installed, so **bump
`plugins/workbench/.claude-plugin/plugin.json`** — otherwise `claude plugin
update` offers nothing and the hook never reaches them.

Open design questions (shared-helper extraction, cross-tool test coverage
gaps) are tracked in `references/reference.md`.
