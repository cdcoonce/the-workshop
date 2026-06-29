---
name: generate-wiki
description: >
  Bootstrap or update a GitLab-wiki-ready docs directory from codebase analysis. Generates
  architecture docs (what exists), workflow docs (how things run), navigation files, and sync
  infrastructure. Use when creating a wiki, bootstrapping docs, refreshing stale docs,
  or updating docs after code changes.
---

# Generate Wiki Documentation

Build a wiki directory that syncs to GitLab wiki. Two axes: **architecture** (what the code is) and **workflows** (how it runs).

## Mode Detection

- **Wiki directory does not exist** -> Bootstrap mode (Steps 1-6)
- **Wiki directory exists** -> Update mode (Step 7)

## Bootstrap Mode

### Step 1: Discover Project Structure

- [ ] **Ask wiki folder name.** Default: `wiki/`. Confirm with user before proceeding. Use this name (`WIKI_DIR`) for all generated paths.
- [ ] Read `pyproject.toml` / `setup.py` for project name, tech stack, dependencies
- [ ] Glob for `__init__.py` to find packages; identify entrypoints (facade classes, main functions)
- [ ] Map cross-package imports to build dependency graph
- [ ] Identify runtime surfaces: CLI, web apps, jobs, orchestration (Dagster, Airflow, etc.)

Present a **doc plan** to the user listing: chosen folder name, packages, components, and workflows. Get approval before generating.

### Step 2: Generate Architecture Docs

Read source files for each package. Follow templates in [architecture-template.md](references/architecture-template.md).

- [ ] `{WIKI_DIR}/architecture/{package}/overview.md` per package
- [ ] Component docs for significant sub-modules (50+ lines, distinct responsibility)
- [ ] `{WIKI_DIR}/architecture/system-overview.md` (cross-package view)
- [ ] `{WIKI_DIR}/architecture/repo-structure.md` (annotated directory tree)

### Step 3: Generate Workflow Docs

Document each runtime path. Follow templates in [workflow-template.md](references/workflow-template.md).

- [ ] `{WIKI_DIR}/workflows/{package}/` with per-workflow docs
- [ ] Workflow index (`readme.md`) per package listing all workflows with triggers

### Step 4: Create Navigation

- [ ] `{WIKI_DIR}/home.md` — landing page linking all sections
- [ ] `{WIKI_DIR}/_sidebar.md` — full navigation tree with indented nesting
- [ ] All links use relative paths without `.md` extension (GitLab wiki format)

### Step 5: Add Sync Infrastructure

Copy and configure the bundled scripts. See [sync-infrastructure.md](references/sync-infrastructure.md) for setup prerequisites.

- [ ] Copy [scripts/sync_wiki.py](scripts/sync_wiki.py) to the project (e.g., `scripts/sync_wiki.py`)
- [ ] Edit `WIKI_SOURCE` path and `PROJECT_ROOT` depth to match the project layout
- [ ] Edit `SECTION_ORDER` list to match the project's wiki sections
- [ ] Edit sidebar title in `build_sidebar()` to match the project name
- [ ] Insert [scripts/wiki-ci-stage.yml](scripts/wiki-ci-stage.yml) into the project's `.gitlab-ci.yml`
- [ ] Add `wiki` to the `stages:` list in `.gitlab-ci.yml`
- [ ] Adjust the CI trigger branch and `changes:` path to match `WIKI_DIR`
- [ ] Adjust the `python` command path to match where the sync script was placed

### Step 6: Verify

- [ ] All internal links resolve to existing files
- [ ] Every package directory has `overview.md` or `readme.md`
- [ ] Every doc has an `# H1` title (sidebar uses it as display name)
- [ ] `_sidebar.md` covers all docs

## Update Mode

### Step 7: Diff-Aware Refresh

- [ ] Detect existing wiki directory name (glob for `*/architecture/` or `*/workflows/`)
- [ ] Run `git diff --name-only` to identify changed source files
- [ ] Map each changed file to its corresponding doc
- [ ] Re-read source and existing doc; update doc to match current code
- [ ] New files/modules: generate new docs and add to `_sidebar.md`
- [ ] Deleted files: flag orphaned docs for user decision
- [ ] Present changes to user before writing

## Rules

- **Ask first.** Always confirm the wiki folder name in Step 1. Default to `wiki/`.
- **Read before writing.** Never generate docs without reading the source first.
- **Copy, don't regenerate.** Use bundled scripts directly — don't rewrite them from memory.
- **overview.md = directory index.** Every package directory gets one. The sync script uses it as the clickable directory link in the sidebar.
- **Architecture != Workflows.** Architecture = structure, contracts, dependencies. Workflows = runtime steps, triggers, failure modes. Never mix.
- **Scale to project size.** A 3-file script gets one overview. A 50-module monorepo gets full hierarchy.
- **Preserve hand edits.** In update mode, diff against existing docs. Don't blindly overwrite.
- **GitLab wiki links.** Relative paths, no `.md` extension: `[Title](architecture/spot/overview)`
- **Lowercase paths.** Use lowercase for all generated directory and file names.
