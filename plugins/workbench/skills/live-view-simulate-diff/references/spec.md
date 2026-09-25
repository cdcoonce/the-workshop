# Run spec reference

The spec is a JSON file. Paths are relative to the spec file's directory, so
commit the spec next to the SQL it verifies.

## Top-level fields

| Field           | Required | Default        | Meaning                                                                |
| --------------- | -------- | -------------- | ---------------------------------------------------------------------- |
| `views`         | yes      | —              | Views to simulate and diff, in order                                   |
| `shadow_tables` | no       | `{}`           | `{ "DB.SCHEMA.TABLE": "patch.sql" }` — substitute a patched base table |
| `rel_tol`       | no       | `1e-9`         | Relative tolerance separating float noise from a real change           |
| `abs_tol`       | no       | `1e-12`        | Absolute floor for values near zero                                    |
| `env_prefix`    | no       | `"SNOWFLAKE_"` | Prefix for connection environment variables                            |
| `out_dir`       | no       | `sim_diff_out` | Where `evidence.json` and worksheets land, relative to the spec        |

At least one view needs `proposed_sql`, or `shadow_tables` must be non-empty —
otherwise there is nothing to simulate and the harness refuses (exit 2).

## Per-view fields

| Field           | Required | Meaning                                                                                  |
| --------------- | -------- | ---------------------------------------------------------------------------------------- |
| `fqn`           | yes      | Fully qualified view name, e.g. `DEV_ANALYTICS_DB.REVENUE_WATERFALL.BUDGET_MONTHLY`      |
| `key`           | yes      | Columns forming the declared grain; the diff and duplicate-key gate run on this          |
| `value_columns` | yes      | Columns compared under tolerance                                                         |
| `proposed_sql`  | no       | Full `CREATE OR REPLACE VIEW` file. Omit to diff a downstream consumer of another change |
| `where`         | no       | Filter applied to both baseline and simulation — scope large views                       |
| `checks`        | no       | List of `{ "label", "sql" }`; each must return zero rows to pass                         |

A view **without** `proposed_sql` is a blast-radius probe: the harness pulls
its live body with `GET_DDL`, substitutes the proposed upstream bodies and
shadow patches into it, and diffs that against the live output. A consumer
whose columns go dead shows up as removed or changed rows.

## Substitution semantics

- References are matched fully qualified (`db.schema.table`), case-insensitive
  for unquoted segments, exact-case for `"QUOTED"` segments, never inside
  comments or string literals, and never as part of a longer name.
- Substitution is recursive so chains compose: a downstream body receives the
  proposed upstream body, which receives the shadow patch.
- A patch body that reads its own table keeps reading the real table — the
  reference it replaces is excluded from its own expansion. A virtual-delete
  patch (`SELECT * FROM t WHERE NOT <bad rows>`) therefore works as written.
- Inside a `checks` entry, the view's own FQN resolves to the simulated body.

## Connection environment

With the default prefix (`SNOWFLAKE_`):

| Variable                                     | Required            |
| -------------------------------------------- | ------------------- |
| `SNOWFLAKE_ACCOUNT` / `_USER` / `_WAREHOUSE` | yes                 |
| `SNOWFLAKE_PRIVATE_KEY` (PEM text)           | this or `_PASSWORD` |
| `SNOWFLAKE_PRIVATE_KEY_PASSPHRASE`           | no                  |
| `SNOWFLAKE_DATABASE` / `_SCHEMA` / `_ROLE`   | no                  |

Set `env_prefix` to reuse a repo's existing variables (for example
`MERCHANT_REV_SNOWFLAKE_`).

## Worked example

Upstream mart gets a patched base table and a proposed rewrite; the variance
view downstream is probed for fallout; two invariants gate the run.

```json
{
  "env_prefix": "MERCHANT_REV_SNOWFLAKE_",
  "shadow_tables": {
    "DEV_RAW_DB.FUNDAMENTAL_CURVES.BUDGETS": "patches/budgets_virtual_delete.sql"
  },
  "views": [
    {
      "fqn": "DEV_ANALYTICS_DB.REVENUE_WATERFALL.BUDGET_MONTHLY",
      "proposed_sql": "proposed/budget_monthly.sql",
      "key": ["YEAR_MONTH", "SITE", "CONTRACT", "ATTRIBUTE"],
      "value_columns": ["VALUE"],
      "checks": [
        {
          "label": "paired-unit identity",
          "sql": "WITH r AS (SELECT year_month, site, contract, MAX(CASE WHEN attribute = 'total_revenue_$/mwh' THEN value END) AS rate, MAX(CASE WHEN attribute = 'net_generation_mwh' THEN value END) AS gen, MAX(CASE WHEN attribute = 'total_revenue_$' THEN value END) AS dollars FROM DEV_ANALYTICS_DB.REVENUE_WATERFALL.BUDGET_MONTHLY GROUP BY 1, 2, 3) SELECT * FROM r WHERE ABS(rate * gen - dollars) > 1e-6"
        }
      ]
    },
    {
      "fqn": "DEV_ANALYTICS_DB.REVENUE_WATERFALL.REVENUE_VARIANCE_MONTHLY",
      "key": ["YEAR_MONTH", "SITE", "CONTRACT", "ATTRIBUTE"],
      "value_columns": ["VALUE"]
    }
  ]
}
```

## Outputs

- `evidence.json` — timestamp, tolerances, and per view: `ddl_sha256`, row
  counts, `buckets` (added / removed / changed / noise), capped samples,
  `new_duplicate_keys`, check results, worst residual, verdict.
- `worksheet_N.sql` — per proposed view: the SHA2 baseline guard with the
  expected hash, followed by the proposed file verbatim. Paste into a
  Snowflake worksheet; run the guard; deploy only on a hash match.
