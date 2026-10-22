---
name: codex-enable
description: >
  Vendors a Codex-functional .codex/hooks.json into a target repo so a Codex
  teammate gets workbench's hook protections. Use when someone asks to enable
  workbench hooks on Codex or to set up .codex/hooks.json in a repo.
disable-model-invocation: true
---

# Codex Enable

Codex plugin installs ship skills but their hooks only help if the owner trusts them, and hooks that read a stdin payload learn nothing on Codex. This skill vendors the one repo-level setup that works: a flat `<repo>/.codex/hooks.json` plus the small runtime it calls (#486; facts in COMPATIBILITY.md → Codex → Hooks).

## Run it

```bash
python3 <plugin-root>/skills/codex-enable/scripts/codex_enable.py <repo> [--force]
```

It wraps `render_codex_hooks` from `machinery/tools/wiring_gen.py` over `scripts/codex-hooks-spec.json`, so the file is byte-identical to a wiring_gen render. Files written:

- `.codex/hooks.json`
- Under `.claude/scripts/` (where wiring_gen's command template points): the hook runner, `verify-tests-before-stop.py`, `_git_baseline.py`

## Behavior

- **Rerun-safe.** Identical files report `unchanged`.
- **Never a silent half-install.** If any target file exists and differs, it prints `REFUSED`, lists the files, and writes nothing. `--force` overwrites them. Read the diff before forcing; a hand-authored `hooks.json` may carry hooks you want to keep.
- **Trust steps.** Codex skips untrusted hooks silently. On success it prints the two steps only the owner can do: `trust_level = "trusted"` for the repo in `~/.codex/config.toml`, then per-hook approval on first run. Relay them; don't edit `~/.codex/config.toml` yourself.

## Which hooks are Codex-functional

Codex delivers hooks no stdin payload (COMPATIBILITY.md). The spec lists only hooks that derive every fact themselves. Hooks that "fire and learn nothing" are left out on purpose (#486):

| Hook | Vendored | Why |
|---|---|---|
| `verify-tests-before-stop.py` | yes | self-derives cwd and tree state; empty stdin is its documented payload-less path |
| `protect-files.py` | no | needs the tool payload's file path; inert payload-less |
| `verify-subagent-evidence.py` | no | needs the subagent payload; inert payload-less |
| `snapshot-subagent-start.py` | no | partial Codex event support |
| `audit-config-change.py` | no | `ConfigChange` does not exist on Codex |
| `warn-off-trunk.py` | no | `SessionEnd` does not exist on Codex |
| vault hooks (`vault-*.py`) | no | vault-engine hooks; the vault-ops preset vendors its own |

To add a hook that becomes payload-safe: confirm it self-derives its facts, add an entry to `scripts/codex-hooks-spec.json`, add its file (and any sibling module) to the vendored set in `codex_enable.py`, and update this table.
