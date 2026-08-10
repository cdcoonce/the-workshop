# Doc templates

Layouts for each file in the `docs/reference/` set. These are starting shapes,
not rigid forms — adapt headings to the repo, drop sections that do not apply,
and never pad. Every doc ends with the provenance footer.

Keep prose for humans: short paragraphs, concrete nouns from the codebase,
"why" alongside "what". Use tables for enumerable facts and Mermaid only where a
picture beats a list.

---

## Provenance footer (every doc)

The last line of every doc is an HTML comment the updater and
`scripts/check_docs.py` both parse:

```
<!-- repo-reference-docs: baseline=<commit-sha> covers=<comma,separated,paths> -->
```

- `baseline` — the commit the doc was last synced to (`git rev-parse HEAD` at
  write time).
- `covers` — the source paths this doc is derived from, relative to repo root.
  List directories for broad docs (`src/api`) and files for specific ones
  (`src/api/router.py`). These drive incremental updates and staleness checks,
  so keep them accurate.

---

## README.md (index)

```markdown
# Reference docs

How this repository works, for engineers onboarding to it.

Suggested reading order:

1. [Architecture](architecture.md) — the big picture.
2. [Module map](module-map.md) — where each piece lives.
3. [Data & control flow](data-flow.md) — how it runs end to end.
4. [Conventions & glossary](conventions.md) — patterns and terms.

_Generated and maintained by the `repo-reference-docs` skill._
```

Note any doc intentionally omitted and why.

---

## architecture.md

- **What this repo is** — one paragraph: purpose and the problem it solves.
- **Major components** — the handful of top-level parts and each one's job.
- **How they fit** — a Mermaid `graph`/`flowchart` of components and their
  dependencies, followed by prose on the important edges.
- **Entry points** — where execution starts (CLI, server, jobs, `__main__`).
- **External dependencies** — services, APIs, datastores the system relies on.

---

## module-map.md

One section per top-level package/directory. A table works well:

| Directory | Responsibility | Key files | Public surface |
| --------- | -------------- | --------- | -------------- |

Follow each row with a sentence or two on anything non-obvious — why it exists,
what it must not do, where its responsibility ends.

---

## data-flow.md

- **Primary flows** — for each major operation, trace input → transformation →
  output across components.
- **Sequences** — a Mermaid `sequenceDiagram` for the one or two flows that
  matter most.
- **State** — where state lives, what is persisted vs cached vs derived.
- **Integrity constraints** — invariants that must hold across the flow.

---

## conventions.md

- **Naming** — file, symbol, and branch conventions actually used here.
- **Patterns** — recurring structures a newcomer will meet (error handling,
  config, testing) with a pointer to one canonical example in the code.
- **Glossary** — domain terms and acronyms, defined plainly.

---

## schema.md (optional, database repos)

Only when the repo declares a database schema. Layout:

- **What this schema is** — one paragraph, plus links to the DDL and any data
  dictionary.
- **Reading the model** — the two or three facts that explain its shape (grain
  splits, derived vs authored tables, append-only-ness).
- **Entities** — a Mermaid `erDiagram` plus an entity/grain/PK/natural-key table.
- **View dependencies** — a Mermaid `flowchart` DAG plus a view/reads/use-it-for
  table per group.
- **Common queries** — a few real ones, and the traps they avoid.
- **Verifying against the live database** — catalog queries a human can run, and
  a statement that they do not run in CI.
- **Regenerating this page** — only if it is generated.

Generate the two diagram sections from the DDL when the repo qualifies; see
[generated-erd.md](generated-erd.md) for the generator, marker injection, and
drift tests. The provenance footer goes outside the generated markers.

---

## Mermaid guidance

- Use `flowchart`/`graph` for component and dependency structure,
  `sequenceDiagram` for ordered interactions.
- Keep a diagram to what fits on one screen; split rather than sprawl.
- Every diagram is followed by prose — the diagram supports the text, not the
  reverse.
- **Validate syntax before committing** — a Mermaid error renders as a broken block
  in the host, not as a build failure, so nothing else catches it. Either
  `daa-code-review`, or the `mermaid.parse()` harness in
  [mermaid-guidelines.md](mermaid-guidelines.md#validate-every-diagram-before-committing),
  which also documents the import-order trap that fails diagrams with a misleading
  DOMPurify error.
