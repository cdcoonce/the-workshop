# SQL, dbt and Snowflake Checks

Apply when the diff touches SQL, dbt models or macros, Snowflake connector or Snowpark code, Dagster assets that query Snowflake, or warehouse, role and grant DDL. Review changed hunks and their model YAML.

Sources: Snowflake Well-Architected Framework ([Performance](https://www.snowflake.com/en/developers/guides/well-architected-framework-performance/), [Security and Governance](https://www.snowflake.com/en/developers/guides/well-architected-framework-security-and-governance/)) and dbt's [project structure guide](https://docs.getdbt.com/best-practices/how-we-structure/1-guide-overview). When a finding depends on version-specific behavior or exact syntax, confirm it against current Snowflake documentation before reporting and link the page.

## Deterministic

The `sqlfluff` check in `branch_checks.py` lints changed `.sql` files.

- A repo SQLFluff config wins; without one the `snowflake` dialect is used.
- Lint findings are Minor. Report them, not personal style preferences.
- Files that failed templating or parsing are named in the check's `reason` and its status is `error`: the SQL verdict is then Incomplete, never an approval.
- If the repo's config requires the dbt templater, it needs a profile that may connect to the warehouse. Ask before running it; otherwise record "not run".
- `dbt parse` validates Jinja and YAML without a warehouse connection. Run `uv run dbt parse` only when dbt is a project dependency and the execution gate in [targets-and-output.md](targets-and-output.md) passes. Never run `dbt compile`, `run`, `build` or `test` without an explicit yes and a non-production target.

## Query design

- `SELECT *` in production code: name the columns needed. It scans more data and breaks silently when columns change.
- Joins: prefer equality conditions; flag `OR` inside join conditions and joins on expressions that block pruning.
- Prefer window functions over self-joins; remove sorts nothing consumes.
- Filters on large tables hit columns the table is clustered or naturally ordered on, so micro-partition pruning works. Flag functions wrapped around filter columns (`WHERE DATE(ts) = ...` instead of a range on `ts`).
- Heavy views stacked on views: ask whether a table or materialization is warranted.

## Warehouse and cost

Performance is a recurring credit cost; the stance is "as fast as necessary", not "as fast as possible".

- Many small queries in a loop where one set-based statement works: Major.
- Hard-coded warehouse names or sizes in application code instead of configuration; upsizing a warehouse as the fix for a bad query.
- Warehouse DDL: `AUTO_SUSPEND` set deliberately; multi-cluster only when concurrency needs it.
- New clustering keys are justified by a large table and frequently filtered columns, since automatic clustering has its own cost.
- Long-running queries without a timeout in application code.

## Loading and writing data

- Bulk paths (`COPY INTO` from a stage, `write_pandas`, a single `INSERT ... SELECT`) instead of row-by-row `INSERT` in a loop.
- Idempotent writes: `MERGE` or delete-then-insert in one transaction, so a rerun does not duplicate rows.
- `CREATE OR REPLACE TABLE` on an existing table: the new table does not inherit the old table's explicit grants unless `COPY GRANTS` (or the equivalent `COPY = ( GRANTS )`) is specified; future grants on the schema still apply. Flag it on tables other roles use, and check the CREATE reference for views and other objects. Source: [CREATE TABLE](https://docs.snowflake.com/en/sql-reference/sql/create-table).
- Dropping or renaming columns and tables in the same change that stops using them: split into sequential deployments.
- Dynamic object names built by string concatenation: use `IDENTIFIER()`; values go through bind variables. In the Python connector, avoid Python string formatting for values and prefer server-side `qmark` or `numeric` binding; `executemany()` takes a list of parameter sets, and larger loads belong in staged files with `COPY INTO`. Source: [Using the Python Connector](https://docs.snowflake.com/en/user-guide/python-connector-example).

## Security and access

- Least privilege: application code does not run as `ACCOUNTADMIN` or `SECURITYADMIN`, and does not need `SYSADMIN` just to read tables. Grants go to roles, not directly to users.
- Service accounts authenticate with key pair, OAuth or SAML-based flows, not passwords; no credentials in code, notebooks or CI files.
- New roles, grants or network-policy changes match what the code actually uses, nothing broader.
- Sensitive columns (PII, financial): masking or row access policies, and not copied into logs, query tags or external stages.
- Writes to external stages or other outbound paths: confirm the destination is intended and access-controlled.

## dbt models

- Layering: staging (source-conformed, one model per source table, light cleanup and renames) feeds intermediate models, which feed marts (business-conformed). Each transformation lives in one place.
- Relations use `ref()` / `source()`, never a hard-coded `database.schema.table`. Major; a Blocker when the model would break or duplicate rows.
- New models have descriptions, and tests on the grain key (`unique`, `not_null`), on join keys, and on relationships where relevant, in the YAML next to the model. Missing tests are Major; a missing description is Minor.
- Incremental models define `unique_key` and an `is_incremental()` filter, and handle late-arriving data deliberately.
- Materialization matches use: views for light staging, tables or incremental for expensive or widely used models.

## Defer

Deep modelling, testing, snapshot, or materialization questions go to `dbt-expert`; do not re-derive its guidance. Dagster asset, sensor and schedule patterns go to `dagster-expert`.
