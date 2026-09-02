# Workflow

The loop, the grounding rules, and the procedures for updating, classifying, and
migrating. The governing rule throughout: **read before you write.** A section may
only describe source opened this session.

## The loop

Diátaxis is a guide, not a plan. Documentation is never finished, but it can always
be complete: useful, appropriate to the repo's current stage, and structurally healthy.

1. **Choose** one piece of documentation: a page, a section, a paragraph. If nothing
   suggests itself, pick at random.
2. **Assess** it. What reader need does it serve? How well? Do its language and logic
   fit its mode ([compass.md](compass.md))?
3. **Decide** the single next action that improves it: add, move, remove, or change.
4. **Do** that action, run the checker, and commit or open the change.
5. Return to step 1.

Structure emerges from this; it is not built in advance. Never create the four
directories and fill them later, and never tear a doc set down to start again.

## Orient

1. **Shape.** List the top-level tree; identify languages, package and dependency
   files, and the build and test entry points.
2. **Entry points.** Where execution starts: CLI, server bootstrap, scheduled jobs,
   `main`, exported package API.
3. **Dependency structure.** Follow imports out from the entry points. This is the
   backbone of `architecture.md` and `module-map.md`.
4. **Read the real code** in each major component, enough to describe responsibility
   and public surface honestly. The paths become each doc's `covers` list.

Prefer a broad read of many files over a deep dive into one corner. For a large or
unfamiliar repo, delegate the sweep to a read-only exploration agent, or run the
four-phase method in [analysis-phases.md](analysis-phases.md), then synthesize.

## Write

- Draft from the mode guide and its template. Cite the paths each section draws on.
- Stamp the footer as the last line: `baseline` is `git rev-parse HEAD` at write
  time; `covers` is the union of source paths the doc describes, directories for
  broad docs, files for narrow ones.
- Every relative link must resolve. The checker reports `broken-link`; fix it before
  committing, not in a follow-up.

## Incremental update

When docs exist, stamped or not, do not regenerate. Human edits must survive. An update touches only the sections the change affects; the template shapes new docs and never re-shapes existing ones. Re-shaping a hand-written README is its own proposal, shown as a diff and approved first.

1. Read each footer for `baseline` and `covers`.
2. Per doc, `git diff --name-only <baseline>..HEAD -- <covers…>`. Nothing changed,
   nothing touched.
3. Where covered paths changed, re-read them and revise only the affected sections.
4. Re-stamp: new `baseline`, `covers` extended if the doc now describes new paths,
   and a `mode` if the old footer had none.



## Classify and fix

For an existing doc the user asks about, or one the loop lands on:

1. Read the whole doc. Apply the compass at the document level, then at the
   paragraph level where it wavers.
2. Emit the verdict in the format from [compass.md](compass.md): mode, evidence,
   leak, next action.
3. The next action is exactly one add, move, remove, or change. An extraction is a move that leaves a link behind, and it is the usual one. It is small enough to review in one sitting. Present it and wait for approval.
4. Apply it on a branch. Rewrite in-repo links to anything that moved. Re-stamp both
   the source and the destination.
5. Run the content-loss guard, then the checker.

The root README is exempt from the mode verdict but not from the length bar. Over
the bar, the next action is the one extraction that removes the most lines: usually
a procedure to `docs/how-to/` or an option table to `docs/reference/`.

## Content-loss guard

A rewrite once silently dropped two operator-facing sentences that a test pinned.
Before finishing any rewrite or extraction:

1. `git diff -- <doc>` and read every removed line.
2. Each removed line is either present at its new home (name it) or deliberately
   dropped (say why). A line that is neither goes back.
3. Run any `tests/test_docs_*.py` in the repo. A red doc test is a blocked change.

## Migration

Moving a repo's existing docs into mode directories. One repo per merge request, done
when already working in that repo, never as a sweep across repos.

1. Run the checker first for the baseline: `scripts/check_docs.py --repo-root .`.
2. Inventory `docs/` and the README. Classify each doc with the compass and the
   alias table. Record the verdicts in the MR description.
3. One move per pass, ordered by value: the runbook out of `docs/reference/` first,
   then explanation paragraphs out of reference docs, then the README under the bar.
4. Each move: `git mv` to the destination named in [layout.md](layout.md); retitle a single-goal how-to "How to …" (a multi-goal runbook keeps its name now and is split later, one extraction per pass); re-stamp with `mode=`; then
   `grep -rn "<old path>"` across the repo and rewrite every in-repo link in the
   same change. Nothing is left at the old path. Links from outside the repo (vault
   notes, MR descriptions) are accepted breakage.
5. Create or update the hub and any per-mode landing page the counts now demand.
6. Checker green, content-loss guard clean, then the next move or the MR.

Legacy footers are provenance. A doc stamped by `repo-reference-docs` keeps being
drift-checked and is re-stamped with a mode the first time it is rewritten or moved.

## Check

`scripts/check_docs.py --repo-root . [--docs-dir docs] [--readme README.md] [--readme-max-lines 150] [--exempt notebooks,qa_reports]`

Reports `missing-path`, `changed-source`, `broken-link`, `mode-mismatch`, and
`readme-length`. Exit 1 on any finding, exit 0 clean, exit 0 with a warning on its own
error. It reads only the repo and git, so it works in CI and on a fresh clone. Relative `--docs-dir` and `--readme` resolve against `--repo-root`, so it runs from anywhere, including the skill's announced base directory (expand that path inline).

## Discipline

The law is one sentence and has no exceptions: **no document serves two modes.**
Landing pages are a separate, bounded carve-out, not an exception to the law.

| Excuse                                                            | Reality                                                                                                                    |
| ----------------------------------------------------------------- | -------------------------------------------------------------------------------------------------------------------------- |
| "It is three quick steps; they belong next to the architecture."  | That is how a 400-line runbook ends up inside `docs/reference/`. Three steps are a how-to with a link from the reference.  |
| "The reader will want the why right here."                        | The reader at work wants the fact; the reader at study wants the why. One paragraph in `docs/explanation/`, one link here. |
| "Splitting this README now will break links."                     | In-repo links are rewritten in the same change and the checker proves it. Outside links were accepted breakage in advance. |
| "Create all four directories now so people know where things go." | Empty structure teaches nothing and Diátaxis forbids it. The first file creates the directory; ask which doc is needed first and write that.                             |
| "A tear-down and rewrite is faster than one extraction."                   | A tear-down is how two tested sentences vanished. One extraction, guard, checker, approval.                             |

Red flags that the law is already broken:

- A diff removes lines you cannot point to a new home for.
- A directory under `docs/` with no files in it.
- A how-to whose title does not start with "How to".
- A reference table or paragraph containing "because", "historically", or "we chose".
- The README past 150 lines, or a "Troubleshooting" section at all: symptom tables are how-to.

Escalation: run the checker before and after. Findings that pre-date the change are reported and become the next action. Two failed runs on findings the change introduced means the change is wrong, not the checker. Stop, show the findings, and ask.
