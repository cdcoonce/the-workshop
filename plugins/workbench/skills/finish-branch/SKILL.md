---
name: finish-branch
description: >
  Use when implementation is complete, all tests pass, and you need to decide
  how to integrate a finished development branch — merge, open a PR, keep it,
  or discard it. Do not use mid-implementation or while the test suite is red.
---

# Finish Branch

Terminal decision gate for completed development work. This skill runs after
the `commit` skill has already committed all changes — it never stages files
itself (no `git add`, `git add -A`, or `git add .`).

## Resolve the integration branch

Before presenting options, read the repository's project instructions and
CI/CD configuration to identify its integration branch. Never infer the
integration branch from the repository default branch. Honor an explicit
branch policy even when it differs from the hosting provider's default.

## Entry Gate

Run the project's full test suite before anything else.

- **Green** → proceed to the options below.
- **Red or unknown** → hard stop. Report the failing tests and get them fixed
  first. Do not present the menu on a red suite.

## Present Exactly Four Options

Ask the user to choose one. Do not add, remove, or substitute options.

### 1. Merge locally

1. Check out the repository's integration branch and pull the latest.
2. Merge (or rebase) the feature branch into it.
3. Re-run the full test suite on the resulting tree.
4. Only if that run is green, declare the merge complete. If it's red, stop
   and report — do not force the merge through on a failing suite.

### 2. Push + open PR

Invoke the `github-cli` skill for this option only — it owns the push/PR
mechanics; this skill does not run `git push` or `gh pr create` directly.

1. Rebase onto the latest integration branch if it has moved.
2. Re-run the full test suite after any rebase and confirm it's green before
   opening the PR.
3. Use `github-cli` to push the branch and open the pull request.

### 3. Keep the branch as-is

Leave the branch untouched — no merge, no push, no cleanup. Confirm to the
user that the branch and its commits remain exactly as they are.

### 4. Discard

Never delete anything yourself. Point the user at the manual steps only:

```bash
git checkout <default-branch>
git branch -D <branch-name>
```

This skill must never run a branch-deleting or otherwise destructive command
on the user's behalf.

## Rules

- Never run `git add`, `git add -A`, or `git add .` — staging and committing
  belongs to the `commit` skill and must already be done before this skill
  runs.
- Never delete a branch or force-push, in any option.
- For options 1 and 2, the full test suite must be re-run and confirmed green
  after any rebase or merge before that option counts as complete.
