---
name: github-cli
description: >
  GitHub CLI (gh) integration for managing issues, pull requests, branches,
  commits, and code reviews directly from the terminal. Use when Claude needs to
  create, list, view, or update GitHub issues; create draft branches and
  pull requests; make commits and push changes; review pull request diffs and
  changes; approve or merge PRs; manage GitHub Actions workflows; or work with
  GitHub repositories without switching to a browser. Requires gh CLI installed
  and authenticated.
---

# GitHub CLI (gh) Skill

Use the `gh` CLI to interact with GitHub repositories, issues, pull requests, and Actions workflows from the terminal.

## Prerequisites

Verify gh is installed and authenticated:

```bash
gh --version
gh auth status
```

If not authenticated, run `gh auth login` and follow the prompts.

## Core Workflows

`gh` covers the full GitHub loop from the terminal. See [references/commands.md](references/commands.md) for the exact syntax, flags, and examples for every command family below.

- **Issues** — `gh issue list | create | view | edit | comment | close | reopen`
- **Pull requests** — `gh pr create [--draft] [--fill] | list | view | checkout | edit | ready`
- **Code review** — `gh pr diff`, `gh pr review --comment | --approve`, `gh pr merge [--squash] [--rebase] [--auto]`
- **Actions** — `gh run list | view | watch | rerun [--failed-only]`, `gh workflow run <file> [--ref <branch>]`

Scope any command to another repository with `-R OWNER/REPO`.

## Common Flag Reference

| Flag                    | Description                    |
| ----------------------- | ------------------------------ |
| `-R, --repo OWNER/REPO` | Target different repository    |
| `--base`                | Base branch for PR             |
| `--head`                | Head branch for PR             |
| `-t, --title`           | Title for issue/PR             |
| `-b, --body`            | Body for issue/PR              |
| `-l, --label`           | Labels (comma-separated)       |
| `-a, --assignee`        | Assignee username              |
| `-m, --milestone`       | Milestone name                 |
| `--draft`               | Create as draft PR             |
| `--fill`                | Auto-fill from commit messages |
| `--web`                 | Open in browser                |
| `-y, --yes`             | Skip confirmation prompts      |

## Environment Variables

| Variable   | Purpose                                                    |
| ---------- | ---------------------------------------------------------- |
| `GH_TOKEN` | Auth token — prefer `gh auth login` over exporting one raw |
| `GH_HOST`  | GitHub Enterprise host (e.g. `github.example.com`)         |
| `GH_REPO`  | Default repository, as `owner/repo`                        |

Prefer `gh auth login` for authentication; reserve a raw token for non-interactive CI, and inject it from a secret store rather than a shell literal.

## Tips & Gotchas

### Multi-line Descriptions with Markdown

When creating issues or PRs with long markdown descriptions (code blocks, backticks), avoid heredocs — shell interpretation can mangle them. Write the description to a temp file and source it instead:

```bash
gh issue create -t "Title" -b "$(cat temp_description.txt)"
rm temp_description.txt
```

This sidesteps backticks conflicting with command substitution, special-character interpretation, and heredoc-delimiter conflicts. The same pattern sources a description straight from a plan file:

```bash
gh pr create -t "Title" -b "$(cat docs/plans/my-plan.md)"
```

## Detailed Reference

For comprehensive command options and examples, see [references/commands.md](references/commands.md).
