---
name: gitlab-mr-create
description: Create GitLab merge requests with `glab` using the `HEAD` conventional-commit subject as the exact title, a Markdown description file with real newlines, and API read-back verification. Use whenever creating a GitLab merge request.
---

# GitLab MR creation

**Scope:** for repos where GitLab is the primary remote (e.g. the work DAA GitLab), and also for the-workshop's GitLab `dev` branch specifically, via `sync-gitlab-dev` — that skill invokes this script rather than duplicating MR-creation logic. Do NOT use this directly on the-workshop for anything else: GitHub (`origin`) remains its own integration point (PRs via `github-cli`), and GitLab `main` there is a solo CI-green merge with no MR step at all.

Run the wrapper from the target repository — `cwd` must be the repo the MR is created in, because the script reads `git log` and the branch from there. Do not invoke `glab mr create` directly.

The wrapper derives the title from `git log -1 --format=%s`, reads the description from a file (preserving real line breaks rather than a literal `\\n`), rejects manual title/description flags, and verifies the created MR through `glab api`.

```bash
bash "<skill base directory>/scripts/create-mr" \
  docs/mr-description.md --target-branch main --yes
```

`<skill base directory>` is the absolute path this skill's loader announces when it loads — the line reading `Base directory for this skill: /…/skills/gitlab-mr-create`. Expand it inline while composing the command.

It is **not** a shell variable, and neither is anything else here: each command runs in a fresh shell, so an assignment made in one does not survive into the next. `$CLAUDE_PLUGIN_ROOT` in particular is defined only in the _hook_ environment, never in the shell a skill runs commands in — a path built from it collapses to the filesystem root and fails on a missing file (#686). A bare `scripts/create-mr` is wrong for the mirror-image reason: `cwd` is the target repository, which does not contain this skill.

Amend the commit before creating the MR if its conventional-commit subject is not the intended title.
