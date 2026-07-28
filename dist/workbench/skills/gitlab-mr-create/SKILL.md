---
name: gitlab-mr-create
description: Create GitLab merge requests with `glab` using the `HEAD` conventional-commit subject as the exact title, a Markdown description file with real newlines, and API read-back verification. Use whenever creating a GitLab merge request.
---

# GitLab MR creation

**Scope:** for repos where GitLab is the primary remote (e.g. the work DAA GitLab), and also for the-workshop's GitLab `dev` branch specifically, via `sync-gitlab-dev` — that skill invokes this script rather than duplicating MR-creation logic. Do NOT use this directly on the-workshop for anything else: GitHub (`origin`) remains its own integration point (PRs via `github-cli`), and GitLab `main` there is a solo CI-green merge with no MR step at all.

Use `bash scripts/create-mr DESCRIPTION.md [glab mr create options]` from the target repository. Do not invoke `glab mr create` directly.

The wrapper derives the title from `git log -1 --format=%s`, reads the description from a file (preserving real line breaks rather than a literal `\\n`), rejects manual title/description flags, and verifies the created MR through `glab api`.

```bash
bash "$CLAUDE_PLUGIN_ROOT/skills/gitlab-mr-create/scripts/create-mr" \
  docs/mr-description.md --target-branch main --yes
```

Amend the commit before creating the MR if its conventional-commit subject is not the intended title.
