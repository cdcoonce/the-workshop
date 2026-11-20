# Plan: daa-code-review redesign

Date: 2026-11-13
Status: phases 1-3 landed on `feat/daa-code-review-redesign` (2026-11-13); phase 4 next. Resolved: `/code-review` fan-out at medium; Mermaid best-effort via `mmdc`. Added in review: repo ruff config wins (no-config fallback = defaults + B,S), bandit findings are should-fix, `assert` in test files is a nit. The adversarial-review line stayed unchanged (eval-gated).
Authority: Charles (scope calls made 2026-11-13)

The skill reviews one file or pasted snippet at a time, covers Python, Markdown and Mermaid only, writes report files into the repo, and overlaps the built-in `/code-review` and `/simplify`. This plan makes it a diff-first umbrella reviewer that covers the DAA stack (Python, dbt/Snowflake SQL, YAML, Markdown, Mermaid).

## Boundaries

- The skill name stays `daa-code-review`. Five agents load it by name, and three root tests pin it.
- PRs into `dev` are version-neutral. The bump happens at `make release`.
- Test-pinned strings survive the rewrite:
  - "SOLID/DRY/YAGNI" and "descriptive variable naming" stay in SKILL.md.
  - `private_key_bytes` stays in `references/python-checks.md`.
  - "repo-docs" stays in SKILL.md.
  - `scripts/tests/test_*.py` must still exist.
- The description stays at or under 250 characters, the cap in `test_skill_description_budget.py`. It must not claim another skill's trigger, such as "security review".
- `*.teeth.json` anchors into `markdown_analyzer.py` keep resolving (`make check-teeth-anchors`).

## Architectural decisions

1. **Diff-first target.**
   - With no argument, the skill reviews the current branch against its integration target. The target is resolved from repo policy (`dev` for the-workshop and Clearway GitLab repos), diffed from the merge-base.
   - `--mr <n>` (glab) or `--pr <n>` (gh) reviews that MR or PR's diff.
   - Explicit paths and pasted snippets still work.
   - Only changed hunks get findings. Their surrounding context is read, but not reported on.
2. **Coverage, deterministic first, then judgment.**

   | Type     | Deterministic                                                                                                                                                 | Judgment                                                                                                                                                                                                                                    |
   | -------- | ------------------------------------------------------------------------------------------------------------------------------------------------------------- | ------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------- |
   | Python   | `ruff`, `python_analyzer.py --json`                                                                                                                           | `dignified-python` standard, SOLID/DRY/YAGNI, naming                                                                                                                                                                                        |
   | SQL/dbt  | `uvx sqlfluff lint --format json`: dbt templater when `dbt_project.yml` is present, else the `snowflake` dialect. A repo `.sqlfluff` wins over both defaults. | `ref()`/`source()` instead of hardcoded relations; `unique`/`not_null` on the grain key; join keys tested; incremental `unique_key` present; materialization fits the model; no `select *` in marts. Defers deep questions to `dbt-expert`. |
   | YAML     | parse check (`yaml.safe_load`)                                                                                                                                | dbt schema files (models documented and tested), CI files (rules and branch scope)                                                                                                                                                          |
   | Markdown | `markdown_analyzer.py --json`                                                                                                                                 | none beyond the analyzer                                                                                                                                                                                                                    |
   | Mermaid  | `mmdc` parse when available; otherwise the diagram is reported as **unverified**                                                                              | no web search                                                                                                                                                                                                                               |
   | Dagster  | none                                                                                                                                                          | asset, sensor and schedule patterns. Defers to `dagster-expert`.                                                                                                                                                                            |

3. **Umbrella (full mode, the default for a user call).**
   - The skill runs its own standards pass, then `/code-review` (correctness bugs) and `security-review` (vulnerabilities).
   - It merges the findings, dedupes them on file:line plus issue, and tags each with its source.
   - It never asks `/code-review` for the max or ultra level unless the user does.
4. **`--quality-only` mode.**
   - Runs the standards pass only.
   - dev-cycle phase 6 uses it, and so do the five agents that load the skill.
   - This prevents re-running `/code-review` and security-review on every review loop. It also prevents the cycle where security-review calls this skill and this skill calls security-review.
5. **Severity contract.**
   - Findings are **blocking**, **should-fix** or **nit**.
   - "Clean" means zero blocking findings. dev-cycle loops on this.
6. **Output.**
   - Findings go to chat, grouped by severity, with `file:line` and source.
   - `--save` writes to `~/.workshop/daa-code-review/<repo>/<YYYY-MM-DD>-<branch>.md`.
   - `--post` posts to the MR or PR through glab or gh. It shows the exact comment text and posts only on an explicit yes.
   - Nothing is written inside the repo. The `docs/code_reviews/` convention and its `.gitignore` line go away.
7. **Fixes.** The skill offers fixes and applies them with approval. `fix-workflow.md` is trimmed to the approval modes.
8. **Scripts.**
   - Delete `report_generator.py` and `test_report_generator.py`.
   - Drop `ReviewReport` from `models.py`.
   - Both analyzers get a `--json` CLI over paths.
9. **README step dropped.** One hand-off sentence replaces it: when the diff changes public behaviour and the docs look stale, hand off to `repo-docs`.

## Phase 1: Slim the scripts (TDD)

- Failing tests first: the analyzer `--json` CLI returns findings for a fixture with known issues.
- Delete the report generator, `test_report_generator.py`, and `ReviewReport`.
- Exit criteria: `make test` is green and the teeth anchors resolve.

## Phase 2: Rewrite the skill

- Rewrite SKILL.md (under about 100 lines) to cover target resolution, modes, the severity contract and output.
- New references:
  - `sql-dbt-checks.md`
  - `yaml-checks.md`
  - `umbrella.md` (fan-out, merge and dedupe rules)
- Trim `fix-workflow.md` and `authoring-conventions.md`, and drop their report_generator content.
- Retire the web-search guidance in `mermaid-checks.md`.

## Phase 3: Update callers

- `dev-cycle/SKILL.md`:
  - Line 65: phase 6 calls `daa-code-review --quality-only` against the branch diff.
  - Lines 67 and 77: fan-out wording.
- Agents that load the skill: say quality-only.
- `security-review/SKILL.md` lines 6 and 15: the boundary becomes that full-mode daa-code-review calls security-review, and security-review never calls back.
- `adversarial-review/SKILL.md` line 109: full mode is no longer "cheaper"; quality-only is.
- `repo-docs/SKILL.md` line 82: the README check line.
- `.gitignore`: drop the `docs/code_reviews` line.
- Run `make stamp`, then `make test`.

## Phase 4: Harden

- Write `tests.md` covering:
  - diff-target resolution
  - quality-only versus full mode
  - SQL finding on a hardcoded relation
  - unverified Mermaid
  - `--post` asks first
  - nothing written to the repo
- Run `/improve-skill daa-code-review` from baseline to target.

## Open questions

- The effort level for the `/code-review` fan-out. Proposal: medium.
- Whether `mmdc` should be an expected dependency or stay best-effort (unverified when absent).
