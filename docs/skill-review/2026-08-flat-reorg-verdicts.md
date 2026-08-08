# Skill Review — Flat-Reorg Verdict Table (2026-08-08)

Phase 1 of the flat-toolbox reorg (map: [#633](https://github.com/cdcoonce/the-workshop/issues/633),
rubric: [#635](https://github.com/cdcoonce/the-workshop/issues/635), this table:
[#636](https://github.com/cdcoonce/the-workshop/issues/636)). Seven parallel graders
pre-graded all 79 skills; the owner adjudicated every proposed retire/consolidate/relocate
and every overlap set (rulings in the Adjudication log at the bottom). Phase 2 executes
this table row by row.

Verdicts: `keep` | `consolidate-into-<slug>` | `retire` | `relocate-to-<dest>` | `shelve`.
Usage = transcript files with a genuine `Launching skill:` invocation marker (bare-slug
matches are meaningless — every session prompt lists every skill); evidence informs,
never rules.

## core/skills/ (36)

| Skill                      | Verdict    | Bucket           | Usage                                      | Overlap / notes                                                                              |
| -------------------------- | ---------- | ---------------- | ------------------------------------------ | -------------------------------------------------------------------------------------------- |
| adversarial-review         | keep       | quality-review   | 0 files; 2026-07-31                        | vs vault-cold-read: distinct phase (post-work attack vs pre-promotion spec gate) — keep-both |
| blueprint                  | keep       | planning-shaping | 8 files; 2026-08-01                        | self-delineated vs brainstorm/grill-me/PRD flows                                             |
| brainstorm                 | keep       | planning-shaping | 3 files; 2026-07-25                        | clean handoff contract downstream                                                            |
| commit                     | keep       | daily-workflow   | 17 files; 2026-07-18                       | foundational; highest-used in its batch                                                      |
| create-hook                | keep       | routing-infra    | 0 files; 2026-07-20                        | unique capability; no substitute                                                             |
| daa-code-review            | keep       | quality-review   | 0 files; 2026-07-23 (33 commits since May) | boundary vs security-review self-documented                                                  |
| design-an-interface        | keep       | planning-shaping | 0 files; 2026-07-17                        | named methodology (Design It Twice); no duplicate                                            |
| detector-teeth-check       | keep       | quality-review   | 3 files; 2026-07-26                        | load-bearing dependency of drain-queue's landing gate                                        |
| dev-cycle                  | keep       | daily-workflow   | 0 files; 2026-07-25                        | lane boundary vs drain-queue/vault-dispatch self-documented                                  |
| dignified-python           | keep       | quality-review   | 2 files; 2026-07-18                        | proactive standards vs daa-code-review's post-hoc pipeline                                   |
| drain-queue                | keep       | daily-workflow   | 0 files; 2026-08-07 (1 day old)            | zero usage is age artifact; re-evaluate later                                                |
| finish-branch              | keep       | daily-workflow   | 1 file; 2026-07-20                         | composes with commit + github-cli                                                            |
| github-cli                 | keep       | daily-workflow   | 0 files; 2026-07-27                        | platform-parallel to gitlab-cli                                                              |
| gitlab-cli                 | keep       | daily-workflow   | 0 files; 2026-07-23                        | boundary vs gitlab-mr-create carved in-skill                                                 |
| grill-me                   | keep       | planning-shaping | 0 files; 2026-07-18                        | vs vault-grill: name collision only                                                          |
| mr-merge-order             | keep       | daily-workflow   | 0 files; 2026-07-27                        | real script+tests; insurance-use profile                                                     |
| mr-review-fixes            | keep       | daily-workflow   | 0 files; 2026-07-27                        | vs vault-mr-review-packet: verified NOT an overlap (opposite direction)                      |
| plan-ceo-review            | keep       | planning-shaping | 4 files; 2026-07-18                        | distinct from grill-me/adversarial-review                                                    |
| prd-to-issues | keep (absorbs prd-to-plan) | planning-shaping | 1 file; 2026-07-25 | merged skill gains a `--plan` output mode; final slug decided in Phase 2 |
| prd-to-plan | **consolidate-into-prd-to-issues** | n/a | 0 files; 2026-07-18 | near-verbatim shared slicing methodology; only output format differed |
| project-context            | keep       | routing-infra    | 0 files; 2026-07-18                        | machine-facing; complementary to repo-reference-docs                                         |
| repo-reference-docs        | keep       | daily-workflow   | 0 files; 2026-07-31                        | human-facing counterpart to project-context                                                  |
| request-refactor-plan      | keep       | planning-shaping | 0 files; 2026-07-23                        | refactor-specific framework; not generic PRD shaping                                         |
| security-review            | keep       | quality-review   | 0 files; 2026-07-23                        | role boundary vs daa-code-review self-documented                                             |
| setup-pre-commit           | **retire** | n/a              | 0 files ever; 2026-03-22                   | abandoned one-off predating the modern era; nothing references it                            |
| shared-tree-safety         | keep       | routing-infra    | 7 files; 2026-07-23                        | guard with real invocation evidence                                                          |
| sql-deploy-precheck        | keep       | data-domain      | 0 files; 2026-07-31                        | live half of pair with warehouse-sql-test-harness                                            |
| stale-artifact-sweep       | keep       | quality-review   | 0 files; 2026-07-31                        | pre-step for mr-merge-order/mr-review-fixes/triage-issue                                     |
| tdd                        | keep       | daily-workflow   | 21 files; 2026-07-18                       | most-used skill in review; foundational                                                      |
| transcript-notes           | keep       | daily-workflow   | 0 files; 2026-07-22                        | vs vault-teach: different mechanism and lifecycle — keep-both                                |
| triage-issue               | keep       | planning-shaping | 1 file; 2026-07-23                         | vs vault-fix-issue: sequential stages (investigate+file vs implement) — keep-both            |
| triage-quarantine          | keep       | routing-infra    | 6 files; 2026-07-25                        | unique afk-diagnostic niche with real usage                                                  |
| using-workflow             | keep       | routing-infra    | 3 files; 2026-07-25                        | vault-ops copy collapses to one in the merge (mechanical)                                    |
| warehouse-sql-test-harness | keep       | data-domain      | 0 files; 2026-07-31                        | offline half of pair with sql-deploy-precheck                                                |
| worktree-audit             | keep       | routing-infra    | 1 file; 2026-08-01                         | complements shared-tree-safety                                                               |
| write-a-prd                | keep       | planning-shaping | 1 file; 2026-07-17                         | upstream of the prd family; scope vs prd-to-plan confirmed distinct at adjudication          |

## presets/workbench/skills/ (8)

| Skill                 | Verdict | Bucket         | Usage               | Overlap / notes                                                       |
| --------------------- | ------- | -------------- | ------------------- | --------------------------------------------------------------------- |
| chart-taste           | keep    | ui-domain      | 0 files; 2026-07-17 | boundary vs react-ui-ux carved in-skill                               |
| dagster-expert        | keep    | data-domain    | 0 files; 2026-07-17 | distinct tool in data family                                          |
| data-discovery        | keep    | data-domain    | 0 files; 2026-08-04 | newest in family; distinct deliverable                                |
| dbt-expert            | keep    | data-domain    | 0 files; 2026-07-17 | distinct tool in data family                                          |
| gitlab-mr-create      | keep    | daily-workflow | 0 files; 2026-07-28 | layered call chain, not duplicate                                     |
| gitlab-promotion-flow | keep    | daily-workflow | 0 files; 2026-07-25 | policy layer above gitlab-mr-create                                   |
| react-ui-ux           | keep    | ui-domain      | 0 files; 2026-07-17 | container complement to chart-taste                                   |
| walkthrough | keep | daily-workflow | 0 files; 2026-07-31 | MR-mode boundary vs vault-mr-review-packet documented in both (no merge) |

## presets/vault-ops/skills/ (26) — all move into workbench, `vault-ops` bucket

| Skill                       | Verdict                            | Bucket    | Usage                | Overlap / notes                                                        |
| --------------------------- | ---------------------------------- | --------- | -------------------- | ---------------------------------------------------------------------- |
| vault-audit                 | keep                               | vault-ops | 0 files; 2026-07-23  | no core analog                                                         |
| vault-budget                | keep                               | vault-ops | 0 files; 2026-07-23  | unique niche                                                           |
| vault-clickup-task-sync     | keep                               | vault-ops | 0 files; 2026-07-23  | no core equivalent                                                     |
| vault-cold-read             | keep                               | vault-ops | 0 files; 2026-08-02  | vs adversarial-review: distinct pipeline stage — keep-both             |
| vault-connect               | keep                               | vault-ops | 0 files; 2026-07-23  | absorbs vault-link (see log)                                           |
| vault-context-then-delegate | keep                               | vault-ops | 0 files; 2026-07-23  | unique pre-delegation grounding                                        |
| vault-debrief               | keep                               | vault-ops | 0 files; 2026-07-31  | distinct meta-analysis                                                 |
| vault-dispatch              | keep                               | vault-ops | 0 files; 2026-07-31  | vault-linkback bridge dev-cycle/drain-queue lack — keep-both           |
| vault-dump                  | keep                               | vault-ops | 0 files; 2026-07-23  | Obsidian-specific inbox routing                                        |
| vault-essay                 | keep                               | vault-ops | 0 files; 2026-07-23  | depersonalize in Phase 2                                               |
| vault-find                  | keep                               | vault-ops | 0 files; 2026-07-23  | semantic search infra                                                  |
| vault-fix-issue             | keep                               | vault-ops | 2 files; 2026-07-23  | vs triage-issue: build-execution vs investigate+file — keep-both       |
| vault-garden                | keep                               | vault-ops | 3 files; 2026-07-27  | apply-stage of graph family                                            |
| vault-grill                 | keep                               | vault-ops | 2 files; 2026-07-23  | vs grill-me: name collision only                                       |
| vault-handoff               | keep                               | vault-ops | 2 files; 2026-07-23  | distinct trigger granularity from wrap-up                              |
| vault-init                  | keep                               | vault-ops | 0 files; 2026-07-25  | scaffold-only + generalized (pre-decided)                              |
| vault-link                  | **consolidate-into-vault-connect** | n/a       | 0 files; 2026-07-23  | manual single-term instance of connect's pass; becomes a `--term` mode |
| vault-mr-review-packet      | keep                               | vault-ops | 0 files; 2026-07-23  | mr-review-fixes overlap verified false                                 |
| vault-pulse                 | keep                               | vault-ops | 0 files; 2026-07-26  | bespoke ledger, own scripts                                            |
| vault-recall                | keep                               | vault-ops | 0 files; 2026-07-23  | unique consolidation pipeline                                          |
| vault-standup               | keep                               | vault-ops | 0 files; 2026-07-23  | distinct from wrap-up/project-context                                  |
| vault-sync                  | keep                               | vault-ops | 0 files; 2026-07-23  | sync-specific concerns commit doesn't cover                            |
| vault-teach                 | keep                               | vault-ops | 0 files; 2026-07-23  | stateful tutor vs transcript-notes one-shot                            |
| vault-upgrade               | **retire**                         | n/a       | 6 files; 2026-07-25  | live-reference deletes its target pipeline (pre-decided)               |
| vault-wrap-up               | keep                               | vault-ops | 31 files; 2026-07-27 | highest usage in entire review                                         |
| vault-write                 | keep                               | vault-ops | 0 files; 2026-07-23  | depersonalize in Phase 2                                               |

## presets/workshop-maintainer/skills/ (7) — stays a separate plugin

| Skill                  | Verdict                                     | Bucket           | Usage               | Overlap / notes                                            |
| ---------------------- | ------------------------------------------- | ---------------- | ------------------- | ---------------------------------------------------------- |
| add-the-workshop-hook  | keep                                        | maintainer       | 0 files; 2026-07-28 | paths need full rework post-reorg                          |
| improve-skill          | keep                                        | maintainer       | 0 files; 2026-07-21 | distinct benchmark loop; agents dependency needs rework    |
| land-skill-candidate   | **consolidate-into-workshop-skill-creator** | n/a              | 0 files; 2026-07-28 | near-verbatim duplicate steps; becomes an intake mode      |
| persona-builder        | **relocate-to-workbench**                   | planning-shaping | 2 files; 2026-07-23 | builds user-facing personas; not repo self-maintenance     |
| skill-inventory        | **retire**                                  | n/a              | 2 files; 2026-07-21 | audits a preset-boundary model that stops existing         |
| sync-gitlab-dev        | keep                                        | maintainer       | 1 file; 2026-07-28  | dual-remote flow survives; script path updates             |
| workshop-skill-creator | keep                                        | maintainer       | 3 files; 2026-07-23 | entry point; absorbs land-skill-candidate; routing rewrite |

## Advisors (2) — separate plugins, unchanged

| Skill                    | Verdict | Bucket  | Usage               | Overlap / notes     |
| ------------------------ | ------- | ------- | ------------------- | ------------------- |
| advisor-product-design   | keep    | persona | 0 files; 2026-07-23 | actively maintained |
| advisor-product-strategy | keep    | persona | 0 files; 2026-07-23 | distinct remit      |

## Adjudication log (owner rulings, 2026-08-08)

1. **Retires approved (3):** setup-pre-commit, skill-inventory, vault-upgrade — all on
   structural arguments (abandoned / audits a dead model / target pipeline deleted).
2. **Consolidations approved (3):** land-skill-candidate → workshop-skill-creator
   (intake mode); vault-link → vault-connect (`--term` mode); prd-to-plan →
   prd-to-issues (`--plan` output mode, final slug decided in Phase 2).
3. **Relocation approved (1):** persona-builder → workbench (planning-shaping bucket).
4. **Keep-both arguments accepted wholesale** for every remaining named overlap set —
   the merge default forced arguments and the arguments held; one claimed overlap
   (mr-review-fixes / vault-mr-review-packet) was proven false by source reading.
5. **walkthrough vs vault-mr-review-packet:** both kept; Phase 2 adds a one-line
   cross-reference boundary to each (written packet vs interactive explainer).

**Net result:** 79 graded → 72 keep (1 absorbing), 3 retire, 3 consolidate,
1 relocate. Final shipped-skill count after Phase 2: **73** across workbench (67),
workshop-maintainer (4), advisors (2), plus 5 persona plugins with no skills.
