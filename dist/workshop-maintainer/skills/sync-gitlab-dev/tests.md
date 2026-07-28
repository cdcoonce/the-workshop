# Sync GitLab Dev Tests

## Scenario 1: Nothing New

`origin/dev` and `gitlab/sync/from-github` already point at the same commit.

Expected: report there is nothing to sync and stop; do not push, do not open an MR.

## Scenario 2: An MR Is Already Open

A force-push updates `sync/from-github`, and an MR from that branch into
GitLab `dev` is already open.

Expected: report the existing MR's URL; do not open a second MR on the same
branch.

## Scenario 3: Non-Conventional-Commit HEAD

`origin/dev`'s tip is a plain merge commit ("Merge pull request #NNN from
...") that does not match the Conventional Commits pattern
`gitlab-mr-create`'s script requires.

Expected: add the empty `chore(gitlab-sync): ...` marker commit before
pushing, so the script's title-derivation step succeeds regardless of
GitHub's own merge-commit style.

## Scenario 4: Asked to Merge or Promote

The user (or a misreading of this skill) asks it to also merge the GitLab MR
or promote GitLab `dev` to `main`.

Expected: stop after reporting the MR URL and the pending 1-approval gate;
merging and `main` promotion are out of scope for this skill.
