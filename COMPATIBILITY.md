# Platform Compatibility

This document lists the features each supported agent platform depends on.
Update when a breaking change is discovered. See [ROADMAP.md](ROADMAP.md) for
the overall multi-platform goal and design principle.

### Evidence standard

Any entry asserting a platform behavior — a mechanism works or doesn't, an
event fires or doesn't — must carry a one-line note on how that was verified
(e.g. "confirmed via log inspection across N sessions" or "confirmed via
controlled probe at path X vs path Y"), not just the conclusion. **Presence of
a bundled example or a doc mention is not sufficient evidence on its own** —
see [How that was established](#how-that-was-established) under Cortex Code
below: the bundled `workbench` example shipping `hooks/hooks.json` implied
plugin-level hooks worked on Cortex, and that inference was wrong until a
log-history scan and a controlled plugin-level-vs-user-level probe proved
otherwise. This applies prospectively to new and edited entries; existing
unverified claims may still be marked the way the Claude Code section does
(see "Not re-verified in this pass" below) rather than rewritten.

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

| Event              | Hook                                          | Depends on                                                                        |
| ------------------ | --------------------------------------------- | --------------------------------------------------------------------------------- |
| `PreToolUse`       | `protect-files.py`                            | exit code 2 to deny                                                               |
| `PostToolUse`      | `post-edit-lint.py`                           | side effect only                                                                  |
| `UserPromptSubmit` | `suggest-handoff-on-context.py`               | `additionalContext`                                                               |
| `Stop`             | `verify-tests-before-stop.py`                 | exit code 2 to block                                                              |
| `SubagentStart`    | `snapshot-subagent-start.py`                  | side effect only; **cannot block**                                                |
| `SubagentStop`     | `verify-subagent-evidence.py`                 | top-level `decision: "block"`                                                     |
| `SessionStart`     | `inject-skill-router.py`, `inject_persona.py` | `additionalContext`                                                               |
| `ConfigChange`     | `audit-config-change.py`                      | `systemMessage`; side effect only                                                 |
| `SessionEnd`       | `warn-off-trunk.py`                           | side effect only (stderr); **`SessionEnd` does not exist on Codex** — inert there |

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
- `enabledPlugins` keys: the marketplace has since been re-registered under the
  new name — `known_marketplaces.json` on the reference machine carries
  marketplace `the-workshop` (observed 2026-07-26), and installed plugins now
  key as `<plugin>@the-workshop`. Legacy `<plugin>@claude-workflow` keys left
  checked into repos are **orphaned no-ops**: they match nothing, so a
  `@claude-workflow` disable no longer disables anything. Update such keys to
  `@the-workshop`.

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
- **`.codex-plugin/plugin.json` is confirmed as the manifest Codex reads.**
  Two independent lines of evidence (codex-cli 0.144.6): the CLI's embedded
  plugin validator errors name it explicitly (`missing
`.codex-plugin/plugin.json``), and an installed Workshop preset
  (`vault-ops`) loads and namespaces its skills from the `skills` path that
  manifest declares.
- Marketplace listing via `.agents/plugins/marketplace.json`
  (`scripts/build_marketplace.py`) — this is also the path the CLI itself
  defaults to (`<marketplace root>/.agents/plugins/marketplace.json`).
- Install machinery: `codex plugin marketplace add` (local path or Git),
  snapshots stored under `~/.codex/.tmp/marketplaces/<name>/`, registered as
  `[marketplaces.<name>]` in `~/.codex/config.toml`, with installed plugins
  as `[plugins."<plugin>@<marketplace>"]` entries. `codex plugin
add|list|remove` manage them.

### Hooks

Verified experimentally 2026-07-25 on codex-cli 0.144.6 (`codex exec`, a
scratch repo with an instrumented capture hook; extended the same day with a
flat-vs-nested in-session control and a trust-layer isolation):

- **Discovery: repo-level flat `.codex/hooks.json` in Claude-style schema is
  read and executed.** `SessionStart`, `PostToolUse`, and `Stop` all fired.
  **`.codex/hooks/hooks.json` (nested) is not read — proven by control:**
  both files present in the same trusted session, each wiring a SessionStart
  marker; the flat file's marker appeared, the nested one's never did.
- **Trust is two layers, and both gate silently.**
  1. **Project trust:** the workspace must have `trust_level = "trusted"`
     under `[projects."<abs path>"]` in `~/.codex/config.toml`. Without it,
     repo-level hooks are skipped even with the bypass flag below — and a
     `-c 'projects."<path>".trust_level="trusted"'` CLI override is **not
     honored** for this. An identical probe fired in a file-trusted directory
     and stayed silent in an untrusted one.
  2. **Per-hook trust:** Codex persists per-hook approval as a
     `trusted_hash` under `[hooks.state]`, keyed
     `<source>:hooks/hooks.json:<event>:<i>:<j>` (event names snake_case).
     `codex exec --dangerously-bypass-hook-trust` bypasses this layer only.
     With either layer missing, hooks produce no output, no error, nothing —
     this, not matcher casing, is why repo hooks appear dead.
- **Trust keys are absolute-path-keyed, so renaming a repo directory orphans
  its hook trust.** Observed live: `[hooks.state]` still carries entries for
  `.../GitHub/my-brain/.codex/hooks.json` while that repo now lives at
  `the-vault` — its vendored hooks are silently untrusted again until
  re-approved.
- **Plugin-level hooks cannot fire: the `plugin_hooks` feature is `removed`**
  (`codex features list`). A preset's `hooks/hooks.json` is inert on Codex —
  the same practical conclusion as Cortex, reached by a different mechanism
  (legacy `[hooks.state]` entries for plugin sources remain from when the
  feature existed, and no longer correspond to anything that runs). Hook
  delivery to a Codex repo is the vendored repo-level flat `.codex/hooks.json`
  the vault-ops machinery generates.
- **Event inventory (binary-string evidence, not live-fired):** the CLI
  embeds `SessionStart`, `UserPromptSubmit`, `PreToolUse`, `PostToolUse`,
  `Stop`, `SubagentStart`, `SubagentStop`, `PreCompact`, and
  `PermissionRequest`. **`ConfigChange` and `SessionEnd` do not exist** —
  so unlike Cortex, Codex has `SubagentStart`, but the config-audit hook has
  no event on either platform. Live-fired confirmation still covers only
  `SessionStart`, `PostToolUse`, and `Stop`.
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
  trust gates. A SessionStart entry fires with or without a `matcher`.

### Skills

Verified live 2026-07-25 (marker skills at four candidate roots in one scratch
repo, listed by a headless `codex exec` session):

- **Repo-level auto-discovery works from `.codex/skills/` and
  `.agents/skills/`.** Both markers were listed. **`.claude/skills/` and bare
  `skills/` are not discovered.**
- Skill discovery is **not** gated on project trust — the probe repo was
  untrusted and its skills still listed (hooks in the same repo stayed
  silent).
- **Plugin skills load and trigger, namespaced `<plugin>:<skill>`** (e.g.
  `vault-ops:vault-standup`), including under headless `codex exec` — the
  opposite of Claude Code, where plugin skills don't load under `-p` at all.
- A user-level root exists at `~/.codex/skills/` (directory observed; loading
  not individually exercised).
- `SKILL.md` frontmatter is validated — unexpected keys are rejected with an
  allowed-properties list; `name` + `description` work.

### Agents

Probed 2026-08-01 on codex-cli 0.144.6. **Evidence is manifest-schema,
first-party-corpus, and binary strings — not live-fired.**

- **Plugin `agents/` is not a Codex component.** The plugin manifest schema
  the CLI carries knows `skills`, `hooks`, and `mcpServers`; there is **no
  `agents` key**. Agent files placed in a plugin ship inside the tarball and
  are inert — unreferenced by the manifest and undiscoverable.
- **No first-party Codex plugin ships an `agents/` dir.** All 12 installed
  across `openai-primary-runtime` and `openai-bundled` ship `skills/` only.
- **`agents/openai.yaml` in the binary is a false friend** — it is *skill*
  metadata (`Create agents/openai.yaml for a skill directory`), unrelated to
  subagents. Do not read it as agent support.
- **`codex features list` reports `multi_agent  stable  true`.** That is
  Codex's own internal orchestration, not plugin-supplied agents, and must not
  be read as plugin agent support. (The same command reports `plugin_hooks
  removed`, reproducing the 2026-07-25 hooks finding — the instrument agrees
  with prior work.)

Not yet live-fired: installing a preset carrying `agents/` and confirming
nothing is exposed. Low value, since the manifest has no key to populate.

### Settings

- The `settings.json` concept maps to **`~/.codex/config.toml`** (global):
  `[projects]` trust, `[features]`, `[hooks.state]`, `[marketplaces]`,
  `[plugins]`, `[mcp_servers]`, plus per-invocation dotted-path overrides via
  `-c key=value` on any subcommand.
- No consumer of a plugin-root `settings.json` was observed on Codex.

**Last Verified:** 2026-07-25 — hooks, trust layers, skills, plugin install
surface, and settings verified live as described above; event inventory from
binary strings. Matcher names carried from 2026-07-02 (commit `bde36ea`).
Agents added 2026-08-01 (codex-cli 0.144.6, manifest-schema evidence).

## Cortex Code (CoCo)

### Plugin System

- **Cortex reads `.claude-plugin/plugin.json`, not `.cortex-plugin/`.** Its own
  bundled plugins (`bundled_plugins/airflow`, `bundled_plugins/review`) ship a
  `.claude-plugin/` directory; no `.cortex-plugin` exists anywhere in the
  install. The `.cortex-plugin/plugin.json` this repo emits appears to be read by
  nothing — any preset that works on Cortex does so through the Claude manifest.
- **Version note (2026-07-25, doc-level evidence only):** Cortex Code desktop
  v1.18.0 bundles a first-party plugin spec (`plugin-creator/reference.md` in
  the app bundle) that names `.cortex-plugin/plugin.json` the primary
  CoCo-convention manifest, with `.claude-plugin/plugin.json` "also
  recognized", and documents hooks declared **inline in the manifest** as read.
  Per the evidence standard above this is a bundled spec, not a controlled
  probe — it reopens, but does not overturn, the read-by-nothing conclusion
  probed on v1.1.8. The hook conclusion below (no plugin `hooks/hooks.json`
  has ever executed) is unaffected either way.
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

### Agents

Probed 2026-08-01 against Cortex Code **v1.18.0**'s bundled first-party plugin
spec (`Contents/Resources/app/resources/snowflake/skills/plugin-creator/reference.md`).
**Documentation evidence — not live-fired.**

- **Cortex supports plugin agents.** The spec lists `agents/` as a first-class
  optional component and documents the format as
  **`agents/<name>.md`** — "Agents are Markdown files in the `agents/`
  directory. The filename (without `.md`) becomes the agent name."
- **This repo's layout does not match, so nothing is discovered.** We ship
  `agents/<name>/AGENT.md` **directories**; Cortex looks for a flat
  `agents/<name>.md`. Component placement is otherwise correct — the spec
  forbids putting `skills/`, `agents/` or `hooks/` inside `.cortex-plugin/`,
  and ours sit at plugin root.
- **Agent frontmatter differs.** Cortex documents exactly `name`,
  `description`, `tools`, `resources`. Ours add `role` and
  `skills: {add, remove}`, which have no counterpart — a rename alone would
  not carry this repo's skill-attachment semantics.
- **Tool-ID trap, currently dodged.** The spec warns that agent `tools` must
  use CoCo's lowercase/snake_case tool IDs, and that PascalCase Claude Code
  names like `Read`/`Write`/`Edit` "will silently match no tool and **disable
  the restriction**". This repo's agents declare no `tools` key, so there is
  no silent-disable exposure — do not add one without snake_case IDs.

Not yet live-fired: renaming one agent to `agents/<name>.md`, installing, and
confirming it lists and dispatches. That would settle whether the rename alone
suffices or the frontmatter must change too.

**Last Verified:** 2026-07-23 — Cortex Code v1.1.8, against its bundled
first-party reference (`bundled_skills/cortex-code-guide/HOOKS.md`, `SKILLS.md`)
and its own bundled plugins, plus live runs on an install that already had
`workbench` and `vault-ops` active: `cortex skill list`, headless `cortex -p`
probes, and the user-level vs plugin-level hook comparison above.

Skill discovery and hook non-execution are both confirmed by observation. The
manifest claim (`.cortex-plugin/plugin.json` is read by nothing) rests on
Cortex's own bundled plugins using `.claude-plugin/` and no `.cortex-plugin`
existing in the install — strong, but not a direct experiment.

**⚠️ The v1.1.8 findings above are superseded in part by v1.18.0 (installed
2026-08-01).** Its bundled plugin spec names `.cortex-plugin/plugin.json` the
primary CoCo-convention manifest with `.claude-plugin/` "also recognized" — the
opposite of the "read by nothing" claim — and documents **both** a plugin-root
`hooks/hooks.json` component directory **and** hooks read inline from the
manifest when `hooks` is an object. Whether either actually executes on 1.18.0
is unresolved and is the open question in #487; the v1.1.8 observation that
plugin hooks never fire has not been re-run against 1.18.0. Treat the hook and
manifest rows for Cortex as stale pending that probe.

Cortex's documented event set (v1.18.0): `PreToolUse`, `PostToolUse`,
`PermissionRequest`, `Notification`, `SessionStart`, `SessionEnd`,
`UserPromptSubmit`, `Stop`, `SubagentStop`, `PreCompact`, `Setup`.
`SubagentStart` and `ConfigChange` are absent — but **`SessionEnd` is
present**, so `warn-off-trunk.py` is not inert on Cortex the way it is on
Codex. Matchers must use snake_case tool IDs.
