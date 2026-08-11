---
name: sync-gitlab-dev
description: >
  Push this repo's GitHub dev to GitLab as a reviewable merge request into
  GitLab dev, since GitLab is a manually-updated downstream copy (no
  auto-mirror bot) with its own 1-approval dev gate. Use when GitHub dev or
  main has moved and GitLab hasn't been updated yet, or when the user asks to
  sync, push, or update GitLab for the-workshop.
---

# Sync GitLab Dev

GitHub is this repo's own integration point and is untouched by this skill.
GitLab is a separate downstream copy, updated only when asked — this skill
does that update the right way: through a branch and an MR, never a direct
push to GitLab `dev`, because a direct push (even by a Maintainer) bypasses
the GitLab approval rule entirely. That happened once by mistake; this skill
exists so it doesn't happen again.

## Repository Guard

Run only in The Workshop repository. Verify `plugins/` and `scripts/stamp.py`
exist. Otherwise stop and explain this is not a generic sync workflow.

## 1. Confirm the remotes

`git remote -v`. `origin` must be GitHub, `gitlab` must resolve to
`gitlab.com/clearwayenergy-group/.../the-workshop`. Do not assume — a clone
with these reversed has caused real damage before (see CLAUDE.md).

## 2. Check whether a sync is even needed

`git fetch origin dev` and `git fetch gitlab sync/from-github` (the branch
may not exist yet on first run — that's fine, treat it as needing a sync).
Compare `origin/dev` against `gitlab/sync/from-github`: if they already point
at the same commit, or `origin/dev` is an ancestor of the existing branch,
there is nothing new to sync — report that and stop.

## 3. Stamp a sync marker commit

`gitlab-mr-create`'s script (step 4) derives the MR title from the HEAD
commit's subject and requires it to match Conventional Commits — GitHub's own
merge-commit style for this repo doesn't reliably satisfy that. On a local
branch built from `origin/dev`, add an empty marker commit so the title is
always predictable regardless of how the last GitHub merge was made:

```bash
git checkout -B sync/from-github origin/dev
git commit --allow-empty -m "chore(gitlab-sync): sync dev from GitHub @$(git rev-parse --short origin/dev)"
```

## 4. Push the sync branch (never `dev` directly)

`git push --force gitlab sync/from-github`. Force is correct here — this
branch only ever carries a rebuild of `origin/dev` plus the marker commit, it
is not protected, and nothing but this skill's own MR should ever point at it.

## 5. Open or reuse the MR

Check for an already-open MR on this branch first — a force-push updates its
diff automatically, so re-running this skill should never open a duplicate:

```bash
glab api "projects/clearwayenergy-group%2Fdata-architecture-and-analytics%2Fai-tools%2Fthe-workshop/merge_requests?state=opened&source_branch=sync%2Ffrom-github&target_branch=dev"
```

If that returns an open MR, report its URL and stop — the push above already
updated it. Otherwise, from the repo root, invoke `gitlab-mr-create`'s script
directly rather than calling `glab mr create` yourself (that skill owns MR
creation and verification):

```bash
bash plugins/workbench/skills/gitlab-mr-create/scripts/create-mr \
  <description-file> --target-branch dev
```

Write the description file first — note it is a GitHub → GitLab sync and cite
the `origin/dev` SHA it carries.

## 6. Report

State the MR URL, that it needs 1 approval per the GitLab approval rule
before merge, and that `dev` → `main` promotion on GitLab is a separate,
later step this skill does not perform.

## Boundaries

- Never push directly to GitLab `dev` or `main` — always through this
  branch-and-MR path.
- Never call `glab mr create` directly — delegate to `gitlab-mr-create`.
- Do not merge the MR or promote GitLab `dev` to `main` — those are the
  user's call.
