---
name: add-claude-workflow-hook
description: >
  Design and ship a new core hook in this repo (claude-workflow) — fetch the
  exact event schema, write a stdlib-only fail-open script, TDD it against
  real subprocess+git behavior, wire it into every affected preset, and push
  to both GitHub and GitLab. Use when adding a new Claude Code hook (Stop,
  SubagentStop, ConfigChange, SessionStart, etc.) under core/hooks/.
---

# Add Claude Workflow Hook

Maintainer skill for this repo. Follow these 7 steps in order — they were
derived from building `verify-tests-before-stop` (Stop), the
`snapshot-subagent-start`/`verify-subagent-evidence` pair
(SubagentStart/SubagentStop), and `audit-config-change` (ConfigChange), which
all followed this same recipe.

## 1. Fetch the exact event schema before designing anything

Don't assume the input/output shape from memory or the general hooks guide —
`WebFetch` `code.claude.com/docs/en/hooks` for the specific event (input
fields, matcher values, decision/output format, caveats about what's *not*
available, e.g. `ConfigChange` gives no content diff, `SessionStart` cannot
block). Design decisions should trace back to a real constraint the schema
revealed, not an assumption.

## 2. Design for fail-open and cross-tool portability up front

Every hook in this repo is stdlib-only Python (no cross-hook imports — each
script is fully self-contained, matching `protect-files.py`/
`post-edit-lint.py`/`inject_persona.py` convention) and must degrade safely:
malformed stdin, missing fields, no git repo, missing binaries — all exit 0
rather than blocking on ambiguity. Portability across Claude Code, Cortex
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
`<git-dir>/claude-workflow-<name>-gate/`) with the stop-of-lifecycle
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
Rebuild every touched preset (`uv run python -m scripts.build_preset
<preset>`) and the marketplace (`uv run python -m scripts.build_marketplace`)
before committing — `dist/` output is tracked, not gitignored, in this repo.

## 7. Run the full gate, not just the new test file

`uv run --with pytest python -m pytest -q tests` AND the nested
`core/skills/daa-code-review/scripts` sub-suite (`cd` into it, `uv run --with
pytest --with ruff python -m pytest -q tests`) — both are part of this
repo's real `make test` target. Then commit with a message that states the
*why* (the constraint from step 1, the design tradeoff from steps 3/4), and
push to **both** `origin main` and `gitlab main:dev` — this repo mirrors to
GitLab and the two can silently diverge if only one gets pushed.

## Open questions

- Worth extracting the duplicated `git_dir()`/`working_tree_signature()`/
  `head_sha()` helpers (identical across `verify-tests-before-stop.py`,
  `snapshot-subagent-start.py`, `verify-subagent-evidence.py`) into a shared
  module once a 4th hook needs them? Currently duplicated on purpose to keep
  each hook file self-contained per the repo's existing convention (step 2)
  — revisit if that convention itself changes.
- No CoCo/Codex test harness exists in this repo yet — portability is
  currently an inference from a prior bug fix (`aaf2229`), not something
  re-verified per new hook.
