# GitLab CLI Command Reference

Comprehensive reference for all glab commands used in GitLab workflows.

## Authentication

```bash
# Interactive login
glab auth login                            # Prompts for GitLab instance
glab auth login --hostname gitlab.example.com

# Token-based login
glab auth login --token glpat-xxxx
glab auth login --hostname gitlab.example.com --token glpat-xxxx

# Check auth status
glab auth status
glab auth status --hostname gitlab.example.com

# Logout
glab auth logout
```

## Issue Commands

### glab issue create

```bash
# Basic creation
glab issue create -t "Bug: Login fails" -d "Steps to reproduce..."

# With metadata
glab issue create \
  -t "Feature: Dark mode" \
  -d "Implement dark theme support" \
  --label "enhancement,frontend" \
  --milestone "v2.0" \
  --assignee "username"

# From a file
glab issue create -t "Title" -d "$(cat description.md)"

# Interactive (prompts for all fields)
glab issue create
```

**Flags:**

- `-t, --title` - Issue title (required unless interactive)
- `-d, --description` - Issue description
- `-l, --label` - Labels (comma-separated)
- `-a, --assignee` - Assignee usernames (comma-separated)
- `-m, --milestone` - Milestone name
- `-c, --confidential` - Create as confidential issue
- `--weight` - Issue weight
- `--web` - Open in browser after creation
- `-R, --repo` - Target repository (GROUP/REPO)

### glab issue list

```bash
# Basic listing
glab issue list                            # Open issues
glab issue list --all                      # All states
glab issue list --closed                   # Only closed

# Filtering
glab issue list --assignee @me
glab issue list --author username
glab issue list --label "bug"
glab issue list --label "bug,critical"     # Multiple labels (AND)
glab issue list --milestone "Sprint 1"
glab issue list --search "login error"

# Pagination
glab issue list --per-page 50

# Output format
glab issue list --output json
```

### glab issue view

```bash
glab issue view 123                        # View in terminal
glab issue view 123 --web                  # Open in browser
glab issue view 123 --comments             # Include comments
glab issue view 123 --output json
```

### glab issue update

```bash
glab issue update 123 --title "New title"
glab issue update 123 --description "Updated description"
glab issue update 123 --label "in-progress"
glab issue update 123 --unlabel "todo"
glab issue update 123 --assignee "newuser"
glab issue update 123 --unassign "olduser"
glab issue update 123 --milestone "v2.0"
```

### glab issue note

```bash
glab issue note 123 -m "Comment text"
glab issue note 123                        # Opens editor for comment
```

### glab issue close / reopen / delete

```bash
glab issue close 123
glab issue reopen 123
glab issue delete 123
```

## Merge Request Commands

### glab mr create

```bash
# Interactive creation
glab mr create

# Auto-fill from commits
glab mr create --fill

# Draft MR
glab mr create --draft
glab mr create --draft --fill

# Full specification
glab mr create \
  -t "feat: Add user authentication" \
  -d "Implements OAuth2 login flow" \
  --target-branch main \
  --source-branch feature/auth \
  --label "feature,security" \
  --assignee "@me" \
  --reviewer "senior-dev" \
  --milestone "v2.0"

# From a file
glab mr create -t "Title" -d "$(cat description.md)"

# Open in browser to continue editing
glab mr create --web
```

**Flags:**

- `-t, --title` - MR title
- `-d, --description` - MR description
- `--target-branch` - Target branch (default: repo default)
- `--source-branch` - Source branch (default: current branch)
- `-l, --label` - Labels (comma-separated)
- `-a, --assignee` - Assignees (comma-separated)
- `--reviewer` - Reviewers (comma-separated)
- `-m, --milestone` - Milestone
- `--draft` - Create as draft
- `--fill` - Auto-fill title/description from commits
- `--squash-before-merge` - Enable squash on merge
- `--remove-source-branch` - Delete source branch on merge
- `--allow-collaboration` - Allow commits from members who can merge
- `-w, --web` - Open in browser
- `-R, --repo` - Target repository (GROUP/REPO)

### glab mr list

```bash
# Basic listing
glab mr list                               # Open MRs
glab mr list --all                         # All states
glab mr list --merged                      # Only merged
glab mr list --closed                      # Only closed

# Filtering
glab mr list --assignee @me               # Assigned to you
glab mr list --author @me                 # Created by you
glab mr list --reviewer @me               # Awaiting your review
glab mr list --draft                      # Draft MRs only
glab mr list --label "needs-review"
glab mr list --source-branch "feature/*"  # By source branch
glab mr list --target-branch "main"       # By target branch

# Output
glab mr list --output json
glab mr list --per-page 50
```

### glab mr view

```bash
glab mr view 45                            # View in terminal
glab mr view 45 --web                      # Open in browser
glab mr view 45 --comments                 # Include discussion
glab mr view                               # Current branch's MR
glab mr view 45 --output json
```

### glab mr checkout

```bash
glab mr checkout 45                        # Checkout MR branch locally
glab mr checkout 45 -b my-local-branch     # Custom local branch name
```

### glab mr diff

```bash
glab mr diff 45                            # Show diff
glab mr diff                               # Current branch's MR
```

### glab mr update

```bash
# Modify MR properties
glab mr update 45 --title "New title"
glab mr update 45 --description "Updated"
glab mr update 45 --target-branch develop
glab mr update 45 --label "approved"
glab mr update 45 --unlabel "wip"
glab mr update 45 --assignee "newuser"
glab mr update 45 --reviewer "reviewer1"
glab mr update 45 --milestone "v2.0"
glab mr update 45 --ready                  # Mark draft as ready for review
glab mr update 45 --draft                  # Convert back to draft
```

### glab mr approve

```bash
glab mr approve 45                         # Approve MR
glab mr approve                            # Approve current branch's MR
glab mr revoke 45                          # Revoke approval
```

### glab mr merge

```bash
glab mr merge 45                           # Merge
glab mr merge 45 --squash                  # Squash merge
glab mr merge 45 --rebase                  # Rebase merge

# Post-merge actions
glab mr merge 45 --remove-source-branch    # Delete branch after merge
glab mr merge 45 --when-pipeline-succeeds  # Auto-merge when pipeline passes
glab mr merge 45 --squash --remove-source-branch  # Common combo

# Current branch's MR
glab mr merge
glab mr merge --squash --remove-source-branch
```

### glab mr note

```bash
glab mr note 45 -m "Comment text"
glab mr note 45                            # Opens editor
glab mr note -m "LGTM"                     # Current branch's MR
```

### glab mr close / reopen

```bash
glab mr close 45
glab mr reopen 45
```

## GitLab CI/CD Commands

### glab ci list

```bash
glab ci list                               # Recent pipeline runs
glab ci list --status failed               # Failed pipelines
glab ci list --output json
```

### glab ci view

```bash
glab ci view                               # Interactive selector
glab ci view 12345                         # Specific pipeline
glab ci view --web                         # Open in browser
```

### glab ci run

```bash
glab ci run                                # Trigger on current branch
glab ci run --branch feature/x             # Specific branch
glab ci run --variables "KEY1:value1,KEY2:value2"  # With variables
```

### glab ci retry

```bash
glab ci retry 12345                        # Retry pipeline
```

### glab ci trace

```bash
glab ci trace                              # Trace/follow running job
glab ci trace --branch main                # Trace on specific branch
```

### glab ci status

```bash
glab ci status                             # Pipeline status for current branch
glab ci status --branch main               # Status for specific branch
```

## Repository Commands

### glab repo clone

```bash
glab repo clone group/repo
glab repo clone group/repo target-dir
```

### glab repo view

```bash
glab repo view                             # Current repo
glab repo view group/repo
glab repo view --web                       # Open in browser
glab repo view --output json
```

### glab repo fork

```bash
glab repo fork group/repo
glab repo fork group/repo --clone          # Fork and clone
glab repo fork --remote                    # Add fork as remote
```

### glab repo create

```bash
glab repo create my-repo --public
glab repo create my-repo --private
glab repo create my-repo --internal        # GitLab internal visibility
glab repo create my-repo --group "my-group"
```

## Release Commands

```bash
# Create release
glab release create v1.0.0
glab release create v1.0.0 --name "v1.0.0" --notes "Release notes"
glab release create v1.0.0 --notes-file CHANGELOG.md
glab release create v1.0.0 --assets-links '[{"name":"binary","url":"https://..."}]'

# List / view
glab release list
glab release view v1.0.0

# Upload assets
glab release upload v1.0.0 ./dist/binary

# Delete
glab release delete v1.0.0 --yes
```

## Configuration

### glab config

```bash
# View config
glab config get editor
glab config get browser

# Set config
glab config set editor vim
glab config set browser firefox
glab config set git_protocol ssh

# Per-host config
glab config set -h gitlab.example.com git_protocol ssh
```

### Aliases

```bash
# Create alias
glab alias set co 'mr checkout'
glab alias set review 'mr list --reviewer @me'
glab alias set mv 'mr view --web'

# List aliases
glab alias list

# Delete alias
glab alias delete co
```

## Tips & Patterns

### Complete Feature Branch Workflow

```bash
# 1. Create feature branch from issue
git checkout -b feature/issue-123-add-auth

# 2. Make changes and commit
git add .
git commit -m "feat: add OAuth2 authentication

Implements login flow with:
- Google OAuth2 provider
- Session management
- Token refresh

Closes #123"

# 3. Push and create draft MR
git push -u origin feature/issue-123-add-auth
glab mr create --draft --fill

# 4. Continue working, push updates
git add .
git commit -m "fix: handle token expiration"
git push

# 5. Mark ready for review
glab mr update --ready
glab mr update --reviewer "senior-dev"

# 6. After approval, merge
glab mr merge --squash --remove-source-branch
```

### Quick Review Workflow

```bash
# 1. See pending reviews
glab mr list --reviewer @me

# 2. Checkout and test
glab mr checkout 45

# 3. Review diff
glab mr diff 45

# 4. Approve
glab mr approve 45
glab mr note 45 -m "Looks good, minor nit on line 42"
```

### JSON Output & Filtering

```bash
# glab supports --output json for structured output
glab issue list --output json
glab mr list --output json
```
