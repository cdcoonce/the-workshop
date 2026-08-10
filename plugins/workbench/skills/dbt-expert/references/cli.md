# dbt CLI Commands

Reference for dbt Core CLI commands, selection syntax, graph operators, and common flags.

## Core Commands

| Command | Purpose |
|---------|---------|
| `dbt build` | **(preferred)** Run models, tests, snapshots, seeds in DAG order |
| `dbt run` | Materialize models only (no tests) |
| `dbt test` | Run tests only (generic, unit, custom) |
| `dbt show` | Compile and run a query, print results — nothing materialized |
| `dbt compile` | Compile Jinja/SQL without executing, output to `target/compiled/` |
| `dbt debug` | Validate project config, profiles.yml, and warehouse connectivity |
| `dbt seed` | Load CSVs from `seeds/` into the warehouse |
| `dbt snapshot` | Run SCD Type 2 snapshot models |
| `dbt docs generate` | Build documentation from descriptions, tests, and DAG |
| `dbt docs serve` | Start local server to browse generated docs |

### dbt build

The preferred command — runs models and tests in DAG order so each model is tested immediately after materialization.

```bash
dbt build
dbt build --select my_model+
```

### dbt show

Use for quick validation without materializing. Supports inline SQL.

```bash
dbt show --select my_model --limit 50
dbt show --inline "select * from {{ ref('stg_orders') }} limit 10"
```

### dbt compile

Inspect the generated SQL dbt will send to the warehouse.

```bash
dbt compile --select my_model
```

### dbt debug

Run first when setting up a new environment or troubleshooting connection issues.

## Selection Syntax

Use `--select` (or `-s`) to target nodes and `--exclude` to skip them.

```bash
dbt build --select my_model                  # single model
dbt build --select model_a model_b           # multiple models
dbt build --select tag:daily                 # by tag
dbt build --select path:models/staging       # by directory
dbt build --select resource_type:model       # by resource type
dbt build --exclude my_slow_model            # skip a model
dbt build --select tag:daily --exclude stg_legacy__events
```

## Graph Operators

Expand selection along the DAG.

| Operator | Meaning | Example |
|----------|---------|---------|
| `+model` | Model and all upstream ancestors | `--select +fct_orders` |
| `model+` | Model and all downstream dependents | `--select stg_orders+` |
| `+model+` | Full lineage (up and down) | `--select +fct_orders+` |
| `@model` | Model, its parents, and its children | `--select @fct_orders` |

The `@` operator is useful for CI: it covers the model, everything it depends on, and everything that depends on it.

## Common Flags

| Flag | Purpose | Example |
|------|---------|---------|
| `--full-refresh` | Rebuild incremental models from scratch | `dbt build --full-refresh` |
| `--target` | Override default target from profiles.yml | `dbt build --target prod` |
| `--vars` | Pass variables for `{{ var('key') }}` | `dbt build --vars '{"start_date": "2024-01-01"}'` |
| `--threads` | Control parallelism | `dbt build --threads 8` |
| `--quiet` / `-q` | Suppress non-essential output (CI-friendly) | `dbt build -q` |

## dbt Core vs Fusion

dbt Core is the open-source CLI (`dbt`). dbt Fusion (`dbtf`) is an alternative high-performance engine. Fusion is not required — all commands documented here work with standard dbt Core. If Fusion is installed, replace `dbt` with `dbtf` in commands.
