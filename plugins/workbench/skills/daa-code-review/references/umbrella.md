# Umbrella Mode (Full Review)

Full mode is the default for a user call. `--quality-only` skips everything below.

## Fan-out order

1. Standards pass (this skill) on the resolved diff target.
2. Invoke the Skill tool with skill `code-review` and args `medium <target>`. The target is the branch name for a branch or GitLab MR, or the PR number for a GitHub PR. Never pass max or ultra unless the user asks for it.
3. Invoke the Skill tool with skill `workbench:security-review` on the same diff.

Steps 2 and 3 are independent; run them concurrently when the harness allows.

## Merge and dedupe

- Collect all findings into one list. Two findings are duplicates when they share file:line and the same underlying issue; keep one, with the highest severity, and list every source that raised it (for example `code-review, standards`).
- Tag each finding with its source: `standards`, `ruff`, `sqlfluff`, `code-review`, `security-review`.

## Severity mapping

| Source          | Their level               | Contract level              |
| --------------- | ------------------------- | --------------------------- |
| analyzers/ruff  | ERROR / WARNING / INFO    | blocking / should-fix / nit |
| sqlfluff        | parse error / lint        | blocking / nit              |
| code-review     | confirmed bug / uncertain | blocking / should-fix       |
| security-review | high / medium / low       | blocking / should-fix / nit |

A source that gives no level maps to should-fix. Judgment findings from the standards pass are should-fix by default; blocking only for a defect that breaks behaviour. "Clean" has one definition, in SKILL.md (zero blocking findings and a complete run); do not restate it here.

## Guards

- `--quality-only` runs no fan-out. dev-cycle and the agents that load this skill use it.
- Recursion guard: inside a subagent, or when invoked from `security-review`, force `--quality-only`. The call direction is daa-code-review to security-review only.
- If a fan-out source fails or is unavailable, say so in the output; the verdict is incomplete, not clean.
