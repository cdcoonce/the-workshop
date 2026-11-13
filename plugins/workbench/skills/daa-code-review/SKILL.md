---
name: daa-code-review
description: >
  Diff, branch, or MR/PR review for Python, SQL/dbt, YAML, Markdown, Mermaid.
  Use when asked for a "code review" or "quality check", or code is pasted.
  Not vulnerabilities; see security-review.
---

# DAA Code Review

Diff-first quality review for the DAA stack. Deterministic tools run first, then judgment. Findings land only on changed hunks.

## Target resolution

- Default: current branch vs its integration target (from repo policy: `dev` for the-workshop and Clearway GitLab repos), diffed from `git merge-base`. Read surrounding context, report only on changed hunks.
- `--mr <n>`: that MR's diff via `glab`. `--pr <n>`: that PR's diff via `gh`.
- Explicit paths and pasted snippets still work; review them whole.

## Modes

- **Full (default for user calls):** this skill's standards pass, then the fan-out in [umbrella.md](references/umbrella.md) (`/code-review` for correctness bugs, `security-review` for vulnerabilities), merged and deduped.
- **`--quality-only` (dev-cycle and agents):** standards pass only. No fan-out, no `/code-review`, no `security-review`.

## Standards pass

Run the deterministic check, then judge. Beyond tool output, check SOLID/DRY/YAGNI conformance and descriptive variable naming (worked example in [python-checks.md#naming](references/python-checks.md#naming)).

| File type | Deterministic                               | Reference                                           |
| --------- | ------------------------------------------- | --------------------------------------------------- |
| Python    | `ruff`, `scripts/python_analyzer.py --json` | [python-checks.md](references/python-checks.md)     |
| SQL/dbt   | `uvx sqlfluff lint --format json`           | [sql-dbt-checks.md](references/sql-dbt-checks.md)   |
| YAML      | `yaml.safe_load` parse                      | [yaml-checks.md](references/yaml-checks.md)         |
| Markdown  | `scripts/markdown_analyzer.py --json`       | [markdown-checks.md](references/markdown-checks.md) |
| Mermaid   | `mmdc` parse when on PATH, else unverified  | [mermaid-checks.md](references/mermaid-checks.md)   |
| Dagster   | none; defer to `dagster-expert`             | asset, sensor, schedule patterns                    |

Analyzer CLI: `python scripts/<analyzer>.py <paths...> --json`. Exit 0 = ran; 2 = path missing or unreadable; 3 = ruff unavailable (Python). On exit 2 or 3, report the failure (for 3: say ruff is missing) and never report that file clean.

## Severity contract

Every finding is **blocking**, **should-fix**, or **nit**. Analyzer ERROR = blocking, WARNING = should-fix, INFO = nit. **Clean means zero blocking findings**; dev-cycle loops on this.

## Output

- Chat, grouped by severity, each finding with `file:line` and a source tag (`standards`, `ruff`, `sqlfluff`, `code-review`, `security-review`).
- `--save`: write to `~/.workshop/daa-code-review/<repo>/<YYYY-MM-DD>-<branch>.md`.
- `--post`: show the exact comment text and post to the MR/PR (`glab`/`gh`) only on an explicit yes.
- Never write anything inside the repo.

## Fixes

After reporting, offer fixes and apply only what the user approves; approval modes are in [fix-workflow.md](references/fix-workflow.md). Re-run the checks after applying.

## Boundaries

- Vulnerability audits (injection, auth, crypto, OWASP) belong to `security-review`. Full mode calls it; `security-review` never calls this skill back.
- `/code-review` owns correctness-bug hunting and `/simplify` owns apply-the-cleanup passes; this skill does not duplicate them.
- If the diff changes public behaviour and README or docs look stale, hand off to `repo-docs` in one sentence; do not edit docs here.
- Changing the analyzer scripts: see [authoring-conventions.md](references/authoring-conventions.md).

## Requirements

Python 3.10+, ruff, `uvx` for SQL. `mmdc` is optional.
