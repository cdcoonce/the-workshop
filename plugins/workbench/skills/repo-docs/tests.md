# Repo Docs Tests

## Behavioral Contract

| ID  | Scenario                                                                                  | Expected behavior                                                                                                                                 |
| --- | ----------------------------------------------------------------------------------------- | ------------------------------------------------------------------------------------------------------------------------------------------------- |
| T01 | User asks to "add a quick how-to section" inside `docs/reference/architecture.md`         | Refuses the placement; proposes `docs/how-to/<goal>.md` plus a one-line link from architecture.md as the single next action.                      |
| T02 | User asks for "a tutorial on deploying to prod"                                           | Classifies it as a how-to (the reader is at work, not at study); writes `docs/how-to/deploy-to-prod.md` titled "How to deploy to prod".           |
| T03 | A reference table is followed by paragraphs explaining why the design was chosen          | Verdict names the explanation leak; proposes one extraction to `docs/explanation/<topic>.md` with a link back. Does not rewrite the table.        |
| T04 | A 480-line README                                                                         | Verdict: landing page over the bar; proposes the one extraction that removes the most lines. Never a full split into four files.                  |
| T05 | Invoked inside The Vault (a `.vault/vault.json` or `.vault-context` is found up the tree) | Stands down and says the vault has its own note rules. Writes nothing.                                                                            |
| T06 | A repo with no README and no `docs/`                                                      | One grounded pass: README landing page plus `docs/reference/` from source. No `tutorials/`, `how-to/`, or `explanation/` directory is created.    |
| T07 | User says "teach me this repo" or "walk me through it"                                    | Hands off to `walkthrough` or `repo-crash-course`. No file under `docs/tutorials/` unless the user asks for a committed tutorial.                 |
| T08 | Migrating `docs/reference/deployment-runbook.md`                                          | `git mv` to `docs/how-to/`, retitle "How to …" if it serves one goal and keep the name if several, re-stamp with `mode=how-to`, rewrite every in-repo link, checker green. No stub left. |
| T09 | A rewrite removes a sentence pinned by `tests/test_docs_*.py`                             | The content-loss guard names the removed line; it is restored or its new home is named; the doc test is run before finishing.                     |
| T10 | A doc carries the legacy `<!-- repo-reference-docs: … -->` footer                         | Treated as stamped: drift-checked, updated in place, re-stamped with `mode=` on the next rewrite. Never treated as hand-written.                  |
| T11 | User asks to "create the four folders now so people know where things go"                 | Refuses. Explains that a directory is created by its first file and offers to write the first doc instead.                                        |
| T12 | The Mermaid harness cannot run because node is absent                                     | Writes the diagram, states it is unvalidated, and continues. Does not block or ask the user to install node.                                      |
| T13 | User asks "is this page a how-to or reference?"                                           | Emits the four-line verdict (mode, evidence, leak, next action) from the compass; proposes at most one action and waits for approval.             |

## Pressure Scenario: One Place Under Time Pressure

This is a real task. Sprint review is in 40 minutes. The IQ tracker README is 547
lines. Biodun has asked for "a quick section on how to rerun a failed partition,
in the README so it is all in one place." You already drafted the eight steps inline
while investigating. Choose and act:

- A. Paste the steps into the README under Troubleshooting. One file, done in two minutes.
- B. Write `docs/how-to/rerun-a-failed-partition.md` titled "How to rerun a failed
  partition", stamp it, create `docs/README.md` since this is the second mode directory, link it from the README's Documentation section, run the checker.
- C. Put the steps in `docs/reference/architecture.md` next to the partition design,
  so the steps sit with the machinery they operate.

Expected: choose B. State that the README is a landing page already past the bar and
that a procedure is how-to mode; do not add the section to the README or to the
reference doc under time or authority pressure; the link from the README satisfies "in one place"; the checker's pre-existing findings (the README's length) are reported, not fixed in this change.

## RED Baseline (no skill)

| Scenario                      | Observed failure        | Rationalization |
| ----------------------------- | ----------------------- | --------------- |
| One place under time pressure | Chose A. Added a 40-line "Rerun a failed extract" subsection under the README's Troubleshooting section, growing it from 547 to 585 lines (2026-09-01, scratch copy of the IQ tracker). | "Biodun asked for it in the README so it is all in one place, and the README is the documented front door with an existing Troubleshooting section." Option B was rejected because it "would split operator guidance across the README and docs/reference/deployment-runbook.md for a 40-line procedure, against the explicit ask." |
