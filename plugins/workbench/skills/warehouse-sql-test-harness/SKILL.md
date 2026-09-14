---
name: warehouse-sql-test-harness
description: Executes committed warehouse SQL (Snowflake, BigQuery, Redshift) against DuckDB via sqlglot to prove views and MERGE statements run, instead of asserting on text. Use when SQL has no executing tests. Not drift — use sql-deploy-precheck.
---

# Warehouse SQL test harness

Warehouse SQL usually ships untested, because the engine is remote, credentialed and
slow. The substitute — asserting the generated SQL _contains_ some text — passes on
code that would not run and fails on formatting.

Load the committed `.sql` files into in-process DuckDB through `sqlglot`, seed fixture
rows, freeze the clock, and query the real views. No warehouse, no credentials,
millisecond runs.

## When this is the wrong tool

It cannot see **deployment drift**. The harness builds its tables from the same file it
is testing, so a column the file declares and the live database lacks is invisible _by
construction_. Pair it with `sql-deploy-precheck`, which is the live half. A green
harness is not evidence that anything deploys.

It also proves `sqlglot`'s translation, not the warehouse. Dialect-specific semantics
(`TIMESTAMP_TZ` arithmetic, clustering, `QUALIFY` planning) need the live check.

## Build it

1. **Translate, don't hand-copy.** Read the real `01_tables.sql` / `02_views.sql` and
   run every statement through `sqlglot.transpile(read="snowflake", write="duckdb")`.
   Copying SQL into the test is how the test and the deployed object drift apart.
2. **Freeze the clock.** Anything with a `CURRENT_TIMESTAMP` spine is untestable
   otherwise, and date defects are the common kind. Inject a fixed `now`.
3. **Seed sparsely.** One row per case, with a builder per table. Fixtures that mirror
   production hide which column drove the result.
4. **Assert on rows, never on strings.**

## Dialect gaps that cost real time

The first is a qualified UPDATE SET inside a MERGE, and it is the one that stops the
statement dead rather than changing its meaning.

`sqlglot` handles most of the translation. These three it does not, and each fails in a
way that does not name the cause:

| Snowflake                      | DuckDB                     | Symptom                                                                    |
| ------------------------------ | -------------------------- | -------------------------------------------------------------------------- |
| `SET t.COL = s.COL` in `MERGE` | rejects the alias          | `Parser Error: Qualified column names in UPDATE .. SET not supported`      |
| `EQUAL_NULL(a, b)`             | `a IS NOT DISTINCT FROM b` | translated automatically — verify it, don't assume                         |
| `:named` bind params           | placeholder node           | `Values were not provided for the following prepared statement parameters` |

Substitute bind params **before** `transpile`, not after: `sqlglot` parses `:name` into
a placeholder and DuckDB then demands a value for it.

Strip only what the dialect forces — target-alias qualification, three-part database
names the harness has no schema for — and say so in the helper's docstring. Every strip
is a place the test stops testing the committed bytes.

## Verify the harness has teeth

A harness that silently seeds nothing passes everything. Assert the frozen clock
actually moved, and that fixture counts are non-zero, or the suite is vacuous. Then use
`detector-teeth-check` on the first real defect it is meant to catch.

## Related

- `sql-deploy-precheck` — the live half; catches what this structurally cannot.
- `detector-teeth-check` — prove a new test would fail on the defect it describes.
- `tdd` — red-first discipline these tests should follow.
