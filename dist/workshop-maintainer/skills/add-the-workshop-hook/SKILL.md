---
name: add-the-workshop-hook
description: >
  Design and ship a new core hook in this repo (the-workshop) — fetch the
  exact event schema, write a stdlib-only fail-open script, TDD it against
  real subprocess+git behavior, wire it into every affected preset, and push
  to both GitHub and GitLab. Use when adding a new Claude Code hook (Stop,
  SubagentStop, ConfigChange, SessionStart, etc.) under core/hooks/.
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

Shared logic goes in an underscore-prefixed sibling under `core/hooks/` (e.g.
`_git_baseline.py`): `run-hook.sh` runs `python3 hooks/scripts/<name>`, so a
plain `import` resolves, `build_preset` ships `_*.py` unconditionally, and both
hook discovery and the fail-open scan skip the prefix. Guard it with
`except ImportError: sys.exit(0)` so a partial install no-ops rather than
crashing the tool path. (#328 replaced the older "fully self-contained, no
cross-hook imports" rule after three helpers had been copied into four hooks.)

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

## 6. Wire it everywhere it should apply, not just where you're testing

Add the hook entry to `core/settings-base.json` under the right event key,
then register the script filename in **every** affected preset's
`manifest.json` under `core.hooks` (skip persona-only presets unless the
hook is persona-relevant — they opt out of `base_settings` entirely).
Regenerate the living docs and rebuild every touched preset before committing:
run `make docs` (rewrites `docs/reference/` and the README's generated hook
tables from the new hook's docstring + wiring) and `make build` (rebuilds every
preset into `dist/` and regenerates the marketplace). `dist/` and the reference
docs are tracked, not gitignored, in this repo — commit the regenerated output
alongside the hook or the drift gate (step 7) fails.

## 7. Run the full gate, not just the new test file

Run `make test` — it runs the root suite, every auto-discovered skill-script
suite, AND the docs/dist drift gate (`build_docs --check` plus a `dist/`
rebuild that fails on any uncommitted diff). If the gate reports stale output,
you skipped `make docs`/`make build` in step 6 — regenerate and commit.

Then commit with a message stating the _why_ (the constraint from step 1, the
tradeoff from steps 3/4) and follow CLAUDE.md's branch policy: **branch off
`dev`, PR into `dev`.** Never push to `main`; never push or merge this repo on
GitLab — `origin` is GitHub, GitLab is a one-way mirror fed by merges into
`dev`. Confirm with `git remote -v` rather than assuming.

If the hook ships in a preset someone already has installed, **bump that
preset's version** — otherwise `claude plugin update` offers nothing and the
hook never reaches them.

Open design questions (shared-helper extraction, cross-tool test coverage
gaps) are tracked in `references/reference.md`.
