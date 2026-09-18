# Promoting from a frozen release branch

An MR's diff always tracks its source branch head. Promoting straight from
`dev` therefore means every merge into `dev` changes what the reviewer is
reading, and an approval can land on a change they never saw. The alternative —
holding every `dev` merge until the promotion lands — makes your velocity a
function of someone else's review calendar, and stacks interdependent branches
that then all need rebasing.

Freeze the diff instead, and leave `dev` open.

## The flow

1. **Cut `release/vX.Y.Z` off `dev`** at the SHA being promoted, and open the
   promotion MR from *that* branch into `main`. It is byte-identical to `dev`
   at freeze time, so nothing about the change set is altered — only its
   ability to drift.
2. **Protect it at push=Maintainers**, not "No one". "No one" reads like the
   safer setting and is the wrong one here: it blocks step 3.
3. **Review findings land on `dev` first**, through the normal branch-to-MR
   flow, and are then cherry-picked forward:

   ```bash
   git checkout release/vX.Y.Z && git cherry-pick <fix-sha> && git push
   ```

   Forward only. Fixing on the release branch and forgetting to back-merge
   silently regresses `dev` and reintroduces the bug at the next promotion.
4. **Audit before merging.** `git log release/vX.Y.Z..dev --oneline` lists
   everything this MR leaves behind. Every entry should be new feature work
   deliberately excluded; anything resembling a review fix means a cherry-pick
   was missed.

## The title

The promotion MR's title comes from `gitlab-mr-create`'s `--title-file`. At the
head of a release branch the `HEAD` subject is the release bot's
`chore(release): vX.Y.Z` — the commit's subject, not the release's title — and
because that satisfies the conventional-commit gate it is accepted rather than
refused. Amending it is not the fallback: the freeze exists so the diff cannot
move, and the branch is protected against force-push.

## Check CI before assuming this is free

The deviation is usually invisible to CI, but confirm rather than assume, since
the rules are per-repo:

- Pipeline rules that fire on `merge_request_event` give the MR its pipeline
  regardless of source branch name.
- Deploy and tag jobs gating on `CI_COMMIT_BRANCH == "main"` behave identically
  after the merge, because the merge commit lands on `main` either way.
- A version-bump job scoped to `dev` will not run here, which is the intent:
  the version was already bumped on `dev` before the freeze.
- Pushing the release branch itself should spawn no pipeline. Verify it rather
  than assuming it.
