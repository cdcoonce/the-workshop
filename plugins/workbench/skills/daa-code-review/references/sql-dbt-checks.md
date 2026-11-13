# SQL and dbt Checks

Review only changed `.sql` hunks (and their model YAML).

## Deterministic

Run `uvx sqlfluff lint --format json <paths>`.

- If `dbt_project.yml` exists at the repo root, use the dbt templater.
- Otherwise use the `snowflake` dialect.
- A repo `.sqlfluff` wins over both defaults; do not override it.
- If `uvx` or sqlfluff fails to run, report that; never report SQL clean on a tool failure.

## Judgment checklist

- Relations use `ref()` / `source()`, not hardcoded database.schema.table names.
- `unique` and `not_null` tests exist on the grain key.
- Join keys are tested.
- Incremental models set `unique_key`.
- Materialization fits the model (view/table/incremental/ephemeral for its size and use).
- No `select *` in marts.

Hardcoded relations and missing grain tests are should-fix; blocking only when the model would break or duplicate rows.

## Defer

Deep modelling, testing, snapshot, or materialization questions go to `dbt-expert`; do not re-derive its guidance. Dagster asset, sensor and schedule patterns go to `dagster-expert`.
