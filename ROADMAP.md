# Roadmap: Multi-Agent Platform Support

This build system targets three coding-agent platforms as first-class outputs:
**Claude Code**, **Codex**, and **Cortex Code (CoCo)**. A preset built here should
install and run natively on any of the three without an install-time transform.

## Current Status

Shipped:

- Manifest truth is a single hand-written `.claude-plugin/plugin.json` per
  plugin (`plugins/<name>/.claude-plugin/plugin.json`). The former `core/` +
  `presets/` composition build, its `dist/` output, and `scripts/build_preset.py`
  are gone; `scripts/stamp.py` (`make stamp`, `make stamp-check`) regenerates
  every derived file from that same source. What each platform actually reads
  from it is documented in COMPATIBILITY.md.
- Cortex Code reuses the Codex manifest shape verbatim — **probe-verified
  2026-08-08 (v1.20.2, #634): correct after all.** Cortex reads both
  `.cortex-plugin/plugin.json` (its primary convention) and
  `.claude-plugin/plugin.json`, and executes plugin hooks (file-based and
  inline). Caveat: Cortex does not set `CLAUDE_PLUGIN_ROOT`, so this repo's
  hook commands fail to resolve there. See COMPATIBILITY.md.
- Hook matchers cover all three platforms' tool-ID naming conventions in one
  pattern (`edit|write|multi_edit|Edit|Write|MultiEdit`).
- Codex plugin marketplace support via `.agents/plugins/marketplace.json`
  (`scripts/build_marketplace.py`, which used to generate it, was deleted in
  the flat-plugin-reorg; regeneration is not yet re-verified).

Open questions (tracked here until resolved, not blocking):

- **Cortex hook semantics — ANSWERED 2026-07-23.** Payload shape, exit codes,
  and JSON output match Claude Code's. But Cortex has **no `SubagentStart` and
  no `ConfigChange`**, so two shipped hooks never fire and the subagent evidence
  gate is silently inert. Details in COMPATIBILITY.md.
- **Cortex skill auto-discovery — ANSWERED 2026-07-23.** Works, from
  `.cortex/skills/`, `.claude/skills/`, and `.snova/skills/`; `~/.claude/skills/`
  is treated as project-level for compatibility.
- **Does Cortex read a plugin-level `hooks/hooks.json`? — ANSWERED 2026-07-23:
  no; REVERSED 2026-08-08.** ~~Tested on a machine with `workbench` active: no
  plugin-declared hook has ever executed, while an identical `SessionStart`
  hook in the user-level `~/.snowflake/cortex/hooks.json` fired immediately
  under the same headless probe. **No Workshop hook runs on Cortex.**~~ A
  controlled probe on v1.20.2 (#634) overturned this: plugin hooks EXECUTE,
  and both `.cortex-plugin`-only and `.claude-plugin`-only manifests are
  read. See "Shipped" above and COMPATIBILITY.md for the full result and its
  caveats (`CLAUDE_PLUGIN_ROOT` unset, window-restore race). Skills work
  fully either way.
- ~~Given that: should the build emit Cortex hooks inline in `plugin.json`
  (the shape Cortex's own bundled plugins use), or should Cortex be
  documented as a skills-only target? A real decision, not a defect — the
  hooks degrade silently rather than erroring. **The same decision now
  applies to Codex** (see next item): as of 2026-07-25 presets are
  skills-only carriers on both non-Claude platforms; on Codex, hooks ship
  via the vendored repo-level `.codex/hooks.json` the vault-ops machinery
  already generates.~~ **Moot as of 2026-08-09: both premises were wrong.**
  Plugin hooks work on Cortex (above) and on Codex (below), so hooks ship
  plugin-level — `plugins/workbench/hooks/hooks.json` — with no vendored
  repo-level shim.
- **Codex hook semantics — ANSWERED 2026-07-25; plugin-hooks line CORRECTED
  2026-08-09.** Repo-level flat `.codex/hooks.json` only (nested path proven
  unread by control); a two-layer silent trust gate (project `trust_level`
  in `config.toml` + per-hook `trusted_hash`, bypass flag covers only the
  latter); no stdin/env payload. ~~plugin-level hooks impossible — the
  `plugin_hooks` feature is `removed`~~: wrong — the flag was retired
  because the capability graduated into the stable hooks engine
  (openai/codex#19705); the 2026-07-25 probe's own plugin was almost
  certainly silently skipped as untrusted, the same silent gate this
  section documents for repo hooks. Plugin-level hooks WORK on Codex. Event
  inventory: `SubagentStart` exists (unlike Cortex); `ConfigChange` and
  `SessionEnd` do not. Details in COMPATIBILITY.md.
- **Codex skill auto-discovery — ANSWERED 2026-07-25.** Works, from
  `.codex/skills/` and `.agents/skills/` (not `.claude/skills/`, not bare
  `skills/`); plugin skills load namespaced `<plugin>:<skill>`, including
  headless. Not trust-gated. ~~unlike Claude Code's `-p`~~ — that contrast
  is gone: Claude Code's `-p` was found 2026-08-09 to load plugin skills
  too (COMPATIBILITY.md → Claude Code → Headless).
- **Codex `settings.json` equivalent — ANSWERED 2026-07-25:**
  `~/.codex/config.toml` plus `-c` dotted-path overrides; no consumer of a
  plugin-root `settings.json` observed. The Cortex half of this question is
  still open.

Each answer, once verified, moves from here into `COMPATIBILITY.md`.

## Design Principle

**Default to one shared implementation.** Skills, agents, and core scripts are
written once and used by all three platforms unchanged.

**Reach for a per-platform adapter only where a platform's shape genuinely
diverges** — the deleted `build_preset.py`'s inline three-manifest block was
the earlier example of this: one shared `manifest` dict, three small
platform-specific serializations. Today the shared shape lives in each
plugin's single hand-written `.claude-plugin/plugin.json`; reach for an
adapter from there only where a platform's shape genuinely diverges. Don't
build abstraction layers or adapter classes ahead of a proven divergence; a
few extra lines inline beats premature structure.

When a real divergence is found (e.g., a hook payload shape Codex needs that
Claude Code doesn't), it gets a small, named adapter next to the shared logic —
not a rewrite of the shared path.

## Non-Goals

- Not chasing platforms beyond Claude Code, Codex, and Cortex Code.
- Not guaranteeing feature parity when a platform lacks a concept outright
  (e.g., if a platform has no hook system equivalent, that's a documented gap
  in `COMPATIBILITY.md`, not something to work around or fake).
