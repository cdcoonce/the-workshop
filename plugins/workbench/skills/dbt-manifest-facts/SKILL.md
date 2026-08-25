---
name: dbt-manifest-facts
description: Answers structural questions about a dbt project from its parsed manifest.json rather
  than from model comments, README prose, or memory. Use when stating or checking how many
  models, tests, seeds, or marts a project has; when documenting or auditing a dbt repo;
  when asking which models a seed or source actually feeds, or what a model really depends
  on; when hunting for seeds and models that nothing references; when confirming what key
  or grain a model declares; or when a claim about a dbt project's structure needs evidence
  behind it.
---

# dbt manifest facts

A dbt project has two descriptions of itself: what its comments and docs say,
and what its manifest declares. Only the second is checkable. Every count, key,
and edge you report should come from the manifest.

## Build a manifest

```bash
dbt parse --project-dir <dir> --profiles-dir <dir>
```

`dbt parse` — not `dbt docs generate` — is the cheap path, and it needs **no
warehouse connection** when the profile's `env_var()` calls carry defaults.
Assuming a live connection is required is the usual reason people answer from
prose instead. The manifest lands at `<project>/target/manifest.json`.

## Ask it

```bash
python scripts/manifest_facts.py <command> [target] --project-dir <dir>
```

| Command          | Answers                                                     |
| ---------------- | ----------------------------------------------------------- |
| `summary`        | resource counts, materializations, tests broken out by type |
| `orphans`        | seeds, models, and sources that no model consumes           |
| `keys [model]`   | the uniqueness a model actually declares                    |
| `lineage <node>` | the real parents and children of one node                   |

Add `--json` for machine-readable output. `orphans` exits **1** when it finds
something, so it works as a CI gate.

## What each one is for

**`summary`** settles any "there are N models/tests/marts" claim. It also
surfaces the odd one out — a lone `incremental` among tables is the single
place a project's "everything rebuilds" assumption breaks.

**`orphans`** catches the resource that is fully typed, documented, and tested
but referenced by nothing. dbt does not treat this as an error, so nothing
fails and nobody notices. Read the output with judgement: a terminal mart has
no model children by design and is listed too — the question it asks is
"confirm something outside the project consumes this," not "delete it."

**`keys`** answers what grain a model is really on. A `unique` on a surrogate
key says nothing about the tuple a consumer joins on, so single-column and
combination forms are reported separately. A model with neither is flagged.

**`lineage`** replaces "X reads Y" from a comment with the edges dbt resolved.
Tests are excluded from children — counting them makes every tested model look
like it has a consumer.

## A stale manifest is worse than none

It answers everything confidently, about a project that has since moved on. The
script compares the manifest's mtime against the project's `.sql`/`.yml`/`.csv`
files and **refuses to report** when it is behind, listing what changed. Re-run
`dbt parse`; use `--allow-stale` only when you have decided the drift is
irrelevant and can say why.

Two more limits worth stating before quoting a number:

- The manifest describes the **checked-out branch**, not `main`. Pin the branch
  before treating a count as the project's current state.
- It describes what the project **declares**, never what the warehouse holds. A
  column added by hand, or a mart built from an older model, is invisible here.

## Boundaries

- Authoring dbt — models, tests, materializations, CLI usage — is
  `dbt-expert`. This skill reads a project; it does not write one.
- Profiling actual data (row counts, distributions, coverage) is
  `data-discovery`. Nothing here touches the warehouse.
- Comparing committed SQL against a live schema is `sql-deploy-precheck`.
  Manifest-vs-warehouse drift is that skill's question, not this one's.
