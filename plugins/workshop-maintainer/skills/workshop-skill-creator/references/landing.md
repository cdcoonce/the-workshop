# Landing a Pre-Scoped Candidate

Intake path for a candidate that already arrives with a target skill and
evidence — surfaced by `/wrap-up`, `improve-skill`, a review, or the user
directly — rather than one gathered by interviewing the user from scratch.

## Intake

Require the target skill (an existing slug to revise, or "new") and the gap
or improvement and the evidence or session that surfaced it, so the commit
and PR can cite a real source, not a vague "improves X". A candidate with no
target skill and no evidence is not ready to land — route it back to the user
or to `grill-me`.

If the candidate is a brand-new skill rather than a revision, run Gather and
Blueprint (steps 1-2) first and obtain approval; return here only for
Implement and Land once that blueprint is approved. A revision to an existing
skill skips straight to Implement Test-First (step 3).

## Sync the Integration Branch

`git fetch origin`, then check `git diff origin/dev origin/main --stat`.
Empty output means `dev` is only pointer-stale — safe to branch off `main`
and PR into `dev`, since the diff will be clean. Non-empty output means real
divergence: stop and flag it rather than guessing which branch is
authoritative. Branch off the correct base as `<type>/<slug>-<slug-for-fix>`
(Conventional Commit type prefix).

## Land

Commit with a message stating why (the constraint or evidence from Intake),
push the branch, and open a PR with base `dev` — never `main` directly, and
never GitLab: GitHub is `origin` and this repo's own integration point,
GitLab is a separate downstream copy synced by `sync-gitlab-dev`, not by
landing a candidate here. Watch CI (`gh pr checks <n> --watch`) until it
reports green; a pending or absent check is never a pass. Merge only if the
user has already authorized merging this candidate; otherwise stop once CI
is green, report the PR URL, and ask. Promoting `dev` to `main` is a
separate, later step — never fold it into this run.

## Boundaries

- Do not push directly to `dev` or `main`; always land through a PR.
- Do not touch the GitLab remote — syncing it is `sync-gitlab-dev`'s job, run
  separately once this candidate's GitHub PR has merged.
- Do not promote `dev` to `main` as part of landing a candidate.
