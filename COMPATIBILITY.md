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
- `enabledPlugins` keys observed in the wild as `<plugin>@claude-workflow` —
  the marketplace identity survived the repo's rebrand to the-workshop, so any
  per-project disable must use the `@claude-workflow` suffix until the
  marketplace is re-added under the new name

### Headless (`claude -p`)

Verified experimentally 2026-07-25 (scrubbed env + `CLAUDE_CODE_OAUTH_TOKEN`,
the same invocation shape the vault's batch runs use):

- Project-scope `.claude/skills/*/SKILL.md` **resolves** as a slash command
  under `-p`.
- Project-scope `.claude/commands/*.md` **resolves** under `-p`.
- **Plugin skills do not load under `-p` at all.** Probed with a plugin-only
  skill both outside and _inside_ a project where that plugin's skills are
  active interactively; both return `Unknown command`. Consequence: any skill
  a headless workflow invokes must exist project-scope in the target repo —
  an installed plugin is not a carrier for headless automation.

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

Verified experimentally 2026-07-25 on codex-cli 0.144.6 (`codex exec`, a
scratch repo with an instrumented capture hook):

- **Discovery: repo-level flat `.codex/hooks.json` in Claude-style schema is
  read and executed.** `SessionStart`, `PostToolUse`, and `Stop` all fired.
  (`.codex/hooks/hooks.json` was not observed to fire when the flat file was
  absent from the run that tested it; the flat path is the proven one.)
- **Trust gate: hooks are silently skipped unless trusted.** Codex persists
  per-hook approval as a `trusted_hash` under `[hooks.state]` in
  `~/.codex/config.toml`, keyed `<source>:hooks/hooks.json:<event>:<i>:<j>`.
  With no persisted trust and no bypass, a repo's hooks produce no output, no
  error, nothing — this, not matcher casing, is why repo hooks appear dead.
  `codex exec --dangerously-bypass-hook-trust` runs them for automation that
  has already vetted the hook source.
- **Payload: none.** Hook processes receive no JSON on stdin, no
  payload-bearing environment variables, and only the argv the command line
  itself supplies. Hooks that parse a stdin payload (tool name, file path)
  fire but learn nothing — on Codex a hook must derive its facts itself
  (e.g. from `git status`). Exit-code blocking semantics are untestable
  without a payload-driven decision and remain unverified.
- **cwd = the workspace root**, so relative hook commands and the
  `"${CLAUDE_PROJECT_DIR:-.}"` fallback pattern both resolve correctly.
- Tool-ID matcher names differ from Claude Code's (`edit`, `write`,
  `multi_edit` vs. `Edit`, `Write`, `MultiEdit`) — the dual-convention
  matcher `write|edit|multiedit|multi_edit|Write|Edit|MultiEdit` **fired on a
  file-creating tool use**; a broader matcher that also names `shell` fired
  one additional time. With no payload there is no way to log which ID
  matched, so keep matchers dual-convention.
- Headless `codex exec` runs hooks the same as above, subject to the same
  trust gate.

### Skills

- Not yet verified whether auto-discovery matches Claude Code's convention

**Last Verified:** 2026-07-25 — hooks verified live as described above.
Manifest shape and matcher names carried from 2026-07-02 (commit `bde36ea`);
skill auto-discovery still unverified.

## Cortex Code (CoCo)

### Plugin System

- **Cortex reads `.claude-plugin/plugin.json`, not `.cortex-plugin/`.** Its own
  bundled plugins (`bundled_plugins/airflow`, `bundled_plugins/review`) ship a
  `.claude-plugin/` directory; no `.cortex-plugin` exists anywhere in the
  install. The `.cortex-plugin/plugin.json` this repo emits appears to be read by
  nothing — any preset that works on Cortex does so through the Claude manifest.
- Plugins are supplied by the `--plugin-dir` flag (a directory, GitHub repo, or
  URL, repeatable). There is no `plugin install` subcommand; `cortex skill`
  manages skill directories separately.
- Cortex's bundled plugin declares its hooks **inline in `plugin.json`**, not in
  a plugin-level `hooks/hooks.json`.
- **Cortex does not read plugin-level `hooks/hooks.json`. No Workshop hook runs
  on Cortex.** Verified experimentally, not inferred — see below.

### Hooks

Supported events: `PreToolUse`, `PostToolUse`, `PermissionRequest`,
`UserPromptSubmit`, `Stop`, `SubagentStop`, `Notification`, `SessionStart`,
`SessionEnd`, `PreCompact`, `Setup`.

- **`SubagentStart` and `ConfigChange` do not exist on Cortex.**
- Hook types: `command` and `prompt` only — no `mcp_tool`, `http`, or `agent`.
  This repo uses `command` throughout, so that constraint is satisfied.
- Config location: `~/.snowflake/cortex/hooks.json`, or inline in a plugin
  manifest.
- Stdin payload carries the same common fields Claude Code sends (`session_id`,
  `transcript_path`, `cwd`, `hook_event_name`, plus `permission_mode`), with
  `tool_name`/`tool_input`/`tool_use_id` on tool events and `source` on
  `SessionStart`.
- Exit codes match: `0` continue, `2` block with stderr sent to the agent.
  JSON output uses the same `decision` / `hookSpecificOutput` /
  `permissionDecision` shape.

What that means for the hooks this repo ships:

| Hook                                                         | On Cortex                                                                                                                              |
| ------------------------------------------------------------ | -------------------------------------------------------------------------------------------------------------------------------------- |
| `protect-files.py` (PreToolUse, exit 2)                      | works                                                                                                                                  |
| `post-edit-lint.py` (PostToolUse)                            | works                                                                                                                                  |
| `suggest-handoff-on-context.py` (UserPromptSubmit)           | event exists; `additionalContext` support unconfirmed                                                                                  |
| `verify-tests-before-stop.py` (Stop, exit 2)                 | works                                                                                                                                  |
| `inject-skill-router.py`, `inject_persona.py` (SessionStart) | event exists; `additionalContext` support unconfirmed                                                                                  |
| `snapshot-subagent-start.py` (SubagentStart)                 | **never fires — no such event**                                                                                                        |
| `verify-subagent-evidence.py` (SubagentStop)                 | event exists, but **silently inert**: its baseline comes from the SubagentStart hook, so it finds no snapshot and fails open by design |
| `audit-config-change.py` (ConfigChange)                      | **never fires — no such event**                                                                                                        |

That table is now moot in practice: **none of these hooks run on Cortex at all**,
because Cortex never loads a plugin's `hooks/hooks.json`. The event-level gaps
still matter for the day plugin hooks are supported, or if hooks are moved
inline into `plugin.json`.

#### How that was established

Inference from the bundled example was not enough, so it was tested:

1. `workbench` is installed and active in Cortex, and its installed copy
   contains `hooks/hooks.json` wiring a `SessionStart` hook.
2. Across the entire Cortex log history — every session on that machine, with
   `workbench`, `vault-ops`, and `full-stack` active at various points — **no
   plugin-declared hook has ever executed.** The only `Executing … hooks` lines
   are `SessionEnd`.
3. The obvious confound was that the probe ran headless (`cortex -p`), which
   might skip `SessionStart` regardless of configuration. So an identical
   `SessionStart` hook was placed in the **user-level** `~/.snowflake/cortex/
hooks.json` and the same headless probe re-run. **It fired immediately.**

Same event, same mode, same machine: user-level fires, plugin-level does not.
The layout is the variable.

Consequence: every protection this repo ships as a hook — file protection,
test-before-stop, subagent evidence, config auditing — is **absent on Cortex**,
silently. Skills are unaffected and work fully.

### Skills

- Auto-discovery **works**, from `.cortex/skills/`, `.claude/skills/`, and
  `.snova/skills/`. `~/.claude/skills/` is treated as project-level "for
  compatibility" — confirmed live: `cortex skill list` on this machine
  discovers skills installed under `~/.claude/skills/`.
- Skills can also arrive via `--plugin-dir`, or be added/published through
  `cortex skill add|publish` (including from a Snowflake stage).

**Last Verified:** 2026-07-23 — Cortex Code v1.1.8, against its bundled
first-party reference (`bundled_skills/cortex-code-guide/HOOKS.md`, `SKILLS.md`)
and its own bundled plugins, plus live runs on an install that already had
`workbench` and `vault-ops` active: `cortex skill list`, headless `cortex -p`
probes, and the user-level vs plugin-level hook comparison above.

Skill discovery and hook non-execution are both confirmed by observation. The
manifest claim (`.cortex-plugin/plugin.json` is read by nothing) rests on
Cortex's own bundled plugins using `.claude-plugin/` and no `.cortex-plugin`
existing in the install — strong, but not a direct experiment.
