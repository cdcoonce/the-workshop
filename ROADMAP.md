# Roadmap: Multi-Agent Platform Support

This build system targets three coding-agent platforms as first-class outputs:
**Claude Code**, **Codex**, and **Cortex Code (CoCo)**. A preset built here should
install and run natively on any of the three without an install-time transform.

## Current Status

Shipped:

- Every preset build emits three plugin manifests from one shared source —
  `.claude-plugin/plugin.json` (Claude Code), `.codex-plugin/plugin.json` (Codex),
  `.cortex-plugin/plugin.json` (Cortex Code) — see `scripts/build_preset.py`.
- Cortex Code reuses the Codex manifest shape verbatim — **probe-verified
  2026-08-08 (v1.20.2, #634): correct after all.** Cortex reads both
  `.cortex-plugin/plugin.json` (its primary convention) and
  `.claude-plugin/plugin.json`, and executes plugin hooks (file-based and
  inline). Caveat: Cortex does not set `CLAUDE_PLUGIN_ROOT`, so this repo's
  hook commands fail to resolve there. See COMPATIBILITY.md.
- Hook matchers cover all three platforms' tool-ID naming conventions in one
  pattern (`edit|write|multi_edit|Edit|Write|MultiEdit`).
- Codex plugin marketplace support (`.agents/plugins/marketplace.json`,
  `scripts/build_marketplace.py`).

Open questions (tracked here until resolved, not blocking):

- **Cortex hook semantics — ANSWERED 2026-07-23.** Payload shape, exit codes,
  and JSON output match Claude Code's. But Cortex has **no `SubagentStart` and
  no `ConfigChange`**, so two shipped hooks never fire and the subagent evidence
  gate is silently inert. Details in COMPATIBILITY.md.
- **Cortex skill auto-discovery — ANSWERED 2026-07-23.** Works, from
  `.cortex/skills/`, `.claude/skills/`, and `.snova/skills/`; `~/.claude/skills/`
  is treated as project-level for compatibility.
- **Does Cortex read a plugin-level `hooks/hooks.json`? — ANSWERED 2026-07-23:
  no.** Tested on a machine with `workbench` active: no plugin-declared hook has
  ever executed, while an identical `SessionStart` hook in the user-level
  `~/.snowflake/cortex/hooks.json` fired immediately under the same headless
  probe. **No Workshop hook runs on Cortex.** Skills work fully.
- Given that: should the build emit Cortex hooks inline in `plugin.json` (the
  shape Cortex's own bundled plugins use), or should Cortex be documented as a
  skills-only target? A real decision, not a defect — the hooks degrade silently
  rather than erroring. **The same decision now applies to Codex** (see next
  item): as of 2026-07-25 presets are skills-only carriers on both non-Claude
  platforms; on Codex, hooks ship via the vendored repo-level
  `.codex/hooks.json` the vault-ops machinery already generates.
- **Codex hook semantics — ANSWERED 2026-07-25.** Repo-level flat
  `.codex/hooks.json` only (nested path proven unread by control); a
  two-layer silent trust gate (project `trust_level` in `config.toml` +
  per-hook `trusted_hash`, bypass flag covers only the latter); no stdin/env
  payload; plugin-level hooks impossible — the `plugin_hooks` feature is
  `removed`. Event inventory: `SubagentStart` exists (unlike Cortex);
  `ConfigChange` and `SessionEnd` do not. Details in COMPATIBILITY.md.
- **Codex skill auto-discovery — ANSWERED 2026-07-25.** Works, from
  `.codex/skills/` and `.agents/skills/` (not `.claude/skills/`, not bare
  `skills/`); plugin skills load namespaced `<plugin>:<skill>`, including
  headless — unlike Claude Code's `-p`. Not trust-gated.
- **Codex `settings.json` equivalent — ANSWERED 2026-07-25:**
  `~/.codex/config.toml` plus `-c` dotted-path overrides; no consumer of a
  plugin-root `settings.json` observed. The Cortex half of this question is
  still open.

Each answer, once verified, moves from here into `COMPATIBILITY.md`.

## Design Principle

**Default to one shared implementation.** Skills, agents, and core scripts are
written once and used by all three platforms unchanged.

**Reach for a per-platform adapter only where a platform's shape genuinely
diverges** — the inline three-manifest block in `build_preset.py` is the
existing example: one shared `manifest` dict, three small platform-specific
serializations. Don't build abstraction layers or adapter classes ahead of a
proven divergence; a few extra lines inline (like today's manifest block) beats
premature structure.

When a real divergence is found (e.g., a hook payload shape Codex needs that
Claude Code doesn't), it gets a small, named adapter next to the shared logic —
not a rewrite of the shared path.

## Non-Goals

- Not chasing platforms beyond Claude Code, Codex, and Cortex Code.
- Not guaranteeing feature parity when a platform lacks a concept outright
  (e.g., if a platform has no hook system equivalent, that's a documented gap
  in `COMPATIBILITY.md`, not something to work around or fake).
