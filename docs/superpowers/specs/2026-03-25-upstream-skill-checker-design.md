# Upstream Skill Checker — Design Spec

**Date:** 2026-03-25
**Status:** Draft

## Problem

The `dagster-expert` and `dbt-expert` skills in `presets/data-pipeline/` are snapshot ports from external GitHub repositories. There is no automated mechanism to detect when upstream repos change — particularly changes to implementation best practices and recommended patterns.

### Upstream Sources

| Skill | Upstream Repo | Relationship |
|-------|--------------|-------------|
| dagster-expert | `dagster-io/skills` | Near-verbatim port (163 reference files) |
| dbt-expert | `dbt-labs/dbt-agent-skills` | Rewritten/consolidated (9 upstream skills → 4 local reference files, Cloud/MCP refs stripped) |

## Solution

A CLI script (`scripts/check_upstream.py`) that shallow-clones upstream repos, diffs against a known-synced commit, and produces a markdown report showing what changed.

## Metadata File: `upstream.yaml`

Lives at repo root. One entry per tracked skill.

```yaml
skills:
  dagster-expert:
    repo: https://github.com/dagster-io/skills.git
    upstream_path: skills/dagster-expert/skills/dagster-expert
    local_path: presets/data-pipeline/skills/dagster-expert
    last_synced_sha: null
    last_checked: "2026-03-25"
    last_checked_sha: null

  dbt-expert:
    repo: https://github.com/dbt-labs/dbt-agent-skills.git
    upstream_path: skills/dbt/skills
    local_path: presets/data-pipeline/skills/dbt-expert
    last_synced_sha: null
    last_checked: "2026-03-25"
    last_checked_sha: null
    file_map:
      using-dbt-for-analytics-engineering/SKILL.md: references/modeling.md
      adding-dbt-unit-test/SKILL.md: references/testing.md
      running-dbt-commands/SKILL.md: references/cli.md
      fetching-dbt-docs/SKILL.md: references/docs.md
    ignored:
      - answering-natural-language-questions-with-dbt
      - building-dbt-semantic-layer
      - configuring-dbt-mcp-server
      - troubleshooting-dbt-job-errors
      - working-with-dbt-mesh
```

### Field Definitions

- `repo`: Git clone URL for the upstream repository.
- `upstream_path`: Directory within the upstream repo containing the skill content.
- `local_path`: Directory within this repo containing the local copy.
- `last_synced_sha`: Upstream commit SHA that the local copy was last reconciled against. Updated manually via `--mark-synced` after reviewing changes.
- `last_checked`: Date the script last ran against this skill. Updated automatically each run.
- `last_checked_sha`: Upstream HEAD SHA recorded during the most recent check run. Used by `--mark-synced` to promote to `last_synced_sha` without re-cloning.
- `file_map` (optional): Explicit mapping of upstream file paths (relative to `upstream_path`) to local file paths (relative to `local_path`). When absent, the script assumes the upstream and local directory structures mirror each other. Only SKILL.md files are mapped — upstream `references/` and `scripts/` subdirectories within mapped skills are intentionally excluded since local files are rewrites, not verbatim copies.
- `ignored` (optional): List of upstream skill directory names to suppress from "new file" detection. Used for upstream skills that were intentionally excluded during the initial port (e.g., Cloud-only or MCP-specific dbt skills).

## Script: `scripts/check_upstream.py`

### Invocation

```bash
# Check all tracked skills
uv run python -m scripts.check_upstream

# Check a specific skill
uv run python -m scripts.check_upstream dagster-expert

# Initialize baseline (record current upstream HEAD, no diff)
uv run python -m scripts.check_upstream --init

# Mark a skill as synced after reviewing changes
uv run python -m scripts.check_upstream --mark-synced dagster-expert
```

### Behavior

1. Read `upstream.yaml` from repo root.
2. For each skill to check:
   a. Shallow-clone the upstream repo to a temporary directory (auto-cleaned).
   b. Resolve `last_synced_sha` in the cloned repo.
   c. Diff upstream content between `last_synced_sha` and `HEAD`:
      - **No `file_map`** (dagster-expert): `git diff` scoped to `upstream_path`.
      - **Has `file_map`** (dbt-expert): diff each mapped upstream file between the two SHAs. Label output with both upstream and local filenames.
   d. Detect new files/directories added upstream since `last_synced_sha`:
      - **No `file_map`**: any new file under `upstream_path` not at the same relative path under `local_path`.
      - **Has `file_map`**: only report entirely new skill directories under `upstream_path` that are not in `file_map` or `ignored`. Do not report files within already-mapped skill directories.
3. Print summary to terminal: per-skill change count, new files, unchanged count.
4. Write full report to `docs/upstream-reports/YYYY-MM-DD-upstream-diff.md`. Same-day re-runs overwrite the previous report.
5. Update `last_checked` and `last_checked_sha` in `upstream.yaml`. Do NOT update `last_synced_sha` — that requires explicit `--mark-synced`.

### `--init` Flag

For first run or adding a new skill: clones the upstream repo, records the current upstream HEAD as both `last_synced_sha` and `last_checked_sha`, without producing a diff. Establishes the baseline for future comparisons. Only sets SHAs for entries where `last_synced_sha` is currently `null`. Accepts an optional skill name to initialize a single skill: `--init dbt-expert`.

### `--mark-synced` Flag

After reviewing a report and applying desired changes locally, run with `--mark-synced <skill_name>` to promote `last_checked_sha` to `last_synced_sha`. This advances the baseline so the next diff only shows new changes. Requires a skill name argument — omitting it is an error (prevents accidentally marking unreviewed skills as synced). Errors if `last_checked_sha` is `null` for the requested skill (run a check first).

The three modes (check, `--init`, `--mark-synced`) are mutually exclusive.

### Clone Strategy

The script needs enough git history to resolve `last_synced_sha`. Strategy:
1. Start with `git clone --depth 1` (fast, HEAD only).
2. If `last_synced_sha` is not found, deepen with `git fetch --unshallow`.
3. If still not found (force-pushed repo), fall back to full-file diff as documented in error handling.

## Report Format

Written to `docs/upstream-reports/YYYY-MM-DD-upstream-diff.md`.

```markdown
# Upstream Diff Report — YYYY-MM-DD

## dagster-expert
**Upstream:** dagster-io/skills @ <old-sha>..<new-sha>
**Files changed:** N | **New files:** N | **Deleted:** N

### Changed Files
#### references/assets.md
~~~diff
- old line
+ new line
~~~

### New Files
- `references/automation/new-feature.md`

---

## dbt-expert
**Upstream:** dbt-labs/dbt-agent-skills @ <old-sha>..<new-sha>
**Files changed:** N | **New files:** N | **Deleted:** N

### Changed Files
#### using-dbt-for-analytics-engineering/SKILL.md → references/modeling.md
~~~diff
- old best practice
+ updated best practice
~~~

### New Files
- `skills/new-dbt-skill/SKILL.md` (no local mapping)
```

## Error Handling

| Scenario | Behavior |
|----------|----------|
| No network / clone fails | Print error, skip skill, continue with others |
| `last_synced_sha` not found upstream | Warn (repo may have been force-pushed), fall back to full file diff |
| Upstream repo gone / 404 | Print error, skip, continue |
| No changes detected | Print "up to date", still update `last_checked` |
| First run / `last_synced_sha` is `null` | Require `--init` flag or error with instructions |
| `--mark-synced` with `null` `last_checked_sha` | Error: "run a check first" |

## Dependencies

- `pyyaml` — for reading/writing `upstream.yaml`
- `git` — must be available on PATH (already required by this repo)
- No other external dependencies. Uses `subprocess` for git operations and `tempfile` for clone directories.

## File Changes

| Action | Path |
|--------|------|
| Create | `upstream.yaml` |
| Create | `scripts/check_upstream.py` |
| Create | `docs/upstream-reports/` (directory, created on first run) |
| Update | `CLAUDE.md` (add command reference) |
| Update | `pyproject.toml` (add `dependencies = ["pyyaml"]` list — field does not currently exist) |

## Out of Scope

- Automatic merging of upstream changes into local files.
- Notification/CI integration (can be added later).
- Tracking skills beyond dagster-expert and dbt-expert (the design supports it, but only these two are configured initially).
