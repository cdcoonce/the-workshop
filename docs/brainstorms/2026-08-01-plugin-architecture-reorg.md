# Brainstorm: Plugin architecture reorg — graph-derived plugins (2026-08-01)

**Status.** Decision record only — this document authorizes no build. Next lane is a
grill-me stress-test; implementation starts only after that and a PRD.

**Problem.** Co-installing Workshop presets puts duplicate copies of shared skills into
every session (routing ambiguity, context bloat, version skew), and the core-vs-presets
model no longer describes how skills are actually consumed — membership is hand-curated
and has drifted once already.

**Appetite.** Big: multi-session restructure with migration. Hard constraint: the
plugin/marketplace install style is retained — no switch to git-vendored skill delivery.

**Direction.** The dependency graph becomes the source of truth. Every skill declares
its edges once, in frontmatter: `hands-off-to`, `requires-hook`, `requires-script`, and
`trigger-class: deterministic | model | user` (deterministic = harness-injected at a
defined moment; model = description-matched by the agent; user = slash-invoked only,
hidden from model invocation; "guard-class" below means a deterministic subset).
Reachability traverses all edge types — hooks and scripts are graph nodes, so a
computed plugin bundles the hooks and scripts its skills require. Plugins become
**computed outputs** of graph queries ("everything reachable from these roots"),
**disjoint for any machine's install set** — a skill can never register twice. The
disjointness invariant is decided; whether a solver computes the partition or a
validator rejects overlap is a deferred mechanism choice (open questions). Core-vs-presets vocabulary
dies: there is a **catalog** (all skills + edges) and **profiles** (named queries that
build plugins). Staleness is answered in-channel: a `doctor` command plus
loaded-version-vs-source surfacing at session start. Session-start resolution (Claude
hook reading the graph) and moment-of-need injection for guard-class skills are optional
Claude-side consumers, not the architecture. This bets that **legibility is the root
problem** — overlap, drift, and forgotten skills are symptoms of hand-maintaining what
should be derived.

**Sequencing change bound into the verdict.** A cheap fix is a separate prerequisite,
not part of this build, and IS authorized now: purge stale plugin caches and end
today's co-install overlap. The grill-me stress-test may run in parallel with living
with the cheap fix; the owner's re-judgment of whether the rebuild still earns its
appetite happens after both, and gates the PRD. If the cheap fix bought most of the
relief, this direction shrinks or dies — a success of the gate, not a failure of the
plan.

**Criteria (frozen).**

1. Single registration — every skill appears exactly once in a session's catalog
   (one copy, one version); invocation count is unlimited.
2. Trigger fidelity — per-skill trigger class is first-class and actually fires.
3. Staleness legible in one command — what's loaded, at what version, vs source.
4. Graph queryable — all four edge types declared once and used by the build.
5. One-step team install that still lands on Codex/Cortex (the non-Claude agent
   platforms, where skills are the only portable layer).

**Killed options.**

- Repartition the presets by hand — bet better boxes end overlap; lost because curated
  membership re-drifts (this brainstorm exists because the last repartition drifted).
  Extracted: membership must be computed, never curated.
- Atomic per-skill install — bet no bundles, no drift; lost on 78-unit install strain,
  and profiles-as-lockfiles reinvent bundles. Extracted: flat namespace, skill-level identity.
- Session-start resolver (standalone) — bet only the session can compose; lost because a
  SessionStart hook serves Claude only. Survives as a consumer of the graph.
- Retrieval concierge — bet discovery is the whole game; lost on the platform gate and
  on model-noticing reliability. Survives as optional guard-class injection on Claude.
- Git-vendored transport — bet git is the only trustworthy channel; killed by owner
  constraint (plugin style stays). Extracted: staleness legibility moves in-channel
  (doctor + version surfacing).

**Premortem risks (winner).**

1. Cache hygiene never lands — old plugin versions and desktop shadow copies keep
   loading beside new computed plugins; doctor must hard-fail on them.
2. Graph rot — declared edges drift from prose behavior; CI must grep skill bodies for
   references and fail on undeclared edges.
3. Frame wrong — most felt pain was the stale cache plus one overlapping preset; the
   cheap-fix-first step exists to expose this before the rebuild is judged.
4. Determinism gets noisy — hard-wired injection fires unwanted skills; budget tokens
   per injection point, demote trigger-class with a one-line edit.

**Open questions (deferred).**

- The profile set: which machines/contexts install which computed plugins, and whether
  workshop-maintainer remains separately installable or becomes a profile.
- How deterministic trigger-class is enforced per platform (hooks on Claude;
  descriptions-only on Codex/Cortex — what degrades, and is that acceptable).
- What happens to the five persona presets and two advisors under catalog/profiles.
- Migration order and marketplace versioning discipline (who bumps what, when).
- Whether `using-workflow` router content is subsumed by the graph (computed router).
- Disjointness mechanism: build-time solver that partitions shared skills into a
  computed shared plugin, vs a validator that errors on overlap and forces a human
  refactor.
- Version identity per skill (frontmatter semver vs content hash vs plugin version) —
  what doctor and session-start surfacing actually compare.
- CI edge-check semantics: what counts as a prose reference, and whether a declared
  edge with no reference is also a failure.

**Routing.** grill-me — stress-test this direction hard before any PRD.

---

## Grill outcomes (2026-08-01, direction survives with decisions)

Seventeen branches resolved; the PRD lane inherits these as settled unless re-opened.

- **Done bar:** graph + build enforcement is the MVO; doctor and session-start
  surfacing trail. Defended failure mode: authoring tax.
- **Scope:** agents, methodology docs, and settings/hook wiring all join the graph as
  nodes (maximal graph). Personas/advisors out of scope v1. vault-ops machinery joins
  via extracted (not authored) edges.
- **Edges:** extract-first — script imports via AST, skill references via body parsing
  (a reference counts only if it resolves to a catalog slug and sits outside code
  fences; router-class docs may set `extract-edges: false`). Frontmatter declares only
  trigger-class and intentional hands-off-to.
- **Disjointness:** validator, not solver — profile roots are human intent, closures
  are computed, overlap across an install set is a hard build error.
- **Profiles:** one plugin per scope. Named unions are their own computed plugins
  (vault-station, data-repo, workshop-dev, team-starter); co-installation ceases to
  exist. New marketplace names; legacy presets tombstoned one release, then dropped.
- **Router:** using-workflow stays hand-written in v1; graph-generated router is a
  later consumer.
- **Versioning:** skill identity = content hash (computed at build); humans see plugin
  semver. Staleness = hash mismatch.
- **Trigger moments v1:** SessionStart + pre-commit wired; further moments schema-only.
- **Orphans:** build error unless `status: shelved` — every skill ships somewhere or
  is explicitly parked.
- **Off-Claude determinism:** build emits a vendorable codex-enable artifact per
  profile (#486); Cortex inline-manifest hooks gated on probe #487; honest
  description-matched degrade until then.
- **Cutover:** big bang (owner accepts risk — all machines are the owner's); schedule
  on a day with no in-flight sessions. Cheap fix executed 2026-08-01: stale plugin
  cache purge + per-project enablement scoping.
- **Deferred to PRD:** exact root lists per profile, pre-commit moment mechanics,
  doctor UX, per-project enablement mechanics, Cortex probe outcome, persona
  migration, generated router.
- **Naming (owner decision, 2026-08-01):** skill names stay unthemed — clarity is
  load-bearing; a workshop-metaphor rename pass was considered and rejected. Single
  exception: `wayfinder` renames to `blueprint` once its first vault run reaches a
  stopping point (independent of the cutover). The rename is a migration, not a mv:
  the `wayfinder:*` label namespace on every tracker hosting a map (afk#1105 et al.)
  must relabel to `blueprint:*` atomically with the skill, or the renamed skill's
  label queries read live maps as complete. Profile names stand as decided above.
