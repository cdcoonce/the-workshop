---
name: live-view-simulate-diff
description: >
  Simulates a proposed change to a live Snowflake view read-only and diffs it
  against the deployed output with float tolerance. Use when a view has no
  committed source (co-edited in the UI) and must be verified before a
  role-gated manual deploy.
---

# Live view simulate-and-diff

Some views have no committed source: teammates co-edit them in the Snowflake
UI, so the deployed definition is the only baseline and it moves without
notice. Any saved DDL copy is already stale. This skill verifies a proposed
change against the live deployment, read-only, and hands the human a guarded
worksheet to deploy under their own role. It never writes to the warehouse.

The naive check — MINUS the simulated output against the live output — fails
two ways: re-evaluating the same view can move the last bit of a float
(parallel SUM ordering), flooding the diff with phantom rows, and MINUS
cannot tell a changed value from an added-plus-removed pair. The harness
diffs on the declared key with a relative tolerance instead.

## Run it

Write a JSON spec next to the SQL it verifies (full schema and a worked
example: [references/spec.md](references/spec.md)):

```json
{
  "env_prefix": "SNOWFLAKE_",
  "views": [
    {
      "fqn": "DB.SCHEMA.MY_VIEW",
      "proposed_sql": "proposed/my_view.sql",
      "key": ["YEAR_MONTH", "SITE", "ATTRIBUTE"],
      "value_columns": ["VALUE"],
      "checks": [
        { "label": "identity", "sql": "SELECT * FROM DB.SCHEMA.MY_VIEW WHERE ABS(rate * gen - dollars) > 1e-6" }
      ]
    }
  ]
}
```

```bash
uv run "<skill base directory>/scripts/sim_diff.py" spec.json
```

`proposed_sql` is the full `CREATE OR REPLACE VIEW` file — the same file that
will deploy, so the simulated body and the worksheet cannot drift apart.

## What a run does

1. Fetches the live DDL fresh with `GET_DDL` and records its SHA-256.
2. Runs the proposed body as a derived table over live data, substituting
   qualified references — a CTE cannot shadow `db.schema.table`, so shadow
   patches and chained upstream bodies are spliced in textually. Refuses
   (exit 2) if any write verb appears in the executable text.
3. Diffs baseline vs simulation on the declared key into four buckets:
   added, removed, changed beyond tolerance, and float noise (within
   relative 1e-9 — counted, never listed as change).
4. Gates on new duplicate keys (legacy duplicates stay tolerated) and runs
   each `checks` entry, which must return zero rows; inside a check, the
   view's FQN resolves to the simulated body, not the live view.
5. Writes `evidence.json` (DDL hashes, buckets, worst residual, check
   results) and a `worksheet_N.sql` per proposed view.

Exit 0 clean or noise-only · 1 findings · 2 refused (bad spec, write verb,
missing environment).

## Check the blast radius

A co-edited upstream can silently kill a consumer — a downstream pivot whose
columns reference attributes the rewritten view no longer emits renders NULL
with no error anywhere. List downstream views in the spec **without**
`proposed_sql`: the harness simulates the live downstream body over the
proposed upstream and diffs it, so consumer breakage shows up as removed or
changed rows before anyone deploys.

## Deploying

The worksheet opens with `SELECT SHA2(GET_DDL(...), 256)` and the expected
hash: if the live view moved after the simulation, the hash mismatches and
the human stops. Simulation is cheap — on a mismatch, re-run it; never
deploy through a failed guard.

## Boundaries

- Committed DDL that should compile against the live schema: use
  `sql-deploy-precheck`. Committed SQL that needs executing tests offline:
  use `warehouse-sql-test-harness`. This skill is for views where live IS
  the source.
- The diff is client-side and meant for mart-scale views; scope big ones
  with each view's `where` filter.
- Credentials come from `<env_prefix>ACCOUNT/USER/WAREHOUSE` plus
  `PRIVATE_KEY` (or `PASSWORD`); see the spec reference. The harness never
  prints credential values.
