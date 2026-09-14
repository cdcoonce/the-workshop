---
name: data-discovery
description: >
  Generates a data discovery doc for a Snowflake schema or dbt project: table
  inventory, coverage, ER diagram, and runnable queries. Use when onboarding to a
  dataset or asking what data exists. Not dbt structure — use dbt-manifest-facts.
---

# Data Discovery

Generate a handoff-ready data discovery document from a Snowflake schema or dbt project.

The document is reference-mode. When it is committed into a repository's `docs/`, its placement and provenance footer belong to `repo-docs`; this skill only produces the content.

## Required Reading

1. Read [command.md](references/command.md) for the full workflow.
2. Read [output-template.md](references/output-template.md) for the output structure.
3. Read [profiling-queries.md](references/profiling-queries.md) for reusable SQL patterns.

## Execution

Follow the command reference exactly. The skill produces a single markdown file — never multiple files, never inline-only output.
