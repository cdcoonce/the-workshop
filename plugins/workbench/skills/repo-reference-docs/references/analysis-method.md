# Analysis method

How to ground the reference set in what the code actually does, and how to keep
it current without rewriting everything. The governing rule: **read before you
write.** A doc section may only describe source you have opened this session.

---

## First pass — orient

1. **Shape.** List the top-level tree; identify languages, package/dependency
   files, and the build/test entry points.
2. **Entry points.** Find where execution starts — CLI, server bootstrap,
   scheduled jobs, `main`/`__main__`, exported package API.
3. **Dependency structure.** Follow imports/requires out from the entry points
   to learn which components depend on which. This is the backbone of both
   `architecture.md` and `module-map.md`.
4. **Read the real code.** Open the key files in each major component — enough
   to describe responsibility and public surface honestly. Note the paths; they
   become each doc's `covers` list.

Prefer a broad read-many-files sweep over deep-diving one corner. When the repo
is large, delegate the sweep to a read-only exploration agent and synthesize.

---

## Writing

- Write each doc from the templates in
  [doc-templates.md](doc-templates.md), section by section, citing the paths a
  section is derived from.
- State the "why" a newcomer cannot infer: intent, historical constraints,
  non-obvious boundaries. Skip what the code makes obvious.
- Stamp the provenance footer: `baseline` = current `HEAD`, `covers` = the
  union of source paths that doc draws from.

---

## Incremental update

When `docs/reference/` already exists, do not regenerate blindly — human edits
must survive:

1. Read each doc's footer to get its `baseline` and `covers`.
2. For each doc, compute what changed: `git diff --name-only <baseline>..HEAD --
<covers...>`. If nothing in `covers` changed, leave the doc untouched.
3. For docs whose covered paths changed, re-read the changed files and revise
   only the affected sections. Preserve surrounding prose and any hand-edits.
4. Re-stamp the footer (`baseline` = new `HEAD`; extend `covers` if the doc now
   describes new paths).

A local analysis cache under `~/.workshop/repo-reference-docs/<repo-key>/` may
store prior structure to speed this up. Treat it as a hint only — the in-repo
footers are the source of truth, so the update is correct even with the cache
absent (fresh clone, teammate, CI).

---

## Checking (read-only)

Run `scripts/check_docs.py --docs-dir docs/reference --repo-root .` to report,
without writing:

- **missing-path** — a `covers` path was moved or deleted.
- **changed-source** — covered paths have commits after `baseline`.

It exits non-zero on any finding, so it can gate a CI job or a pre-promote
check. It relies only on in-repo footers plus git, never on the local cache.
