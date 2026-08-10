# Database / Data Model Walkthrough

## What to Explain

A database walkthrough builds understanding of how data is structured, how entities relate, and how data flows through the system.

## Overview Phase

Generate a visual showing:
- **Entity-Relationship Diagram** — tables as nodes, foreign keys as edges, cardinality annotated
- **Schema grouping** — tables grouped by domain/schema/functional area
- **Data flow direction** — source tables → staging → marts → consumption (if a warehouse pattern)

Best diagram type: **Mermaid ER diagram** for schemas under ~15 tables. **D3 force-directed graph** for larger schemas with tables as nodes, colored by schema/domain, edges showing FK relationships with cardinality labels.

## Drill-Down Sections

1. **Core entities** — the most important tables, what they represent, how they're keyed
2. **Relationships & joins** — how tables connect, common join patterns, many-to-many resolution
3. **Data lineage** — where data comes from, how it's transformed, what feeds what
4. **Naming conventions & patterns** — prefixes, suffixes, type columns, soft deletes, audit columns
5. **Data quality & constraints** — what's enforced (PKs, FKs, NOT NULL), what's assumed, known gaps
6. **Query patterns** — common access paths, how consumers typically query this model

## Exploration Strategy

- Run `SHOW SCHEMAS`, `SHOW TABLES`, `DESCRIBE TABLE` to discover structure.
- Check for documentation tables, data dictionaries, or README files.
- Look at column names for FK patterns (e.g., `*_id`, `*_key`).
- Examine row counts and column types to understand scale and data types.
- Check for views/materialized views that reveal common query patterns.
- Look for dbt models, semantic views, or other transformation layers.

## Visual Updates on Drill-Down

- **Core entities** → focused ERD of just the central tables with column detail
- **Relationships** → join diagram with cardinality and join conditions annotated
- **Data lineage** → DAG-style flow diagram (Mermaid flowchart or D3 Sankey)
- **Query patterns** → annotated SQL examples with visual highlighting of join paths
