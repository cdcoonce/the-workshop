# Brainstorm: Flat-toolbox plugin reorg — one workbench, live-referenced vault (2026-08-08)

**Status.** Decision record from a completed grill-me session (22 branches resolved).
**Supersedes** `2026-08-01-plugin-architecture-reorg.md` in full: the catalog/profiles
(graph-derived plugins) direction is tombstoned. This document authorizes planning —
a blueprint map and PRD — not implementation.

**Problem (unchanged).** Core-vs-presets membership is hand-curated, has drifted, and
no longer describes how skills are consumed. The 2026-08-01 answer was to _compute_
membership from a dependency graph. The owner's re-judgment: with a single-consumer
marketplace and an install set that is in practice "everything, everywhere," there is
no membership problem left to compute. Collapse the boxes instead of deriving them.

**Why this supersedes the graph direction.** The graph bought legibility across 10
hand-curated presets. Ten presets stop existing here. With one toolbox plugin, the
2026-08-01 frozen criteria are met trivially: single registration (one copy of every
skill, by construction), no co-install overlap (nothing to co-install), staleness
legible (version-bump gate + fail-loud version check), disjointness (the filesystem is
the membership authority). The catalog, profiles, extracted edges, solver-vs-validator
question, and computed router are all dead. Carried forward from the old record: the
Cortex inline-manifest-hooks probe (#487), the cache-hygiene premortem (stale desktop
plugin copies shadow on name collision — cutover must verify), and the completed
wayfinder→blueprint rename.

## Decisions (grill log, 2026-08-08)

**Intent.**

1. Flat plugin directories; no core/, no composition build, no validator component.
   Small CI checks only (slug uniqueness, generated-file drift, hook-copy sync).
2. Done = reorg + full re-inventory shipped, all installed machines migrated.
3. Vault-from-plugin becomes first-class and generic: `vault-init` is de-personalized
   and scaffold-only — anyone installing the plugin can stand up a vault.

**Scope.**

4. Roster: **one `workbench` uber-toolbox** (universal + data-domain + vault skills,
   all shared hooks, vault machinery) + `workshop-maintainer` (separate: its skills
   only matter when developing this repo) + 5 persona plugins + 2 advisor plugins =
   9 marketplace entries. An intermediate generic/data-stack split was considered and
   collapsed by the owner mid-grill.
5. Re-inventory is a **full per-skill value review**: all 78 skills get
   keep / consolidate / retire / relocate verdicts; consolidation is in scope.

**Design.**

6. Version-bump gate stays for every plugin.
7. All three platform manifests ship (`.claude-plugin`, `.codex-plugin`,
   `.cortex-plugin`); tri-platform support (Claude Code, Codex, Cortex) is a hard
   constraint. `.cortex-plugin` removal is deferred to the Cortex probe.
8. `dist/` dies; **source directories are the plugins** — marketplace points at
   `plugins/<name>/`. A tiny in-place stamper generates the derivable files
   (codex/cortex manifests, README tables, marketplace.json, persona hook copies)
   with a `--check` mode in CI. `build_preset.py`, `dist_digest`, `verify-generated`,
   `prune-dist` all die.
9. Names stay (`workbench`, persona/advisor names); only the `vault-ops` entry is
   removed. No rename pass.
10. `inject_persona.py` + `run-hook.sh` copies in the 7 persona/advisor plugins are
    stamper-synced from one canonical source.
11. Vault machinery and all 26 vault skills fold into `workbench`.
12. **Live-reference update model**: the vault executes machinery from the installed
    plugin. `machinery_sync`, `machinery_check`, the lockfile, and `/vault-upgrade`
    are deleted. The vault becomes a plugin client; updating the plugin updates every
    vault behavior. Acknowledged trade (owner accepted knowingly): the vault is no
    longer self-contained — a bare clone without the plugin is inert, and version skew
    between machines is invisible except through (14).
13. Vault hooks ship **plugin-level with an is-this-a-vault guard** — gated on a
    fresh controlled probe against current Cortex (~v1.18): if plugin-level hooks are
    still inert there, the pre-agreed fallback is a thin vendored shim (one stable
    dispatch script scaffolded by vault-init). Owner observation that hooks now fire
    on Cortex contradicts the 2026-07-23 v1.1.8 probe and supports the v1.18.0
    bundled-spec note in COMPATIBILITY.md — evidence decides, not recollection.
14. Missing/stale plugin fails loud at session start; the vault declares a minimum
    plugin version in one config line.

**Dependencies.**

15. The pip installer (`scripts/installer/`, the committed wheel/tarball, its tests)
    is deleted. Marketplace install covers all three platforms.
16. GitLab is push-on-demand only; `sync-gitlab-dev` survives as the manual flow,
    updated for the flat layout. The reorg has no GitLab landing requirement.

**Testing.**

17. Composition tests die with the composition layer. Hook/skill content tests and
    machinery engine tests survive. New TDD surface: stamper `--check`, slug
    uniqueness, persona-hook sync, vault guard, fail-loud version check.

**Deployment.**

18. **Review first**: Phase 1 produces the 78-skill verdict table as a reviewable
    document (no code moves); Phase 2 structurally relocates only the survivors.
19. Execution: blueprint map → PRD → mixed lanes. Judgment work (verdicts, stamper,
    hook wiring, vault-init rewrite) runs interactive; well-specced mechanical slices
    (per-skill moves, test ports, doc regen) drain through afk.
20. **Big-bang cutover, same day**: reorg lands dev→main as one release; both
    machines and the-vault migrate immediately (uninstall vault-ops, refresh
    workbench, clear stale caches, delete the vault's vendored tier + lockfile) with
    a per-platform verify checklist. No tombstone period — single-consumer.

## Open items (owned by later phases)

- **Cortex probe** against current v1.18.x — gates (13) and settles (7). Cheapest
  first move; method documented in COMPATIBILITY.md, tracking issue #487.
- **Overlap verdicts** — triage-issue/vault-fix-issue, adversarial-review/
  vault-cold-read, dev-cycle/drain-queue/vault-dispatch, setup-pre-commit staleness —
  resolved by the Phase 1 review, not pre-decided.
- **Bucket taxonomy** — with one toolbox, "buckets" are the within-workbench category
  scheme for docs/README; skill-inventory's 7-bucket taxonomy is the starting
  vocabulary and Phase 1 assigns each survivor a bucket.
- **De-personalization scope** — decided for vault-init; whether the other 25 vault
  skills' owner-specific trigger descriptions generalize is a per-skill Phase 1 call.
- `.claude/skills/security-review` drift copy — one-line sync, do inline anytime.

**Routing.** blueprint — chart the map (Phase 1 review process, stamper design,
Cortex probe, vault migration mechanics), then PRD, then mixed-lane execution.
