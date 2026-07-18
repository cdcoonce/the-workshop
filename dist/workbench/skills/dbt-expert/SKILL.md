---
name: dbt-expert
description:
  Expert guidance for working with dbt Core. ALWAYS use before doing any task that requires
  knowledge specific to dbt, including building or modifying models, writing SQL transformations,
  configuring tests, running dbt CLI commands, or working with dbt project structure.
  Common triggers include references to dbt, models, ref(), source(), materializations,
  seeds, snapshots, dbt build/run/test, YAML schema files, or analytics engineering patterns.
---

## Core dbt Concepts

Brief definitions only (see reference files for detailed examples):

- **Model**: A SQL SELECT statement (stored as a `.sql` file) that dbt materializes into a view, table, or incremental object in the warehouse
- **Source**: A declaration of raw tables already in the warehouse, referenced via `{{ source('schema', 'table') }}`
- **ref()**: The function used to reference other models — `{{ ref('model_name') }}` — which builds the DAG and handles schema resolution
- **Test**: An assertion about your data. Generic tests (unique, not_null, accepted_values, relationships) are declared in YAML; custom tests are SQL queries that return failing rows
- **Seed**: A CSV file in your dbt project that gets loaded into the warehouse via `dbt seed`
- **Snapshot**: A model that captures slowly changing dimension (SCD Type 2) history using `dbt snapshot`

## CLI Overview

dbt Core is invoked via the `dbt` CLI. Key commands:

- **`dbt build`** — The preferred command. Runs models, tests, snapshots, and seeds in DAG order.
- **`dbt run`** — Materializes models only (no tests).
- **`dbt test`** — Runs tests only.
- **`dbt show`** — Compiles and runs a model/query, printing results to the terminal. Use for quick validation without materializing.
- **`dbt compile`** — Compiles SQL without executing. Useful for inspecting generated SQL.
- **`dbt debug`** — Validates project configuration and warehouse connectivity.

### Selection syntax

Use `--select` and `--exclude` to target specific nodes:

```bash
dbt build --select my_model           # single model
dbt build --select my_model+          # model and all downstream
dbt build --select +my_model          # model and all upstream
dbt build --select +my_model+         # model with full lineage
dbt build --select tag:daily          # all nodes with a tag
dbt build --exclude my_model          # everything except this model
```

## CRITICAL: Always Read Reference Files Before Answering

NEVER answer from memory or guess at dbt syntax, YAML schema, or CLI flags. ALWAYS read the relevant reference file(s) from the Reference Index below before responding.

For every question, identify which reference file(s) are relevant using the index descriptions, read them, then answer based on what you read.

## Reference Index

<!-- BEGIN GENERATED INDEX -->

- [Modeling Patterns](./references/modeling.md) — model types, materializations, ref/source, DAG organization, naming conventions, Jinja patterns
- [Testing](./references/testing.md) — generic tests, unit tests, custom tests, test YAML format, severity levels
- [CLI Commands](./references/cli.md) — dbt build, run, test, show, compile, debug; selection syntax, graph operators
- [Documentation](./references/docs.md) — dbt docs generate, dbt docs serve, llms.txt, markdown URL convention

<!-- END GENERATED INDEX -->
