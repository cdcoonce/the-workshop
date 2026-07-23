---
name: gitlab-mr-create
description: Create GitLab merge requests with `glab` using the `HEAD` conventional-commit subject as the exact title, a Markdown description file with real newlines, and API read-back verification. Use whenever creating a GitLab merge request.
---

# GitLab MR creation

**Scope:** for repos where GitLab is the primary remote (e.g. the work DAA GitLab). Do NOT use on repos where GitLab is only a CI mirror of a GitHub origin (e.g. the-workshop) — those take PRs via `github-cli`; the mirror receives pushes, never MRs.

Use `bash scripts/create-mr DESCRIPTION.md [glab mr create options]` from the target repository. Do not invoke `glab mr create` directly.

The wrapper derives the title from `git log -1 --format=%s`, reads the description from a file (preserving real line breaks rather than a literal `\\n`), rejects manual title/description flags, and verifies the created MR through `glab api`.

```bash
bash "$CLAUDE_PLUGIN_ROOT/skills/gitlab-mr-create/scripts/create-mr" \
  docs/mr-description.md --target-branch main --yes
```

Amend the commit before creating the MR if its conventional-commit subject is not the intended title.
