---
name: gitlab-mr-create
description: Create GitLab merge requests with `glab` — the `HEAD` subject titles a merge into `dev`, a title file titles a promotion into `main`, descriptions keep real newlines, and both are read back. Use whenever creating a GitLab merge request.
---

# GitLab MR creation

**Scope:** for repos where GitLab is the primary remote (e.g. the work DAA GitLab), and also for the-workshop's GitLab `dev` branch specifically, via `sync-gitlab-dev` — that skill invokes this script rather than duplicating MR-creation logic. Do NOT use this directly on the-workshop for anything else: GitHub (`origin`) remains its own integration point (PRs via `github-cli`), and GitLab `main` there is a solo CI-green merge with no MR step at all.

Run the wrapper from the target repository — `cwd` must be the repo the MR is created in, because the script reads `git log` and the branch from there. Do not invoke `glab mr create` directly.

The wrapper reads the description from a file (preserving real line breaks rather than a literal `\\n`), rejects manual title/description flags, and verifies the created MR through `glab api`. **Which hop it is decides where the title comes from**, so pass `--target-branch` and let the script route.

## Into `dev` — the `HEAD` subject

One branch carries one concern, so the conventional-commit subject is the title. `--title-file` is refused on this hop, which keeps the affordance below from decaying into a general override.

```bash
bash "<skill base directory>/scripts/create-mr" \
  docs/mr-description.md --target-branch dev --yes
```

## Into `main` — a title file

`--title-file` is **required** here and the `HEAD` subject is refused. The head of a release branch is the release bot's `chore(release): vX.Y.Z`, which satisfies the conventional-commit gate — so deriving the title on a promotion does not fail loudly, it succeeds and names a production release after a chore. Promotions carry a descriptive title instead.

```bash
printf 'Promote ERG v0.7.2 to main' > /tmp/mr-title.txt
bash "<skill base directory>/scripts/create-mr" \
  docs/mr-description.md --title-file /tmp/mr-title.txt --target-branch main --yes
```

The title comes from a file for the same reason the description does. `!NNN` is GitLab's own merge-request reference syntax and the most natural thing to write in a promotion title, and a shell that expands history rewrites it into a stray command on the way past — which is how ERG !104 shipped with `uv run python scripts/backfill_pinnacle.py` baked into its title.

## Resolving the script path

`<skill base directory>` is the absolute path this skill's loader announces when it loads — the line reading `Base directory for this skill: /…/skills/gitlab-mr-create`. Expand it inline while composing the command.

It is **not** a shell variable, and neither is anything else here: each command runs in a fresh shell, so an assignment made in one does not survive into the next. `$CLAUDE_PLUGIN_ROOT` in particular is defined only in the _hook_ environment, never in the shell a skill runs commands in — a path built from it collapses to the filesystem root and fails on a missing file (#686). A bare `scripts/create-mr` is wrong for the mirror-image reason: `cwd` is the target repository, which does not contain this skill.

Amend the commit before creating the MR if its conventional-commit subject is not the intended title. That remedy assumes `HEAD` is amendable, so it never applies to a promotion: a frozen release branch exists precisely so the reviewer's diff cannot move, and these branches are protected against force-push. Use `--title-file` there.
