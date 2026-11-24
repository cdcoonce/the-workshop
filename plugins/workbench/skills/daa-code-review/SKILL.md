---
name: daa-code-review
description: >
  Diff, branch, or MR/PR review for Python, SQL/dbt, YAML, Markdown, Mermaid.
  Use when asked for a "code review", "quality check" or pre-MR check, or code
  is pasted. Security audits: see security-review.
---

# DAA Code Review

Diff-first review for the DAA stack, graded the way a DAA maintainer grades an MR. Deterministic tools run first, then judgment. Every finding has a `file:line`, was checked against the surrounding code, and lands on what the diff changed.

## Target resolution

Default: current branch vs its integration target, diffed from the merge-base to the working tree, so uncommitted and untracked work counts. `--mr <n>` (glab) and `--pr <n>` (gh) review that diff, including its description and existing comments. Explicit paths and pasted snippets are reviewed whole. Empty diff: say there is nothing to review and stop. Commands, worktree checkout and the execution gate: [targets-and-output.md](references/targets-and-output.md).

## Modes

- **Full (default for user calls):** this skill's standards pass, then the fan-out in [umbrella.md](references/umbrella.md) (`/code-review` for correctness bugs, `security-review` for vulnerabilities), merged and deduped.
- **`--quality-only` (dev-cycle and agents):** standards pass only. No fan-out, no `/code-review`, no `security-review`. Force it when running inside a subagent or when invoked from `security-review`.

## Standards pass

**1. Run the checks.** One command, from the reviewed worktree. Resolve `<skill_dir>` as an absolute path from the `Base directory for this skill: /...` line the loader announces, never relative to the repo:

`uv run --script <skill_dir>/scripts/branch_checks.py --target <target-ref>`

It finds the changed files and lines and prints one JSON report: a `checks` list with `tool`, `scope`, `status` (`pass`, `fail`, `not_run`, `error`), `reason` and `findings`, each finding with a severity and `on_changed_line`. Secret values are already redacted. Add `--run-project-tools` for pytest and mypy: by default on your own branch, and only after the execution gate passes for someone else's MR. Exit 2 means the target ref or worktree is invalid. Do not re-run its tools by hand or install anything to make one run.

Report findings on changed lines and in new files; drop the rest unless the diff makes them worse. Mermaid is the one check outside the script: `mmdc` parse when on PATH, else unverified ([mermaid-checks.md](references/mermaid-checks.md)).

**2. Judge the diff on each axis.** Load a reference only when the diff touches its subject.

| Axis                                      | Reference                                                                                              |
| ----------------------------------------- | ------------------------------------------------------------------------------------------------------ |
| Completeness, correctness                 | [review-process.md](references/review-process.md)                                                      |
| Design (SOLID/DRY/YAGNI), security, stack | [engineering-design.md](references/engineering-design.md) (YAGNI wins over SOLID)                      |
| Python, descriptive variable naming       | [python-checks.md](references/python-checks.md), [naming](references/python-checks.md#naming)          |
| SQL, dbt, Snowflake                       | [sql-dbt-checks.md](references/sql-dbt-checks.md)                                                      |
| YAML, CI                                  | [yaml-checks.md](references/yaml-checks.md)                                                            |
| Docs and docstring freshness              | [docs-freshness.md](references/docs-freshness.md)                                                      |
| Markdown, Mermaid                         | [markdown-checks.md](references/markdown-checks.md), [mermaid-checks.md](references/mermaid-checks.md) |
| Dagster                                   | conventions in engineering-design.md; deeper questions go to `dagster-expert`                          |

**3. Verify.** Re-read the surrounding code before reporting and drop what you cannot support; what neither a tool nor reading could confirm goes under "Not verified" ([review-process.md](references/review-process.md#verify-before-reporting)).

## Severity contract

- **Blocker:** security vulnerability, exposed secret, data loss or corruption, wrong results, failing build or tests.
- **Major:** likely bug, missing tests for changed behavior, documentation that now misleads, notable Snowflake cost or performance risk, design problem with a concrete present-day cost.
- **Minor:** maintainability, style the linter missed, small documentation gaps.
- **Nit:** preference. Keep at most five and drop the rest.

Tool findings arrive already graded; a source with no level is Minor until you judge it.

**Verdict.** Any Blocker or Major: **Request changes**. Only Minor or Nit: **Approve with comments**. Nothing to report: **Approve**. The verdict is **Incomplete**, never an approval, whenever a check did not run: a `not_run` or `error` status on a check that had files to look at, exit 2, `mmdc` absent with a changed diagram, or a fan-out source unavailable. Name the gap; a tool that did not run is not a pass. pytest and mypy left out by the execution gate are listed under "Checks run" and do not by themselves make the verdict Incomplete.

## Output

- Chat, in the report template from [review-process.md](references/review-process.md#report-template): verdict, a "Checks run" table, findings grouped by severity, each with `file:line` and a source tag (`standards`, `ruff`, `bandit`, `pydoclint`, `sqlfluff`, `pytest`, `mypy`, `code-review`, `security-review`), then "Not verified".
- `--save`: write to `~/.workshop/daa-code-review/<repo>/<YYYY-MM-DD>-<branch>.md` (`/` in the branch name becomes `-`: `feat/x` is `feat-x`), creating the directory.
- `--post`: draft notes on the MR or one PR comment, shown verbatim, posted only on an explicit yes.
- Never write review output (report, saved files, post bodies, temp files) inside the repo; applying approved fixes edits repo files.

## Fixes

After reporting, offer fixes and apply only what the user approves; approval modes are in [fix-workflow.md](references/fix-workflow.md). Re-run the checks after applying.

## Boundaries

- The standards pass runs the diff-scoped security checklist. Deep vulnerability audits (auth flows, crypto, OWASP) belong to `security-review`. Full mode calls it; `security-review` never calls this skill back.
- `/code-review` owns deep correctness-bug hunting and `/simplify` owns apply-the-cleanup passes; this skill does not duplicate them.
- Stale README or docs are a finding here, with a one-sentence handoff to `repo-docs` for the rewrite; do not edit docs outside the fix workflow.
- Changing the analyzer scripts: see [authoring-conventions.md](references/authoring-conventions.md).

## Requirements

`uv` (it supplies Python 3.10+ and runs each tool in isolation) and `git`. `glab` or `gh` for `--mr` / `--pr`. `mmdc` is optional.
