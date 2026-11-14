# Targets and Output

## Resolve the target

1. Integration target comes from repo policy: the nearest project instructions or CI config. That is `dev` for the-workshop and Clearway GitLab repos. Otherwise use `origin/HEAD`; ask if that is ambiguous.
2. `git fetch origin <target>`, then `base=$(git merge-base HEAD origin/<target>)`. If the fetch fails (offline, no remote), fall back to the local `<target>` branch and say the base may be stale; if neither ref exists, ask.
3. Changed files: `git diff --name-only $base...HEAD`. Hunk ranges: `git diff -U0 $base...HEAD`.
4. `--mr <n>`: `glab mr diff <n>`. `--pr <n>`: `gh pr diff <n>`.
5. Empty diff: say there is nothing to review and stop.

Read surrounding context for understanding, but file findings only on changed lines.

## Save

`--save` writes `~/.workshop/daa-code-review/<repo>/<YYYY-MM-DD>-<branch>.md`; `/` in the branch name is replaced with `-` (`feat/x` becomes `feat-x`); create the directory if missing. Nothing is written inside the repo.

## Post

`--post` posts a single summary comment with findings grouped by severity. Show the exact text first and post only after an explicit yes.

- GitLab: `glab mr note <n> -m "<text>"`
- GitHub: `gh pr comment <n> --body-file <file>` (temp file outside the repo)

Without `--mr` or `--pr`, the target is the open MR/PR for the current branch; if there is none, say so and do not post.
