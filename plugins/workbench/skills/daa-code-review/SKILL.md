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

Default: current branch vs its integration target, diffed from the merge-base; report only on changed hunks. `--mr <n>` (glab) and `--pr <n>` (gh) review that diff. Explicit paths and pasted snippets are reviewed whole. Empty diff: say there is nothing to review and stop. Commands and target rules: [targets-and-output.md](references/targets-and-output.md).

## Modes

- **Full (default for user calls):** this skill's standards pass, then the fan-out in [umbrella.md](references/umbrella.md) (`/code-review` for correctness bugs, `security-review` for vulnerabilities), merged and deduped.
- **`--quality-only` (dev-cycle and agents):** standards pass only. No fan-out, no `/code-review`, no `security-review`. Force it when running inside a subagent or when invoked from `security-review`.

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

Analyzers live in this skill's own `scripts/` dir. Resolve it as an absolute path from the `Base directory for this skill: /...` line the loader announces (`<skill_dir>`), never relative to the repo:
`uv run --with ruff python <skill_dir>/scripts/python_analyzer.py <paths...> --json` (Markdown: `markdown_analyzer.py`, no `--with ruff`). Exit 0 = ran; 2 = path missing or unreadable; 3 = ruff unavailable. The repo's own ruff config wins; with none, defaults plus `B` and `S` run, and `assert` in test files is a nit (details: python-checks.md).

## Severity contract

Every finding is **blocking**, **should-fix**, or **nit**. Analyzer ERROR = blocking, WARNING = should-fix, INFO = nit; a source with no level = should-fix. sqlfluff lint = nit because it reports style, while analyzer WARNINGs flag likely defects. **Clean means zero blocking findings and a complete run.** The verdict is **incomplete**, never clean, whenever a check failed or went unverified: analyzer exit 2 or 3, sqlfluff failure, `mmdc` absent, or a fan-out source unavailable.

## Output

- Chat, grouped by severity, each finding with `file:line` and a source tag (`standards`, `ruff`, `sqlfluff`, `code-review`, `security-review`), then the verdict.
- `--save`: write to `~/.workshop/daa-code-review/<repo>/<YYYY-MM-DD>-<branch>.md`, creating the directory.
- `--post`: one summary comment, shown verbatim, posted only on an explicit yes.
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
