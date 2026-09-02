---
name: repo-docs
description: >
  Creates, classifies, and maintains a repository's human-facing documentation as one
  Diátaxis-shaped set: the root README landing page and docs/ split into tutorials,
  how-to guides, reference, and explanation, with a provenance footer and a drift,
  link, and mode checker. Use when someone asks to write, generate, update, improve,
  or refresh a README, says "this repo needs a README", wants a runbook, how-to guide,
  operations guide, tutorial, architecture doc, module map, data-flow write-up, or a
  "where does X live" doc, asks which kind of doc something is or whether a page is a
  how-to or reference, wants docs restructured or migrated under docs/, or wants a
  staleness or link check of existing docs against the code. Not for the Claude-facing
  project.md (use project-context) or docs/plans/ (use prd-to-plan).
---

# Repo docs

One skill owns a repository's human-facing documentation: the root `README.md`
landing page and `docs/`, arranged by Diátaxis mode. Every claim is grounded in
source read this session. Never describe code you have not opened.

**NO DOCUMENT SERVES TWO MODES.**

| The content… | …serves the reader's… | …so it is                        |
| ------------ | --------------------- | -------------------------------- |
| action       | study                 | a tutorial, `docs/tutorials/`    |
| action       | work                  | a how-to guide, `docs/how-to/`   |
| cognition    | work                  | reference, `docs/reference/`     |
| cognition    | study                 | explanation, `docs/explanation/` |

Landing pages are the one carve-out: the root `README.md`, `docs/README.md` (the hub), and a mode directory's `README.md` introduce and link (`mode=landing`), and the root README
stays near 150 lines. Compass questions, alias table, exempt files, and the verdict
format: [compass.md](references/compass.md).

## Stand down

- Inside The Vault (a `.vault/vault.json` or `.vault-context` up the tree): stop. The
  vault has its own note rules.
- `.claude/docs/project.md` belongs to `project-context`; `docs/plans/` to
  `prd-to-plan`. Link to them, never write them.
- A conversational "teach me this repo" goes to `walkthrough` (ephemeral) or, where installed, `repo-crash-course` (persistent tutor). Write a tutorial file only when asked for one and the compass agrees the content serves study.

## Pick the job

| Job                     | Do                                                                                                                                                                  |
| ----------------------- | ------------------------------------------------------------------------------------------------------------------------------------------------------------------- |
| README only             | The landing page per [readme-structure.md](references/readme-structure.md). Only when the ask was a README; a repo with nothing gets the next row.                                                   |
| README + reference pass | The one grounded multi-doc pass: README plus `docs/reference/` from source, per [mode-reference.md](references/mode-reference.md). A repo with no docs and no named need starts here; a named need (a runbook, a why-question) is written first as one new doc. |
| One new doc             | Compass the request, write from its mode guide, one file, from an identified need.                                                                                  |
| Classify and fix        | Verdict on an existing doc plus exactly one next action, applied after approval.                                                                                    |
| Migrate                 | Move a repo's existing docs into mode directories, one repo per MR: [workflow.md](references/workflow.md#migration).                                                |
| Check                   | Read-only: `scripts/check_docs.py` from this skill's base directory. Exit 1 on any finding, so CI can gate on it.                                                   |

## Workflow

1. **Read source first.** Orient per [workflow.md](references/workflow.md). For an
   unfamiliar repo or a from-scratch pass, run the sweep in
   [analysis-phases.md](references/analysis-phases.md), then ask only what it could not settle.
2. **Compass the request:** action or cognition, study or work. Runbook, operations,
   `DECISIONS.md`, and other house names resolve through the alias table.
3. **Write from the mode guide:** [mode-tutorial.md](references/mode-tutorial.md),
   [mode-how-to.md](references/mode-how-to.md), [mode-reference.md](references/mode-reference.md),
   [mode-explanation.md](references/mode-explanation.md). Diagrams per
   [mermaid-guidelines.md](references/mermaid-guidelines.md); `schema.md` per
   [generated-erd.md](references/generated-erd.md); badges per [badge-reference.md](references/badge-reference.md).
4. **Place it** per [layout.md](references/layout.md). A mode directory is created by
   its first file. Never create an empty mode directory.
5. **Stamp the footer** as the last line:
   `<!-- repo-docs: mode=<mode> baseline=<sha> covers=<comma,separated,paths> -->`.
   Legacy `repo-reference-docs` and `readme-generator` footers are provenance too:
   read them, then re-stamp with a mode.
6. **Run the content-loss guard** in [workflow.md](references/workflow.md#content-loss-guard). A red `tests/test_docs_*.py` blocks the change.
7. **Run the checker** before and after. Fix every finding this change introduced; findings already present before it are reported and become the next action, never fixed in the same change. Two failed runs on findings you introduced: stop and show them instead of attempting a third rewrite.

## Guardrails

- A mixed doc gets one extraction per pass, applied only after approval, on a branch.
  Never a full split, never a tear-down.
- An unstamped README is hand-written: confirm before overwriting. The owner may want parts kept.
- Moves are hard moves: `git mv`, in-repo links rewritten in the same change, checker
  green. Nothing is left behind at the old path.
- Write only `README.md` and `docs/`. The one exception is the opt-in generated `schema.md` machinery in [generated-erd.md](references/generated-erd.md), proposed as its own change after approval. Decision records stay where they are; they are explanation by alias.
- No node for the Mermaid harness: write the diagram and say it is unvalidated. Never block on it.
- Excuse table, red flags, and the escalation threshold: [workflow.md](references/workflow.md#discipline).

## Routes

- `daa-code-review` checks that a README reflects a change; structural doc work comes here.
- `data-discovery` produces a reference-mode document; placement under `docs/` and its footer are this skill's.

