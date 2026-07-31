---
name: sql-deploy-precheck
description: Compile-check committed warehouse SQL (Snowflake, BigQuery, Redshift) against the live schema before deploying it, catching column drift and views that will not build. Use when about to run a .sql file at a warehouse, after any ALTER TABLE, before re-running a views file, or when a deploy half-applied and left objects inconsistent. Skip for local-only or fixture SQL.
---

# SQL deploy precheck

`CREATE TABLE IF NOT EXISTS` is inert against an existing table. Add a column to that
file and nothing happens — no error, no warning, no diff. The file and the database
disagree from then on, and you find out when a view that selects the new column fails
**half-way down a deploy**, leaving everything after it unapplied.

Check before deploying: does the live schema match the committed DDL, and does every
statement compile against it?

## Why a fixture harness cannot do this

`warehouse-sql-test-harness` builds its tables from the same file it is testing, so a
column the file declares and the database lacks is invisible **by construction**. Three
merged MRs and dozens of passing tests can sit on top of SQL that will not deploy. This
is deployment **drift**, and only a live check sees it.

## Procedure

1. **Parse the committed DDL** for declared columns per table. Reuse the repo's existing
   parser if one exists — a second parser is a second opinion about what the schema is.
2. **Read live columns** from `INFORMATION_SCHEMA`. Report drift per table, both
   directions.
3. **Compile every statement** without executing it — `EXPLAIN` on Snowflake, dry-run on
   BigQuery. Include unchanged objects as a **control group**: if they also fail, the
   problem is the harness, not the change.
4. **Exit non-zero on drift or a compile failure**, so CI and a human get the same answer.

Keep it read-only, and assert that: scan each extracted statement for write verbs and
refuse to run if one appears. Scan the _executable_ text only — a comment that names
`DROP TABLE` while explaining it is prose, and aborting on it makes the tool
untrustworthy in exactly the well-commented files that need it most.

## ALTER TABLE ADD COLUMN invalidates every `SELECT *` view

The trap worth the whole skill. The warehouse expands the star at `CREATE VIEW` time and
freezes the column list, so adding a column breaks every view built that way:

```
002057 (42601): View definition for 'V_FOO' declared 28 column(s),
                but view query produces 29 column(s).
```

**Always re-run the views file immediately after an `ALTER TABLE ADD COLUMN.`** The
`ALTER` succeeding tells you nothing about whether the schema still works.

Report this state as `STALE — RE-RUN <views file>`, not as a compile failure. The remedy
is the opposite of "do not deploy", and grouping them strands the operator on the one
action that repairs it.

## Report parsing failures as failures

Every finding is a statement about something the tool _found_. An extractor that
silently yields nothing reports a clean environment. Assert the parse produced tables
and statements, abort if it did not, and test the parser itself — a broken one does not
make this noisy, it makes it lie.

## Related

- `warehouse-sql-test-harness` — the offline half; proves logic, not deployability.
- `stale-artifact-sweep` — before acting on a recorded deploy blocker, re-verify it.
