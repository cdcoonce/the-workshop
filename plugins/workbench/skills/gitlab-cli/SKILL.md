---
name: gitlab-cli
description: >
  GitLab CLI (glab) integration for managing issues, branches, merge request
  review, and CI/CD pipelines from the terminal. Use when Claude needs to create,
  list, view, or update GitLab issues; push branches; review merge request diffs;
  approve or merge MRs; or inspect and retry pipelines and job logs. Requires the
  glab CLI installed and authenticated. For CREATING a merge request, use the
  gitlab-mr-create skill instead.
---

# GitLab CLI (glab) Skill

Use the `glab` CLI to work with GitLab issues, merge requests, and CI/CD pipelines from the terminal.

## Prerequisites

Verify glab is installed and authenticated:

```bash
glab --version
glab auth status
```

If not authenticated, run `glab auth login` and follow the prompts.

## Boundary: creating a merge request

**This skill does not create merge requests.** That is `gitlab-mr-create`, which derives the title from the `HEAD` conventional-commit subject, reads the description from a file so real newlines survive, and verifies the result through `glab api`. Reach for it whenever a new MR is the goal; everything after the MR exists — review, approval, merge, updates — belongs here.

## Branch policy

Before pushing, opening an MR, or merging, read the repository's project instructions and CI/CD configuration to identify the integration branch. Never assume the GitLab default branch is the correct target, and never push directly to a protected or promotion-only branch when the repository requires a staged integration branch.

**Branch creation:** always `git fetch origin` and cut new branches from `origin/<integration-branch>` — never a bare `git checkout -b` from whatever HEAD happens to be, which drags unmerged commits into the MR and can bypass merge gates.

**After pushing:** watch the pipeline for the pushed SHA and confirm every job is green before declaring the work done. Never walk away from a red pipeline.

## Core Workflows

See [references/commands.md](references/commands.md) for exact syntax, flags, and examples for every command family below.

- **Issues** — `glab issue list | create | view | update | note | close | reopen`
- **Merge requests** — `glab mr list | view | checkout | update | for <issue>`
- **Code review** — `glab mr diff`, `glab mr note`, `glab mr approve | revoke`, `glab mr merge [--squash] [--rebase]`
- **CI/CD** — `glab ci list | get | status | trace | retry | run | lint`

Scope any command to another repository with `-R OWNER/REPO`.

## Common Flag Reference

| Flag                    | Description                 |
| ----------------------- | --------------------------- |
| `-R, --repo OWNER/REPO` | Target different repository |
| `-b, --target-branch`   | Target branch for MR        |
| `-s, --source-branch`   | Source branch for MR        |
| `-t, --title`           | Title for issue             |
| `-d, --description`     | Description for issue/MR    |
| `-l, --label`           | Labels (comma-separated)    |
| `-a, --assignee`        | Assignee username           |
| `-m, --milestone`       | Milestone name              |
| `--web`                 | Open in browser             |
| `-y, --yes`             | Skip confirmation prompts   |

## Environment Variables

| Variable       | Purpose                                                      |
| -------------- | ------------------------------------------------------------ |
| `GITLAB_TOKEN` | Auth token — prefer `glab auth login` over exporting one raw |
| `GITLAB_HOST`  | Self-hosted instance (e.g. `https://gitlab.example.com`)     |

Prefer `glab auth login`; reserve a raw token for non-interactive CI, and inject it from a secret store rather than a shell literal.

## Tips & Gotchas

### Pipeline queries fail silently on the wrong argument

`glab ci list --sha` requires the **full** 40-character SHA — an abbreviated one matches nothing. `glab ci get` takes `--pipeline-id`, not `--sha`. Neither errors on the wrong argument; both return empty, which reads exactly like "still running" and can strand a watcher indefinitely.

Confirm any pipeline-watching loop returns something on its **first** pass before trusting its silence.

### Multi-line descriptions with Markdown

When updating issues or MRs with long markdown descriptions (code blocks, backticks), avoid heredocs — shell interpretation can mangle them. Write the description to a file and source it instead:

```bash
glab issue update 123 --description "$(cat temp_description.txt)"
rm temp_description.txt
```

This sidesteps backticks conflicting with command substitution, special-character interpretation, and heredoc-delimiter conflicts.
