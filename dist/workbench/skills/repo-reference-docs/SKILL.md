---
name: repo-reference-docs
description: >
  Create and maintain a repository's human-readable documentation — the root
  README.md front door and, when the repo warrants it, a deep reference set
  under docs/reference/ (architecture, module map, data flow, conventions).
  Use when someone asks to write, generate, update, improve, or refresh a
  README, says "this repo needs a README", or wants deep repo documentation,
  an architecture doc, a "where does X live" module map, a data-flow write-up,
  or a staleness check of existing docs against the code. Not for the
  Claude-facing project.md (use project-context).
---

# Repo reference docs

Build and keep current the documentation that explains how a repository actually
works, for engineers onboarding to it. Two surfaces, one pass, one skill:

- **`README.md`** — the front door. Shallow and orienting: what this is, how to
  run it, what the environment needs, where to look next.
- **`docs/reference/`** — the deep set, for repos that need more than a front door.

Every claim is grounded in real source that you read first — never describe code
you have not opened. Write only these two surfaces; never edit
`.claude/docs/project.md` (that is `project-context`), link to it instead.

## Scope — pick before writing

- **README only.** Small or single-purpose repos, or the user asked for a README.
  Do not invent a `docs/reference/` set they did not ask for.
- **README + reference set.** Multi-component repos, or the user asked for deep
  docs. The README then links into `docs/reference/` rather than duplicating it.
- **Reference set only.** The repo has a healthy README and asked for depth.

## The doc set

`README.md` follows [references/readme-structure.md](references/readme-structure.md)
— section template, badges, diagrams, and writing rules.

Under `docs/reference/` (layouts in
[references/doc-templates.md](references/doc-templates.md)):

- `README.md` — index: one-line summary per doc and a suggested reading order.
- `architecture.md` — what the repo is, major components, how they fit; a
  Mermaid component diagram where it clarifies.
- `module-map.md` — per top-level package/directory: responsibility, key files,
  public surface. The "where does X live" doc.
- `data-flow.md` — how data and control move end to end; key sequences, with a
  Mermaid sequence/flow diagram where it clarifies.
- `conventions.md` — naming, recurring patterns, and a glossary of domain terms.

Trim docs that do not apply; note the omission in the index, never ship an empty file.

## Modes

Detect which applies from the repo state:

- **Create / update (default).** Generate what is absent. Where a doc or README
  already exists, update only the ones whose covered source changed since their
  baseline (see freshness below); leave the rest alone.
- **Check / staleness.** Read-only. Run `scripts/check_docs.py` to report the
  README and any reference doc whose covered paths moved, disappeared, or
  changed since baseline. Writes nothing and exits non-zero on drift, so it
  works in CI and on any clone.

Follow [references/analysis-method.md](references/analysis-method.md) for how to
analyze a repo, ground each section, and scope an incremental update. For an
unfamiliar codebase or a from-scratch pass, use the deeper four-phase sweep in
[references/analysis-phases.md](references/analysis-phases.md), then ask the user
only about what analysis could not settle.

## Freshness & provenance

Each doc — README included — ends with a provenance footer the updater and
checker both read:

```
<!-- repo-reference-docs: baseline=<commit-sha> covers=<comma,separated,paths> -->
```

`covers` lists the source paths that doc is derived from; for the README those
are its front-door anchors (manifests, env templates, CI configs, entry points),
not every file. `baseline` is the commit it was last synced to. This lives
in-repo so staleness is visible to everyone and to CI. A richer local analysis
cache may be kept under `~/.workshop/repo-reference-docs/<repo-key>/` purely to
speed incremental updates — it is an optimization, never the source of truth.

READMEs stamped by the retired `readme-generator` skill carry a
`<!-- readme-generator: ... -->` footer. That is provenance too — read it,
re-stamp with the current marker, never treat it as unstamped.

## Guardrails

- Read source before writing; cite the paths each section covers. No guessing.
- An existing unstamped README is hand-written: confirm with the user before
  overwriting it — they may want parts kept.
- One reference set per repo; keep docs focused and non-overlapping.
- Regenerate the provenance footer whenever you rewrite a doc.
- Prefer updating in place over full regeneration so human edits survive.
- Do not write outside `README.md` and `docs/reference/`.
