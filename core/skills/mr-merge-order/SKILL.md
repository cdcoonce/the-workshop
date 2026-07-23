---
name: mr-merge-order
description: Use when several MRs or PRs are open against the same branch and the user asks which to merge first, whether one blocks another, why merging one breaks another, or in what order to land a queue. Computes a pairwise conflict matrix with git merge-tree and recommends an order by rebase cost. Read-only. Covers GitLab and GitHub.
---

# MR Merge Order

Answers one question: **given several MRs racing into the same branch, which order costs least?**

This is analysis, not action. It never checks out, rebases, merges, or pushes. Landing the
result is the user's call, or `finish-branch` / `mr-review-fixes`.

## The mistake this exists to prevent

"Does this MR conflict with `dev`?" is the wrong question. Two MRs can **each** merge into the
target cleanly and still conflict with **each other** — so a per-MR green check tells you nothing
about the queue. You have to simulate "A merged first" and re-test B.

Assumed dependencies are usually backwards. Verify the direction; never take a remembered
"X has to wait for Y" at face value. If an MR in the queue is blocked by a review finding or
carries commits that may already be in the target, run `stale-artifact-sweep` first — ordering
an MR that no longer needs to land wastes the whole analysis.

## Procedure

Run the script. Prefer it over hand-rolling the loops — the ordering rule is easy to invert by accident.

```bash
uv run python core/skills/mr-merge-order/scripts/merge_order.py --repo <path> --target dev
```

- `--branches a b c` analyses branches directly, skipping MR lookup (useful with no `glab`/`gh`).
- `--no-write` prints without persisting.
- Output is saved to `~/.workshop/mr-merge-order/<repo>.md` so a later session can resume
  without recomputing, and so you can diff how the queue changed.

Then read the report to the user: recommended order, the _why_ per pair, and the conflict matrix.

## The cost rule

For a conflicting pair, **the branch with the larger contested diff merges first**; the smaller
one rebases onto it. Re-applying a 6-line edit onto a settled file is cheap; re-applying a 43-line
block onto a file that just changed underneath you is not.

Ties break toward the non-draft (it can actually merge), then by name. An equal-size tie is
flagged as arbitrary — say so rather than implying the order was derived.

## Scope

- **In:** open MRs targeting the same branch. Drafts are included and flagged — a draft still
  conflicts and still constrains order.
- **Stacked MRs** (B targets A's source branch) are a **hard dependency**, reported as a chain
  and excluded from cost ranking. Order there is structural, not economic.
- **Out:** local unpushed branches, CI status, and anything requiring a merge to observe.

## Reporting rules

- Give the order **and** the rationale per pair. "Merge !80 first" is not useful without "because
  its change to `operations.md` is 43 lines against the other's 6."
- Name the contested files. The user usually knows whether that file matters.
- If nothing conflicts, say "any order works" — do not manufacture a sequence.
- If constraints are cyclic, report the cycle. Do not invent a total order.
- State that the analysis was read-only.

## Watch for

- **A conflict that is semantic, not textual.** A commit can merge cleanly and still be _wrong_
  after the other lands — e.g. a doc correcting a CI stage table is accurate when written and
  stale once the other MR changes the stages. Textual cleanliness is not correctness; when the
  contested file documents something the other MR changes, read the content before recommending.
- **Superseded commits.** If the second MR's change is already contained in the first, dropping
  the commit beats resolving it.
- **A stale base.** The script resolves the target to `origin/<target>` and reports how far the
  local branch has drifted, because analysing against a stale local `dev` _fabricates conflicts
  that do not exist_. Still `git fetch` first — the remote-tracking ref is only as fresh as your
  last fetch. If the report's base note says the local branch is behind, that is information for
  the user, not an error to hide.
- **git < 2.38** — `merge-tree --write-tree` is required; the script errors clearly.
