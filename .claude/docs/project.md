# The Workshop — Project Context

Marketplace of self-contained plugins (`.claude-plugin/plugin.json`, skills, agents, hooks, settings) that install natively on Claude Code, Codex, and Cortex Code — no per-project build step. Nine plugins ship from `plugins/`: `workbench` (the shared toolkit), `workshop-maintainer` (skills for developing this repo), five persona plugins, and two advisor plugins.

## Tech Stack

- **Python >=3.12** — all scripts use stdlib only (no runtime dependencies)
- **uv** — package manager and task runner. `[tool.uv] package = false`: the repo is served, not distributed — nothing here builds a wheel or a console script (no build backend; `hatchling` is no longer used)
- **pytest** — test framework (`tests/` root suite, plus per-skill test suites discovered by `scripts/discover_skill_test_suites.py`; see Test Markers below)

## Project Layout

```text
plugins/                      9 self-contained plugins — what's on disk is what ships
  workbench/                  Shared toolkit: skills, agents, hooks, vault machinery
  workshop-maintainer/        Skills for developing this repo itself
  advisor-product-design/     2 advisor plugins
  advisor-product-strategy/
  persona-*/                  5 persona plugins
  <each contains>             .claude-plugin/plugin.json, skills/, agents/, hooks/
scripts/                      Python tooling (stdlib only, no build step)
  stamp.py                    Regenerate every derived file (`make stamp`, `make stamp-check`)
  smoke_test.py              Validate internal consistency of a source plugin directory
  check_version_bumps.py      Fail when a plugin's shipped content changed without a version bump
  discover_skill_test_suites.py  Discover and run every skill-script test suite in its own rootdir
  dev_cycle_validate.py       Parse/validate dev-cycle state files
tests/                        pytest suite (conftest.py + per-module test files)
docs/                         Plans, archives, and reference docs for this metaproject
```

`core/`, `presets/`, and `dist/` no longer exist — they were the old core+preset
composition build, replaced by the flat `plugins/` layout above. `scripts/build_preset.py`,
`build_docs.py`, `build_marketplace.py`, `dist_digest.py`, and `scripts/installer/`
were deleted with it.

## Data Flow

```text
plugins/<name>/                ─→ read in place by Claude Code / Codex / Cortex,
  .claude-plugin/plugin.json       no build or copy step between source and install
  skills/, agents/, hooks/
                                ─→ scripts/stamp.py regenerates derived files
                                     (docs/reference/*.md, marker-injected README
                                     regions) from that same component metadata
                                ─→ scripts/smoke_test.py validates the tree in place
```

## Key Architecture Patterns

- **No build step** (`scripts/smoke_test.py`): plugins ship directly from `plugins/<name>/` — what is on disk is what ships. The former `core/` + `presets/` composition build and its `dist/` output are gone.
- **Manifest truth, not manifest-driven composition**: each plugin's own hand-written `plugins/<name>/.claude-plugin/plugin.json` is the source of truth; `stamp.py` reads it plus `SKILL.md`/`AGENT.md` frontmatter and hook wiring to regenerate documentation — it does not assemble or copy files into an output tree.
- **Delivery gate** (`scripts/check_version_bumps.py`): a plugin whose shipped content changed without a version bump merges and reaches nobody who already has it installed — `make verify-versions` fails the build on that gap.
- **Plugin format** (`.claude-plugin/plugin.json`): each plugin is self-contained, with skills, agents, hooks, and settings at its own root.

## Test Markers

- `make test` — full gate: lint, the root pytest suite, per-skill test-suite discovery, the vault machinery suite (`make test-machinery`), and the version-bump gate (`make verify-versions`)
- `uv run pytest` — root suite only (`tests/`)
- No custom pytest markers defined

## Custom Exceptions

- `DocsError` (`scripts/stamp.py`) — generated documentation would not regenerate cleanly from source
