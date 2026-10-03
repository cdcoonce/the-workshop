# Landing a PR stacked on a squash-merged base

`pr_land.py land` refreshes a behind head by merging the live base into it in a
scratch worktree. A PR that was cut from another PR's branch (the "base PR")
carries that PR's commits. Once the base PR is squash-merged, that merge can
conflict even though nothing is really in dispute.

## What the stop means

`merging <base> conflicts; resolve by hand:` followed by files, on a PR whose
branch was stacked on a PR that has since been squash-merged. The base PR's
change is on `main` as one new commit, and the head still carries the same
change as the original commits.

## Cause

`git merge <main>` takes the merge base to be the newest commit both sides
share, which is the fork point from before the stack. From there `main`'s
squash and the head's carried copy of the base PR's commits look like two
different additions at the same spot, so they conflict. A squash commit shares
no history with the commits it replaced, so git cannot see they are the same
change.

With the base PR's **final head** as the merge base, the base PR's change is
already on both sides, and the merge leaves only the dependent's own change on
top of `main`.

## What pr_land does now

Only on a conflict, `land` looks for the stack:

1. Takes the commits only the head carries (`git rev-list --topo-order
   <base>..<head>`) and keeps those that are some PR's final head, read in one
   `git ls-remote origin 'refs/pull/*/head'`. GitHub keeps `refs/pull/<n>/head`
   after the branch is deleted. The PR being landed is never a candidate.
2. Walks the candidates newest first and takes the first whose PR is merged
   (`gh api repos/<repo>/pulls/<n>`) with a merge commit that is an ancestor of
   the base. Newest first matters: in a chain A<-B<-C, B's final head already
   contains A's.
3. Merges with that head as the merge base, in the same scratch worktree:
   `git merge-tree --write-tree --name-only --merge-base=<base PR final head>
   HEAD <base>`, then `git commit-tree -p HEAD -p <base>` and
   `git reset --hard`. Needs git 2.40 or newer.
4. Compares the patch-id of `diff(<base PR final head>, <head>)` with
   `diff(<base>, <merged>)`. They must be equal: the dependent's own change and
   nothing else. `--accept-delta-change` works as it does for any refresh.
5. Gates, pushes a plain fast-forward, and prints
   `stack: refreshed with PR #<n> head <sha7> as merge base` on stderr.

Any failure to find the stack (no candidate, an unmerged or unlanded PR, a failed
`ls-remote` or API read) leaves the original refusal unchanged. A merge that
succeeds without this never looks for a stack.

If the merge still conflicts with the stack base, `land` exits 2 with
`merging <base> conflicts even with stack base PR #<n> (head <sha>) as merge
base; resolve by hand:`, the files, and the `git merge-tree` command that
reproduces it. `main` changed the dependent's own region; that is a real
conflict.

## Doing it by hand

```bash
git fetch origin refs/pull/<base-pr>/head
git merge-tree --write-tree --name-only --merge-base=<base PR final head> <head> <base>
```

Exit 0 prints the merged tree on the first line. Compare it with `main` plus the
dependent's change before trusting it:
`git diff <base PR final head> <head>` must equal `git diff <base> <tree>`.

## What stays a stop

Two cases end in the original refusal or a stop, and no git option resolves
either:

- **Not detected (known limit).** Only a stack whose base PR's **final head**
  the dependent already carries is found, because candidates are the final heads
  inside `<base>..<head>`. If the base PR gained a commit after the dependent was
  cut and the dependent never merged it, that final head is not in the
  dependent's history, no candidate exists, and `land` returns the plain
  `merging <base> conflicts; resolve by hand:` refusal with no hint of a stack.
  Merge the base PR's later commits into the dependent first, then land. That is
  the case that can still be a same-position append/append conflict.
- **Detected, still conflicting.** With the stack base found, the dependent and
  something newer (usually `main` moving) both **append at the same spot** of one
  file. That is a genuine append/append conflict. Default and `histogram` leave
  interleaved markers, `patience` and `minimal` fragment the hunks, and `-X ours`
  / `-X theirs` merge cleanly while silently dropping lines.

Prefer not to stack PRs that append at the same position of the same file; land
the base PR first, then cut the dependent from `main`.

## Why no force-push or `rebase --onto`

`pr_land.py` pushes plain fast-forwards only. A rebase rewrites the head, and a
force-push would invalidate the CI run the land is pinned to
(`--match-head-commit`). The repaired merge adds one merge commit on top of the
tested head, so the history the reviewer saw is untouched.
