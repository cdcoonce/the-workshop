# Generated schema page (DDL → Mermaid ERD)

A `docs/reference/schema.md` whose diagrams are **generated from the repo's own
DDL** rather than drawn by hand, so the picture cannot quietly disagree with the
SQL. Optional: only build it when the checklist below says the repo can support
it. A hand-written schema section is a perfectly good outcome.

## Does this repo qualify?

Build the generated page only when **all** of these hold:

- The schema is declared in-repo as SQL `CREATE TABLE` text you can parse
  (`sql/`, `ddl/`, `migrations/` with full table bodies).
- The DDL declares at least some `PRIMARY KEY` / `UNIQUE` / `FOREIGN KEY`
  constraints — those constraints are the derivable half. With none, there is
  nothing to derive and the whole page collapses into the curated file, which is
  just a hand-drawn diagram with extra machinery.
- There is enough of it to be worth a generator: roughly 3+ tables, or views
  that read other views.
- A test runner exists to hold the drift tests.

Degrade instead of forcing it:

| Repo state                                                  | Do this                                                                                                                                                                       |
| ----------------------------------------------------------- | ----------------------------------------------------------------------------------------------------------------------------------------------------------------------------- |
| No SQL DDL at all (ORM models, dbt, Terraform, no database) | Skip entirely. Describe entities in prose in `data-flow.md`.                                                                                                                  |
| DDL exists, declares no constraints                         | Hand-write a schema section with a Mermaid `erDiagram`. Say in the page that the relationships are documented, not declared.                                                  |
| 1–2 tables                                                  | Hand-write it. A generator costs more than it saves.                                                                                                                          |
| Schema lives in migrations that mutate tables over time     | Skip the parser. Point the page at the migration directory and describe the current shape in prose — reconstructing state from a migration chain is a different, harder tool. |
| Views exist but no tables in-repo                           | Ship only the view dependency flowchart.                                                                                                                                      |

When you skip, say so in the reference index — an omission with a reason, never
an empty file.

## The split: derivable vs editorial

The whole design rests on this line. Cross it and the page starts lying.

| Derived from the DDL — never hand-listed | Curated in a YAML sidecar                                      |
| ---------------------------------------- | -------------------------------------------------------------- |
| Entities and their columns and types     | Grain, one sentence per entity                                 |
| `PRIMARY KEY`, `UNIQUE`, `NOT NULL`      | Which non-key columns an analyst needs to write a join         |
| `FOREIGN KEY` edges and their columns    | Joins that work in practice but carry no FK                    |
| —                                        | How N views group into readable clusters, and what each is for |

Nothing in the left column is ever typed into the sidecar: if a constraint moves,
the diagram must move with it. Nothing in the right column is guessable by a
parser: grain is a modelling decision, and "which of these 40 columns matter" is
editorial.

The curated **names** are still mechanical. Every table, view, and column the
sidecar mentions is asserted to exist, and every declared read is asserted to
match what the view's SQL actually selects from. Curation buys judgement, not a
licence to drift.

## Two diagrams, not one

Mermaid's `erDiagram` has no concept of a view, and views commonly read other
views — a DAG, not a layer. Emit both:

1. `erDiagram` — entities, shown columns, key tokens (`PK`, `FK`, `UK`),
   cardinality.
2. `flowchart LR` — the view dependency graph: tables as cylinders
   (`NAME[(NAME)]`), views as plain boxes, one `subgraph` per curated group.

Follow each with a table: entity → grain → PK → natural key for the first,
view → reads → what to use it for (grouped) for the second.

## Draw undeclared joins honestly

A join that has no `FOREIGN KEY` behind it gets a **dashed** connector and an
explicit `(no FK)` in the label — never the same styling as a real constraint:

```
    UPLOAD_LOG  ||--o{ UPLOAD_CURVE_DETAIL : "FK on UPLOAD_ID"
    CURVE_DIMENSION ||..o{ UPLOAD_CURVE_DETAIL : "describes symbol — SYMBOL (no FK)"
```

Say once, above the diagram, what solid and dashed mean. In engines that treat
key constraints as informational (Snowflake, for one), note that neither kind is
enforced at write time — the distinction is what the repo _declares_, not what
the database _guarantees_.

## Parse SQL with a parser

Use `sqlglot` (`read="<dialect>"`) to find what each view reads. A FROM-clause
regex fails in both directions: it reports `FROM VALUES (...)` and
`FROM TABLE(...)` as if they were tables, and it misses a single-line
`CREATE VIEW v AS SELECT * FROM x WHERE ...`.

```python
statements = sqlglot.parse(views_sql, read="snowflake")
for statement in statements:
    if not isinstance(statement, exp.Create):
        continue
    if str(statement.args.get("kind", "")).upper() != "VIEW":
        continue
    name = statement.this.this.name.upper()
    cte_aliases = {c.alias_or_name.upper() for c in statement.find_all(exp.CTE)}
    reads = {
        table.name.upper()
        for table in statement.find_all(exp.Table)
        if table.name and table.name.upper() not in cte_aliases | {name}
    }
```

Exclude CTE aliases and the view's own name, or a recursive or CTE-heavy view
reports itself as a dependency.

A regex over `CREATE TABLE` bodies is acceptable for the column/constraint half
when the DDL is machine-generated or house-style-consistent — anchor it to the
declared type vocabulary and the exact indentation, and let the staleness test be
the thing that catches a miss.

## Generator shape

One script, `scripts/generate_erd_docs.py`, that:

- parses the table DDL into entities/columns/keys/FKs,
- loads the curated YAML sidecar next to the SQL (`sql/<schema>/erd_edges.yaml`),
- renders the two Mermaid blocks plus their tables,
- **injects between markers** — `<!-- erd:begin -->` / `<!-- erd:end -->` — so the
  hand-written prose around them survives regeneration, and raises if either
  marker is missing or they appear out of order,
- supports `--check`, which byte-compares instead of writing and exits 1 when
  stale.

Open the generated region with a one-line "Generated by `<script>` from `<ddl>`
and `<sidecar>`; do not edit inside the markers."

The page still carries the skill's provenance footer, **outside** the end marker,
with `covers` listing the DDL and sidecar paths.

## Drift tests

Three independent guarantees, because the page has two sources of truth:

1. **Staleness** — regenerating reproduces the committed file byte for byte.
   Editing the DDL without regenerating fails here.
2. **Coverage** — every `CREATE VIEW` in the SQL appears in exactly one curated
   group, and the sidecar names no object that does not exist. Adding a view
   without placing it on the diagram fails CI.
3. **Edge honesty** — each view's declared reads equal what `sqlglot` finds in
   its SQL, and every logical relationship names columns that are really in the
   DDL.

A fourth is worth writing once: assert the FK half is read from constraints, not
hand-listed — pin a known FK and assert the tables you deliberately drew as
logical joins still have no declared FK, so promoting a join to a real constraint
forces the sidecar entry to be removed.

## Two things that will bite

**Prettier will fight the byte-compare.** A post-edit formatter hook that runs
prettier on every `.md` realigns generated Markdown tables, which the staleness
test then reports as drift on a file nobody edited. Add the generated page to
`.prettierignore` and confirm:

```bash
npx --no-install prettier --check docs/reference/schema.md
```

**Validate the Mermaid before committing.** Mermaid syntax errors render as a
broken block in the host, not as a build failure. Parse each emitted block:

```bash
npm install mermaid jsdom
```

Then, in a throwaway node script, extract each ` ```mermaid ` block from the page
and call `mermaid.parse()` on it. Mermaid needs a DOM: create a `jsdom` window and
assign `global.window` / `global.document`, and on Node 26 set navigator via
`Object.defineProperty(global, "navigator", { value: window.navigator })` because
the global is read-only. Delete the script and the dev dependencies afterwards
unless the repo wants a permanent check.

## State the provenance limit on the page

A generated ERD documents the schema **the repo declares** — not the live
database. A column added by hand, or a promotion that ran an older file, is
invisible to it. Give the page a short "Verifying against \<engine\>" section
that:

- says plainly that the diagrams come from the repo's DDL,
- includes the catalog queries a human can run — an `INFORMATION_SCHEMA.COLUMNS`
  query for column drift and an object-dependency query (e.g. Snowflake's
  `SNOWFLAKE.ACCOUNT_USAGE.OBJECT_DEPENDENCIES`) for view edges,
- states that **neither query runs in CI**, and when to run them by hand (after
  any promotion or manual schema change),
- names the resolution order: if the live schema and this page disagree, the DDL
  is what changes first, and regenerating propagates it here.
