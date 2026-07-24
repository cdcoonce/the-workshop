# Platform Compatibility

This document lists the features each supported agent platform depends on.
Update when a breaking change is discovered. See [ROADMAP.md](ROADMAP.md) for
the overall multi-platform goal and design principle.

## Claude Code

### Plugin System

- `.claude-plugin/plugin.json` plugin manifest
- Plugin-level `skills/`, `agents/`, `hooks/` directories
- `$CLAUDE_PLUGIN_ROOT` environment variable in hook commands

### Hooks

- `hooks/hooks.json` for plugin hook configuration — a supported location;
  plugin hooks merge with user and project hooks when the plugin is enabled
- `${CLAUDE_PLUGIN_ROOT}` placeholder in hook commands
- `type: "command"` hooks — the only type this repo uses, and the only one
  available on every event it wires (see SessionStart below)
- Hook scripts receive the event payload as JSON on stdin
- `Edit|Write` matcher syntax

Every event this repo ships a hook for, with the mechanism it depends on:

| Event              | Hook                                          | Depends on                         |
| ------------------ | --------------------------------------------- | ---------------------------------- |
| `PreToolUse`       | `protect-files.py`                            | exit code 2 to deny                |
| `PostToolUse`      | `post-edit-lint.py`                           | side effect only                   |
| `UserPromptSubmit` | `suggest-handoff-on-context.py`               | `additionalContext`                |
| `Stop`             | `verify-tests-before-stop.py`                 | exit code 2 to block               |
| `SubagentStart`    | `snapshot-subagent-start.py`                  | side effect only; **cannot block** |
| `SubagentStop`     | `verify-subagent-evidence.py`                 | top-level `decision: "block"`      |
| `SessionStart`     | `inject-skill-router.py`, `inject_persona.py` | `additionalContext`                |
| `ConfigChange`     | `audit-config-change.py`                      | `systemMessage`; side effect only  |

Constraints that shape the hooks above, and would break them if they changed:

- **`SessionStart` supports only `command` and `mcp_tool`** — not `prompt` or
  `agent` — and cannot block. It also **re-runs on `--resume`/`--continue`** and
  on `--fork-session`, so a SessionStart hook must be idempotent and fast.
- **`SubagentStart` cannot block**, which is why the snapshot hook is
  side-effect-only and always exits 0.
- **`ConfigChange` cannot block `policy_settings`** (admin-controlled), and
  provides no content diff — the audit hook records that a change happened, not
  what changed.
- **`PostToolUse` cannot prevent execution**; it only reacts to completion.

### Skills

- `skills/*/SKILL.md` auto-discovery within plugin
- Skill `name` and `description` frontmatter for triggering
- `references/` subdirectory loading

### Agent Features

- `Agent` tool with `subagent_type` parameter
- `TodoWrite` tool for task tracking
- `EnterPlanMode` / `ExitPlanMode` tools

### Settings

- `settings.json` at plugin root (non-hook settings)
- Hook arrays in hooks.json with `matcher` and `hooks` fields

**Last Verified:** 2026-07-23 — hook events, mechanisms, and constraints checked
against the published hooks reference. The previous entry (2026-03-21) predated
six of the eight events this repo now ships, so it documented `PreToolUse` and
`PostToolUse` alone.

Not re-verified in this pass, and still carried from the original entry: skill
auto-discovery, `references/` loading, the agent-tool list, and plugin-root
`settings.json`. They are in daily use and evidently work; they have not been
checked against a current spec.

## Codex

### Plugin System

- `.codex-plugin/plugin.json` plugin manifest, extended shape:
  `author`, `repository`, `skills` path, and an `interface` block
  (`displayName`, `shortDescription`, `longDescription`, `developerName`,
  `category`, `capabilities`)
- Marketplace listing via `.agents/plugins/marketplace.json`
  (`scripts/build_marketplace.py`)

### Hooks

- Tool-ID matcher names differ from Claude Code's (`edit`, `write`,
  `multi_edit` vs. `Edit`, `Write`, `MultiEdit`) — current hook matchers cover
  both naming conventions in one pattern
- Payload shape and ordering semantics beyond matcher syntax: **not yet
  verified** (see ROADMAP.md open questions)

### Skills

- Not yet verified whether auto-discovery matches Claude Code's convention

**Last Verified:** 2026-07-02 — manifest shape and hook matcher names only
(commit `bde36ea`)

## Cortex Code (CoCo)

### Plugin System

- `.cortex-plugin/plugin.json` — **currently identical in shape to the Codex
  manifest** (same `interface` block, same fields). Verified as of the CoCo
  manifest commit; re-check when CoCo's own plugin spec is confirmed
  independently rather than assumed to track Codex.

### Hooks

- Shares the same widened tool-ID matcher pattern as Codex
  (`edit|write|multi_edit|Edit|Write|MultiEdit`)
- Payload shape and ordering semantics: **not yet verified**

### Skills

- Not yet verified whether auto-discovery matches Claude Code's convention

**Last Verified:** 2026-07-02 — manifest shape and hook matcher names only
(commit `4010d37`)
