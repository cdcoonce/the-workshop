# /dispatch — Idea → Documented afk Issue

Close the dispatch seam: turn an idea, decision, or pain point from the live session into a well-shaped, budgeted GitHub issue in an afk-managed repo — filed, labeled, optionally promoted, and linked back into the vault graph. This is the afk-lite replacement (see [[2026-06-11-unified-dev-system-design]]): the live session does the _thinking_ (shaping the issue is frontier-judgment work); the afk pipeline does the _building_. Issues, never code.

## When to run

- Charles says "dispatch this" / "file that for afk" / a session decision produces afk-sized correctness work (the dogfood directive: route it through file → promote → execute → merge, don't hand-code it).
- NOT for greenfield/strength/too-coupled work Charles wants to build live, and NOT a TODO list — every dispatch must be executor-implementable as written.

## Procedure

1. **Resolve the target repo** (default `cdcoonce/afk-agent-system`). The idea must be self-contained enough to build cold — the executor gets the issue body, not this conversation.
2. **Size it.** `afk-sized` = one concern in **existing files** (plus their tests), executor-implementable with clear acceptance criteria. **A new module is never afk-sized** — the scope gate quarantines slices whose changes persist outside the issue's footprint (learned 2026-06-11: afk#324, a new-module mechanism dispatched as afk-sized, quarantined on scope after 4 attempts). New module/mechanism, multi-concern, or architectural → file with `decompose:ready` and let `--decompose` produce the children; never hand-split. Cross-check: if your own Budget estimate is >1 slice, interrogate the afk-sized call before filing.
3. **Duplicate check.** `gh issue list --repo <repo> --search "<keywords>"` across open issues; also check closed for `scout-rejected` / `superseded` — don't re-file a rejected idea without saying so.
4. **Write the body in the proven shape** (model: afk#313):
   - `## Problem` — what's wrong/missing and why it matters.
   - `## Evidence` — cite real artifacts: vault notes, PR/issue numbers, telemetry lines. No fabrication; thin evidence is fine, invented evidence is not.
   - `## Proposed behavior` — concrete enough to build, including exact messages/flags where relevant.
   - `## Acceptance criteria` — checkboxes; MUST include a test criterion.
   - `## Budget` — `~N slices · tier: cheap|frontier` + one line of reasoning. (The driver doesn't parse this yet — it's the contract convention; the parser is a queued dispatch.)
   - `## Notes` — size rationale ("afk-sized: localized to …") + program/design wikilinks.
5. **File it.** `gh issue create --repo <repo> --title "<imperative title>" --label "proposed,afk-sized"` (epics: `proposed,decompose:ready`). Add `afk:cheap` or `afk:frontier` when the tier call is clear — only if the repo has those labels (the-workshop doesn't; the Budget line carries the tier there).
   - **Two decompose flavors (learned 2026-07-17, afk#875):** `decompose:ready` alone → a _plain_ decomposed parent; its children are ordinary afk-sized issues promoted **individually** with `--promote <child>` (`Depends on #N` still gates scheduling), and `--promote-epic` will NOT work on it (its errors are misleading — don't re-decompose). Label the parent `afk:epic` **before** `--decompose` only when you want the unit flow: children get `Target: afk/epic-<N>` markers, integrate on an epic branch, and are approved as a DAG via `--promote-epic`. Default to the plain flavor.
6. **Promotion decision** — apply the low-risk test below. Pass → promote via the pinned toolbox command: `uv run --directory /Users/cdcoonce/Developer/GitHub/afk-agent-system afk-driver --project . --repo <repo> --promote <N>`. Fail → leave `proposed` and print the promote command for Charles.
7. **Link it into the graph.** Add the issue (as a markdown link with one-line context) to the most relevant vault note — the project note, the design note, or the note that sparked it. A dispatch that isn't in the graph didn't happen, Connections-wise.
8. **Digest:** issue URL, labels, size call, promoted-or-not + which test clause decided it, vault note updated.

## Low-risk auto-promotion test

**Owned by [[Constitution]] §3** (Charles-tuned 2026-06-11) — if this block and the Constitution disagree, the Constitution wins and this block is the bug. Auto-promote ONLY if **all** hold; otherwise leave `proposed`:

- **Origin: this skill.** Only issues shaped via `/dispatch` qualify; Scout proposals and other origins always wait for human triage.
- Localized, single-concern change (true `afk-sized`, not a borderline call).
- Budget ≤ 2 slices, any tier.
- Acceptance criteria include tests.
- Touches **no** deny-surface: autonomy/gate/permission config, CI, security (secrets, auth, egress, execution isolation) — NEVER auto-promoted, no exceptions.
- Never epics.

## Constraints

- **Issues, never code.** If you catch yourself writing the fix, stop — that's the executor's job.
- **One issue per dispatch.** Batch ideas = multiple dispatches or one epic.
- **The body must stand alone.** Link vault notes for background, but the executor builds from the issue text — no "as discussed" references.
- **Don't crawl the target repo** to write the issue. Cite what you know (vault, PRs, telemetry); code archaeology is the slice's job. If you can't write acceptance criteria without reading the code, the idea isn't dispatch-ready — say so.
- **Respect the human gate.** When in doubt about promotion, don't.
