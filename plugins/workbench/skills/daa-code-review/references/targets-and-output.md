# Targets and Output

## Resolve the target

1. Integration target comes from repo policy: the nearest project instructions or CI config. That is `dev` for the-workshop and Clearway GitLab repos. Otherwise use `origin/HEAD`; ask if that is ambiguous.
2. `git fetch origin <target>`, then `base=$(git merge-base HEAD origin/<target>)`. If the fetch fails (offline, no remote), fall back to the local `<target>` branch and say the base may be stale; if neither ref exists, ask.
3. Pass `--target origin/<target>` to `branch_checks.py`; it computes the changed files and lines itself, from the merge-base to the working tree, so uncommitted and untracked work is reviewed too. For reading: `git diff $base` plus any untracked files (`git status --short`).
4. Empty diff: say there is nothing to review and stop.

Read surrounding context for understanding, but file findings on what the diff changed. The one exception is documentation the diff made stale ([docs-freshness.md](docs-freshness.md)).

## Reviewing an MR or PR

Run from the repository, or add `-R GROUP/REPO`.

```bash
glab mr view <n> -F json     # title, description, branches, project ids, draft, pipeline
glab mr view <n> --comments  # existing discussions: do not repeat resolved feedback
glab mr diff <n> --raw       # plain diff without color
gh pr view <n> --json title,body,baseRefName,headRepositoryOwner,isCrossRepository
gh pr view <n> --comments
gh pr diff <n>
```

When the MR's branch is not the one checked out, review it in a worktree so the working directory stays untouched: `glab mr checkout <n> --worktree ../review-mr-<n>` (add `--branch review-mr-<n>` if the branch is already checked out elsewhere). If `--worktree` is unrecognized, `git status --porcelain` must be empty; note the current branch, `glab mr checkout <n>`, and `git switch` back at the end. For a GitHub PR: `git fetch origin pull/<n>/head:review-pr-<n>` then `git worktree add ../review-pr-<n> review-pr-<n>`.

Afterwards remove a worktree this review created with `git worktree remove --force ../review-mr-<n>` (the force flag is needed because tools leave `.venv` and caches there; never use it on a path the user supplied), and say where the review ran.

## Execution gate

The static checks run through `uvx` in isolated environments and never import the reviewed code, so they always run. `--run-project-tools` (pytest, mypy) and `dbt parse` install and import the branch, which executes its code.

- **Your own branch:** pass `--run-project-tools`.
- **Someone else's MR or PR:** pass it only when both hold: the source project equals the target project (not a fork), and `bootstrap_files_changed` in the report is empty (`pyproject.toml`, `uv.lock`, `setup.py`, `conftest.py`, `Makefile`, `Dockerfile`, `.gitlab-ci.yml`, `dbt_project.yml`, `packages.yml`, `profiles.yml`). Otherwise name the fork or the changed files and ask a yes/no question first.

Always:

- Never read or pass credentials (`.env`, key files, `profiles.yml` secrets).
- Never run anything that connects to Snowflake without the user's explicit yes and a non-production target.
- A check that needs credentials is recorded as "not run: needs credentials".
- Environment failures are not findings: do not add dependencies or edit the project to make a tool run. Report one only when the diff itself caused it (for example, it removed a dependency).
- If the suite is slow, run the tests covering the changed modules with `uv run python -m pytest -q <paths>` and say so in "Checks run".

## Save

`--save` writes `~/.workshop/daa-code-review/<repo>/<YYYY-MM-DD>-<branch>.md`; `/` in the branch name is replaced with `-` (`feat/x` becomes `feat-x`); create the directory if missing. Nothing is written inside the repo.

## Post

`--post` shows the exact text first and posts only after an explicit yes. Never include a secret value.

- GitLab: one draft note per Blocker, Major and Minor finding (nits only if asked), plus an overall summary. Draft notes stay visible only to the author until published from the MR page; do not publish them. The command is experimental, so run `glab mr note draft create --help` first; if it is unavailable, fall back to one summary comment with `glab mr note <n> -m "<text>"`.

  ```bash
  glab mr note draft create <n> --file <path> --line <line> -m "<comment>"
  glab mr note draft create <n> --file <path> --line <start>:<end> -m "<comment>"
  glab mr note draft create <n> --file <path> --old-line <line> -m "<comment>"
  glab mr note draft create <n> -m "<overall summary>"
  ```

- GitHub: one summary comment, `gh pr comment <n> --body-file <file>` (temp file outside the repo).

Without `--mr` or `--pr`, the target is the open MR/PR for the current branch; if there is none, say so and do not post.
