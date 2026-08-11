# GitHub CLI Command Reference

Comprehensive reference for all gh commands used in GitHub workflows.

## Authentication

```bash
# Interactive login
gh auth login                              # Prompts for GitHub instance
gh auth login --hostname github.example.com

# Token-based login
gh auth login --with-token <<< "ghp_xxxx"
gh auth login --hostname github.example.com --with-token <<< "ghp_xxxx"

# Check auth status
gh auth status
gh auth status --hostname github.example.com

# Logout
gh auth logout
```

## Issue Commands

### gh issue create

```bash
# Basic creation
gh issue create -t "Bug: Login fails" -b "Steps to reproduce..."

# With metadata
gh issue create \
  -t "Feature: Dark mode" \
  -b "Implement dark theme support" \
  --label "enhancement,frontend" \
  --milestone "v2.0" \
  --assignee "username"

# From a file
gh issue create -t "Title" -b "$(cat description.md)"

# Interactive (prompts for all fields)
gh issue create
```

**Flags:**

- `-t, --title` - Issue title (required unless interactive)
- `-b, --body` - Issue body
- `-l, --label` - Labels (comma-separated)
- `-a, --assignee` - Assignee usernames (comma-separated)
- `-m, --milestone` - Milestone name
- `--web` - Open in browser after creation
- `-R, --repo` - Target repository (OWNER/REPO)

### gh issue list

```bash
# Basic listing
gh issue list                              # Open issues
gh issue list --state all                  # All states
gh issue list --state closed               # Only closed

# Filtering
gh issue list --assignee @me
gh issue list --author username
gh issue list --label "bug"
gh issue list --label "bug" --label "critical"  # Multiple labels
gh issue list --milestone "Sprint 1"
gh issue list --search "login error"

# Pagination
gh issue list --limit 50

# Output format
gh issue list --json number,title,state
```

### gh issue view

```bash
gh issue view 123                          # View in terminal
gh issue view 123 --web                    # Open in browser
gh issue view 123 --comments               # Include comments
gh issue view 123 --json title,body,state
```

### gh issue edit

```bash
gh issue edit 123 --title "New title"
gh issue edit 123 --body "Updated description"
gh issue edit 123 --add-label "in-progress"
gh issue edit 123 --remove-label "todo"
gh issue edit 123 --add-assignee "newuser"
gh issue edit 123 --remove-assignee "olduser"
gh issue edit 123 --milestone "v2.0"
```

### gh issue comment

```bash
gh issue comment 123 -b "Comment text"
gh issue comment 123                       # Opens editor for comment
```

### gh issue close / reopen / delete

```bash
gh issue close 123
gh issue reopen 123
gh issue delete 123
```

## Pull Request Commands

### gh pr create

```bash
# Interactive creation
gh pr create

# Auto-fill from commits
gh pr create --fill

# Draft PR
gh pr create --draft
gh pr create --draft --fill

# Full specification
gh pr create \
  -t "feat: Add user authentication" \
  -b "Implements OAuth2 login flow" \
  --base main \
  --head feature/auth \
  --label "feature,security" \
  --assignee "@me" \
  --reviewer "senior-dev" \
  --milestone "v2.0"

# From a file
gh pr create -t "Title" -b "$(cat description.md)"

# Open in browser to continue editing
gh pr create --web
```

**Flags:**

- `-t, --title` - PR title
- `-b, --body` - PR description
- `--base` - Base branch (default: repo default)
- `--head` - Head branch (default: current branch)
- `-l, --label` - Labels (comma-separated)
- `-a, --assignee` - Assignees (comma-separated)
- `--reviewer` - Reviewers (comma-separated)
- `-m, --milestone` - Milestone
- `--draft` - Create as draft
- `--fill` - Auto-fill title/body from commits
- `-w, --web` - Open in browser
- `-R, --repo` - Target repository (OWNER/REPO)

### gh pr list

```bash
# Basic listing
gh pr list                                 # Open PRs
gh pr list --state all                     # All states
gh pr list --state merged                  # Only merged
gh pr list --state closed                  # Only closed

# Filtering
gh pr list --assignee @me                  # Assigned to you
gh pr list --author @me                    # Created by you
gh pr list --reviewer @me                  # Awaiting your review
gh pr list --draft                         # Draft PRs only
gh pr list --label "needs-review"
gh pr list --head "feature/*"              # By head branch
gh pr list --base "main"                   # By base branch

# Output
gh pr list --json number,title,state
gh pr list --limit 50
```

### gh pr view

```bash
gh pr view 45                              # View in terminal
gh pr view 45 --web                        # Open in browser
gh pr view 45 --comments                   # Include discussion
gh pr view                                 # Current branch's PR
gh pr view 45 --json title,body,state
```

### gh pr checkout

```bash
gh pr checkout 45                          # Checkout PR branch locally
gh pr checkout 45 -b my-local-branch       # Custom local branch name
```

### gh pr diff

```bash
gh pr diff 45                              # Show diff
gh pr diff                                 # Current branch's PR
```

### gh pr edit

```bash
# Modify PR properties
gh pr edit 45 --title "New title"
gh pr edit 45 --body "Updated"
gh pr edit 45 --base develop
gh pr edit 45 --add-label "approved"
gh pr edit 45 --remove-label "wip"
gh pr edit 45 --add-assignee "newuser"
gh pr edit 45 --add-reviewer "reviewer1"
gh pr edit 45 --milestone "v2.0"
gh pr ready 45                             # Mark draft as ready for review
```

### gh pr review

```bash
gh pr review 45 --approve                  # Approve PR
gh pr review 45 --request-changes -b "Please fix X"
gh pr review 45 --comment -b "Looks good overall"
gh pr review                               # Review current branch's PR
```

### gh pr merge

```bash
gh pr merge 45                             # Interactive merge
gh pr merge 45 --squash                    # Squash merge
gh pr merge 45 --rebase                    # Rebase merge

# Post-merge actions
gh pr merge 45 --delete-branch             # Delete branch after merge
gh pr merge 45 --auto                      # Auto-merge when checks pass
gh pr merge 45 --squash --delete-branch    # Common combo

# Current branch's PR
gh pr merge
gh pr merge --squash --delete-branch
```

### gh pr comment

```bash
gh pr comment 45 -b "Comment text"
gh pr comment 45                           # Opens editor
gh pr comment -b "LGTM"                    # Current branch's PR
```

### gh pr close / reopen

```bash
gh pr close 45
gh pr reopen 45
```

## GitHub Actions Commands

### gh run list

```bash
gh run list                                # Recent workflow runs
gh run list --status failure               # Failed runs
gh run list --json databaseId,status,conclusion
```

### gh run view

```bash
gh run view                                # Interactive selector
gh run view 12345                          # Specific run
gh run view 12345 --web                    # Open in browser
gh run view 12345 --log                    # Full logs
```

### gh workflow run

```bash
gh workflow run ci.yml                     # Trigger on current branch
gh workflow run ci.yml --ref feature/x     # Specific branch
gh workflow run ci.yml -f "KEY=value"      # With inputs
```

### gh run rerun

```bash
gh run rerun 12345                         # Re-run workflow
gh run rerun 12345 --failed-only           # Re-run only failed jobs
```

### gh run watch

```bash
gh run watch 12345                         # Watch running workflow
```

### gh run list (by branch)

```bash
gh run list --branch main                  # Runs on specific branch
```

## Repository Commands

### gh repo clone

```bash
gh repo clone owner/repo
gh repo clone owner/repo target-dir
```

### gh repo view

```bash
gh repo view                               # Current repo
gh repo view owner/repo
gh repo view --web                         # Open in browser
gh repo view --json defaultBranchRef,name
```

### gh repo fork

```bash
gh repo fork owner/repo
gh repo fork owner/repo --clone            # Fork and clone
gh repo fork --remote                      # Add fork as remote
```

### gh repo create

```bash
gh repo create my-repo --public
gh repo create my-repo --private
gh repo create my-repo --internal
gh repo create my-repo --org "my-org"
```

## Release Commands

```bash
# Create release
gh release create v1.0.0
gh release create v1.0.0 --title "v1.0.0" --notes "Release notes"
gh release create v1.0.0 --notes-file CHANGELOG.md
gh release create v1.0.0 --generate-notes

# List / view
gh release list
gh release view v1.0.0

# Upload assets
gh release upload v1.0.0 ./dist/binary

# Delete
gh release delete v1.0.0 --yes
```

## Configuration

### gh config

```bash
# View config
gh config get editor
gh config get browser

# Set config
gh config set editor vim
gh config set browser firefox
gh config set git_protocol ssh

# Per-host config
gh config set -h github.example.com git_protocol ssh
```

### Aliases

```bash
# Create alias
gh alias set co 'pr checkout'
gh alias set review 'pr list --reviewer @me'
gh alias set pv 'pr view --web'

# List aliases
gh alias list

# Delete alias
gh alias delete co
```

## Tips & Patterns

### Complete Feature Branch Workflow

Create the branch, commit with the `commit` skill, then push and open a PR:

```bash
# 1. Create feature branch from issue
git checkout -b feature/issue-123-add-auth

# 2. Push and create draft PR (after committing with the commit skill)
git push -u origin feature/issue-123-add-auth
gh pr create --draft --fill

# 3. Continue working, push updates (after committing with the commit skill)
git push

# 4. Mark ready for review
gh pr ready
gh pr edit --add-reviewer "senior-dev"

# 5. After approval, merge
gh pr merge --squash --delete-branch
```

### Quick Review Workflow

```bash
# 1. See pending reviews
gh pr list --reviewer @me

# 2. Checkout and test
gh pr checkout 45

# 3. Review diff
gh pr diff 45

# 4. Approve
gh pr review 45 --approve
gh pr comment 45 -b "Looks good, minor nit on line 42"
```

### JSON Output & Filtering

```bash
# gh supports --json for structured output
gh issue list --json number,title,state
gh pr list --json number,title,state,headRefName
gh run list --json databaseId,status,conclusion,workflowName
```
