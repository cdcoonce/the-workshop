# Roadmap: Multi-Agent Platform Support

This build system targets three coding-agent platforms as first-class outputs:
**Claude Code**, **Codex**, and **Cortex Code (CoCo)**. A preset built here should
install and run natively on any of the three without an install-time transform.

## Current Status

Shipped:

- Every preset build emits three plugin manifests from one shared source —
  `.claude-plugin/plugin.json` (Claude Code), `.codex-plugin/plugin.json` (Codex),
  `.cortex-plugin/plugin.json` (Cortex Code) — see `scripts/build_preset.py`.
- Cortex Code currently reuses the Codex manifest shape verbatim — **now known
  to be wrong**: Cortex reads `.claude-plugin/plugin.json`, and the
  `.cortex-plugin/` manifest appears to be read by nothing. See COMPATIBILITY.md.
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
  rather than erroring.
- Do Codex's hook semantics match? Unverified — the same probe has not been run
  against Codex.
- Is there a Codex/Cortex equivalent of `settings.json` (non-hook settings),
  or does that concept not transfer?

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
