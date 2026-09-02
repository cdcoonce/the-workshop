---
name: data-discovery
description: >
  Generate a handoff-ready data discovery document for a Snowflake schema or dbt project.
  Produces a single markdown file with table inventory, coverage summary, Mermaid relationship
  diagram, and runnable discovery queries with plain English headers. Adaptive depth for
  engineers or analysts. Use when: onboarding someone to a dataset, documenting available data,
  creating a data walkthrough, exploring what's in a schema. Triggers: data discovery, discover
  data, what data is available, document this schema, data walkthrough, schema handoff,
  onboard to dataset, what tables exist, explore this data.
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
