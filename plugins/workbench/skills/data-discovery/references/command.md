# /data-discovery — Generate a Data Discovery Document

## When to run

- User says "discover the data in [schema/repo]", "what data is available", "create a data walkthrough", or triggers `/data-discovery`.
- User wants to onboard someone to a dataset or document what's in a schema.
- NOT for writing queries against the data (that's `sql-author`) or for building models (that's `dbt-expert`).

## Procedure

### 1. Gather input

Determine the input mode by checking what the user provided or what's available:

1. **dbt project** (preferred): Detect `dbt_project.yml` in the working directory or a user-specified path. If found, use this mode.
2. **Snowflake schema** (fallback): User provides a `DATABASE.SCHEMA` path, or no dbt project is detected but a Snowflake connection is available.
3. **Explicit table list**: User provides specific tables to document.

### 2. Ask setup questions

Before generating, ask the user three questions via `AskUserQuestion`:

```json
{
  "questions": [
    {
      "header": "Audience",
      "question": "Who will read this discovery doc?",
      "options": [
        {"label": "Engineers (Recommended)", "description": "Full schema detail, JOIN logic, identity resolution notes, technical column descriptions."},
        {"label": "Analysts / business users", "description": "Plain English descriptions, simpler queries, business context over schema detail."}
      ]
    },
    {
      "header": "Layers",
      "question": "Which data layers should the doc cover?",
      "options": [
        {"label": "Marts only (Recommended)", "description": "Just the consumption layer — the tables people should query."},
        {"label": "Full lineage", "description": "Raw → staging → marts. Shows where data comes from and how it transforms."},
        {"label": "Raw + marts", "description": "Source tables and final marts, skip intermediate staging."}
      ]
    },
    {
      "header": "Profiling",
      "question": "Run live profiling queries against Snowflake? (Gets row counts, distinct values, date ranges from the actual data.)",
      "options": [
        {"label": "Yes (Recommended)", "description": "Richer output with real numbers. Requires warehouse access."},
        {"label": "No — metadata only", "description": "Use dbt yml / INFORMATION_SCHEMA only. Faster, no warehouse needed."}
      ]
    }
  ]
}
```

### 3. Gather metadata

Based on input mode:

#### dbt project mode

1. Read `dbt_project.yml` for project name, target schema, and model paths.
2. Read `schema.yml` files (or `_models.yml` / `_sources.yml`) for:
   - Model/table descriptions
   - Column names, types, and descriptions
   - Tests (unique, not_null, accepted_values — these reveal data constraints)
   - Declared relationships
3. Read model SQL files to infer:
   - JOIN relationships (look for `JOIN ... ON` and `{{ ref('...') }}`)
   - Key transformations (CTEs, CASE statements, aggregations)
4. If `manifest.json` exists (compiled): read for the full DAG and column-level lineage.

#### Snowflake schema mode

1. Run `SHOW TABLES IN <DATABASE.SCHEMA>` to get the table list with row counts.
2. Run `DESCRIBE TABLE` for each table to get columns and types.
3. Run `SHOW VIEWS IN <DATABASE.SCHEMA>` to capture views.
4. Infer relationships from naming conventions (FK patterns, shared column names across tables).

#### Fallback (sparse dbt — no schema.yml)

Use Snowflake DESCRIBE against the target schema. Warn the user output will be sparser without yml descriptions.

### 4. Run live profiling (if enabled)

For each table in scope, run profiling queries from [profiling-queries.md](profiling-queries.md):

- Row count
- Date range (MIN/MAX on date/timestamp columns)
- Distinct value counts for categorical columns (VARCHAR columns with < 50 distinct values)
- Freshness (MAX of timestamp columns)
- Source/category breakdowns (GROUP BY on key dimensions)

Batch queries where possible to minimize warehouse usage. Use `INFORMATION_SCHEMA.COLUMNS` to identify which columns to profile.

### 5. Infer relationships

Build a relationship map for the Mermaid diagram:

1. **Declared relationships** (from schema.yml `relationships:` blocks) — highest confidence.
2. **ref() calls** in dbt model SQL — high confidence.
3. **JOIN clauses** in model SQL — medium confidence (note the join keys).
4. **Shared column names** across tables (e.g., `project_identity_key` appearing in multiple tables) — lower confidence, mark as inferred.

### 6. Generate the document

Write a single markdown file following the [output-template.md](output-template.md) structure. Adapt voice based on the audience answer:

- **Engineer audience**: Include column types, identity resolution notes, join keys, technical caveats, and raw SQL.
- **Analyst audience**: Lead with business meaning, use plain English headers, include SQL but annotate what each query answers in non-technical terms.

### 7. Ask where to save

```json
{
  "questions": [
    {
      "header": "Output path",
      "question": "Where should I save the discovery doc?",
      "type": "text",
      "defaultValue": "<inferred-path-based-on-context>.md"
    }
  ]
}
```

Default path inference:
- If in a dbt project: `docs/data-discovery.md`
- If user specified a schema: suggest a descriptive name based on the schema
- If in a vault: `work/active/<project>/data-discovery.md`

### 8. Write and report

Write the file and report:
- File path
- Table count documented
- Whether live profiling was included
- Any gaps (tables without descriptions, unresolved relationships)

## Constraints

- **Single file output.** Never produce multiple files or inline-only output.
- **Runnable SQL.** Every query in the doc must use fully qualified table names and be copy-paste executable.
- **No fabrication.** Row counts, date ranges, and distinct values come from live queries or are omitted. Never estimate.
- **Respect warehouse budget.** Profiling queries should be lightweight (no full table scans on large tables — use TABLESAMPLE or LIMIT for expensive operations).
- **Mermaid must render.** Test that the generated Mermaid syntax is valid (no unescaped special characters in labels, correct arrow syntax).
