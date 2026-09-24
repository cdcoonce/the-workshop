---
name: gitlab-mr-create
description: Create GitLab merge requests with `glab` — a conventional-commit title (the `HEAD` subject, or a title file on a multi-commit branch) for a merge into `dev`, a title file for the hops into `staging` and `main`, descriptions keep real newlines, and both are read back. Use whenever creating a GitLab merge request.
---

# GitLab MR creation

**Scope:** for repos where GitLab is the primary remote (e.g. the work DAA GitLab), and also for the-workshop's GitLab `dev` branch specifically, via `sync-gitlab-dev` — that skill invokes this script rather than duplicating MR-creation logic. Do NOT use this directly on the-workshop for anything else: GitHub (`origin`) remains its own integration point (PRs via `github-cli`), and GitLab `main` there is a solo CI-green merge with no MR step at all.

Run the wrapper from the target repository — `cwd` must be the repo the MR is created in, because the script reads `git log` and the branch from there. Do not invoke `glab mr create` directly.

The wrapper reads the description from a file (preserving real line breaks rather than a literal `\\n`), rejects manual title/description flags, and verifies the created MR through `glab api`. **Which hop it is decides where the title comes from**, so pass `--target-branch` and let the script route.

## Into `dev` — a conventional-commit title

One branch carries one concern, and the title names that concern as a conventional commit. On a one-commit branch that is the `HEAD` subject, so the script uses it by default:

```bash
bash "<skill base directory>/scripts/create-mr" \
  docs/mr-description.md --target-branch dev --yes
```

A multi-commit branch ends on its last slice, not its concern. Test-first work lands a commit per behaviour, then review fixes, then a committed teeth spec, so `HEAD` reads like `test(pjm): commit the conformance mutation spec` (IQ !82). Only 17 of 54 multi-commit MRs into `dev` across six Clearway repos carry their `HEAD` subject as the title. Write the concern's title to a file instead. The same conventional-commit gate applies to it:

```bash
printf 'feat(pjm): conform pjm vocabulary in staging' > /tmp/mr-title.txt
bash "<skill base directory>/scripts/create-mr" \
  docs/mr-description.md --title-file /tmp/mr-title.txt --target-branch dev --yes
```

Never retitle afterwards with `glab mr update --title`: that bypasses the read-back.

## Into `staging` — a title file

Where a repo runs the `dev → staging → main` cadence (see
`gitlab-promotion-flow`'s staging-cadence reference), the refresh MR's source
branch is `dev` itself, so `HEAD` is whatever last landed there: a merge
commit — `Merge branch 'X' into 'dev'`, no conventional-commit subject at
all — or a release bot's `chore(release): vX.Y.Z`, which passes the gate and
mis-titles the refresh silently. Neither describes the hop, so `--title-file`
is required here exactly as into `main`.

```bash
printf 'Refresh staging from dev (carries !117, !118 and !121)' > /tmp/mr-title.txt
bash "<skill base directory>/scripts/create-mr" \
  docs/mr-description.md --title-file /tmp/mr-title.txt --target-branch staging --yes
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

Amending `HEAD` fixes a wrong subject only on a one-commit branch, where that commit is the concern. On a multi-commit branch it relabels a real slice and changes a SHA the description may cite, so pass `--title-file` instead. It never applies to a title-file hop either: a frozen release branch exists precisely so the reviewer's diff cannot move, and `dev`'s merge-commit head belongs to a protected branch no one force-pushes. Use `--title-file` there.
