```skill
---
name: gitlab-cli
description: >
  GitLab CLI (glab) integration for managing issues, merge requests, branches,
  commits, and code reviews directly from the terminal. Use when Claude needs to
  create, list, view, or update GitLab issues; create draft branches and
  merge requests; make commits and push changes; review merge request diffs and
  changes; approve or merge MRs; manage GitLab CI/CD pipelines; or work with
  GitLab repositories without switching to a browser. Requires glab CLI installed
  and authenticated.
---
```

# GitLab CLI (glab) Skill

Use the `glab` CLI to interact with GitLab repositories, issues, merge requests, and CI/CD pipelines from the terminal.

## Prerequisites

Verify glab is installed and authenticated:

```bash
glab --version
glab auth status
```

If not authenticated, run `glab auth login` and follow prompts.

## Core Workflows

### Issue Management

```bash
# List issues
glab issue list                            # Open issues in current repo
glab issue list --all                      # All issues including closed
glab issue list --assignee @me             # Issues assigned to you
glab issue list --label "bug"              # Filter by label

# Create issue
glab issue create -t "Title" -d "Description"
glab issue create -t "Title" --label "bug,priority::high" --milestone "milestone-1"
glab issue create                          # Interactive mode

# View/update issue
glab issue view 123                        # View issue details
glab issue view 123 --web                  # Open in browser
glab issue update 123 --label "in-progress"
glab issue close 123
glab issue reopen 123

# Add comments
glab issue note 123 -m "Working on this now"
```

### Branch & Commit Workflow

```bash
# Create feature/fix branch
git checkout -b feature/my-feature
git checkout -b fix/issue-123
git checkout -b draft/wip-experiment

# Stage and commit changes
git add .
git commit -m "feat: add new feature"
git commit -m "fix: resolve issue #123"

# Push branch to remote
git push -u origin feature/my-feature
```

### Merge Request Management

```bash
# Create MR (multiple methods)
glab mr create                             # Interactive mode
glab mr create --fill                      # Auto-fill from commits
glab mr create --draft                     # Create as draft
glab mr create --draft --fill              # Draft with auto-fill
glab mr create -t "Title" -d "Description" --target-branch main
glab mr create --label "review-needed" --assignee @me

# List MRs
glab mr list                               # Open MRs
glab mr list --assignee @me                # Your MRs
glab mr list --reviewer @me                # MRs requesting your review
glab mr list --draft                       # Draft MRs only

# View MR details
glab mr view 45                            # View MR in terminal
glab mr view 45 --web                      # Open in browser
```

### Code Review Workflow

```bash
# Checkout MR locally for testing
glab mr checkout 45                        # Checkout MR branch locally

# Review changes
glab mr diff 45                            # View MR diff
glab mr diff                               # Diff for current branch's MR

# Add review comments
glab mr note 45 -m "LGTM, minor suggestion on line 42"
glab mr note -m "Please add tests"         # Comment on current branch's MR

# Approve
glab mr approve 45

# Merge
glab mr merge 45                           # Interactive merge
glab mr merge 45 --squash                  # Squash merge
glab mr merge 45 --rebase                  # Rebase merge
glab mr merge 45 --when-pipeline-succeeds  # Auto-merge when pipeline passes
```

### Update Existing MR

```bash
glab mr update 45 --title "New title"
glab mr update 45 --description "Updated description"
glab mr update 45 --target-branch develop
glab mr update 45 --label "ready-for-review"
glab mr update 45 --ready                  # Mark ready (remove draft)
```

### GitLab CI/CD Pipeline Management

```bash
# List pipeline runs
glab ci list                               # Recent pipeline runs
glab ci list --status failed               # Failed runs only

# View pipeline details
glab ci view                               # Current branch pipeline
glab ci view 12345                         # Specific pipeline

# Trigger pipeline
glab ci run                                # Run pipeline on current branch
glab ci run --branch feature/x             # Run on specific branch

# Retry failed jobs
glab ci retry 12345                        # Retry pipeline

# View job logs
glab ci trace                              # Trace/follow running job
glab ci trace --branch main                # Trace on specific branch

# View job status
glab ci status                             # Pipeline status for current branch
glab ci status --branch main               # Status for specific branch
```

## Common Flag Reference

| Flag                    | Description                     |
| ----------------------- | ------------------------------- |
| `-R, --repo GROUP/REPO` | Target different repository    |
| `--target-branch`       | Target branch for MR           |
| `--source-branch`       | Source branch for MR           |
| `-t, --title`           | Title for issue/MR             |
| `-d, --description`     | Description for issue/MR       |
| `-l, --label`           | Labels (comma-separated)       |
| `-a, --assignee`        | Assignee username              |
| `-m, --milestone`       | Milestone name                 |
| `--draft`               | Create as draft MR             |
| `--fill`                | Auto-fill from commit messages |
| `--web`                 | Open in browser                |
| `-y, --yes`             | Skip confirmation prompts      |

## Environment Variables

```bash
export GITLAB_TOKEN="glpat-xxxx"           # Personal access token
export GITLAB_HOST="gitlab.example.com"    # Self-managed GitLab instance
export GITLAB_REPO="group/repo"            # Default repository
```

## Tips & Gotchas

### Multi-line Descriptions with Markdown

When creating issues or MRs with long descriptions containing markdown (code blocks, backticks), avoid heredocs which can fail due to shell interpretation. Instead:

```bash
# Step 1: Write description to a temp file (outside bash)
# Step 2: Create from the temp file
glab issue create -t "Title" -d "$(cat temp_description.txt)"
# Step 3: Clean up
rm temp_description.txt
```

This avoids issues with:

- Backticks in code blocks conflicting with command substitution
- Special characters being interpreted by the shell
- Heredoc delimiter conflicts

### Sourcing Description from Existing Files

To create an issue or MR from a markdown plan file:

```bash
# Read file contents into description
glab issue create -t "Title" -d "$(cat docs/plans/my-plan.md)"
glab mr create -t "Title" -d "$(cat docs/plans/my-plan.md)"
```

## Detailed Reference

For comprehensive command options and examples, see [references/commands.md](references/commands.md).
