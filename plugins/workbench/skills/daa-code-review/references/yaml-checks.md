# YAML Checks

Review only changed `.yml` / `.yaml` hunks.

## Parse check

Run `yaml.safe_load` on each changed file (`python -c` or `uv run --with pyyaml`). A parse error is blocking and reported with its line. Use `safe_load_all` for multi-document files.

## dbt schema files

- Every model in the diff is documented (`description`) and tested.
- Grain key has `unique` and `not_null`; see [sql-dbt-checks.md](sql-dbt-checks.md).
- Columns added in the model SQL appear in the YAML when the repo documents columns.

Missing docs or tests are should-fix.

## CI files

- Every job has explicit `rules` (or `only`/`except`) with branch scope; nothing deploys from an unscoped job.
- Deploy and release jobs are limited to the intended protected branches.
- Rule changes that widen a job's branch scope are blocking unless justified in the diff.
