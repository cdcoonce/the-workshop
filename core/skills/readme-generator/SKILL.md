---
name: readme-generator
description: Use when the user asks to create, write, generate, update, improve, or refresh the root README.md of a repository, or asks for a project's front-door / landing documentation. Also triggers on "this repo needs a README" or just "README"/"readme" in a codebase context. This skill owns the single root README (the front door) and keeps it current. For a multi-file, in-depth reference set — architecture, module map, data flow, conventions — use repo-reference-docs instead.
---

# README Generator

Create and maintain the single root `README.md` for a code repository by analyzing the actual codebase and asking targeted clarifying questions. A good README is the front door to a codebase — a missing or thin one means every new team member burns hours figuring out what a project does, how to run it, and where to look. This skill reads the code, infers what it can, asks about what it can't, produces a README that gets developers productive fast, and keeps it from going stale.

**Lane.** This skill owns only the root `README.md`. It does not produce the deep multi-file reference set — that is `repo-reference-docs` (`docs/reference/`). When `docs/reference/` exists, link to it from the README's overview rather than duplicating that depth here; keep the README the shallow, orienting front door.

## Workflow

### Step 1: Analyze the codebase

Before asking the user anything, execute a structured four-phase analysis to gather as much context as possible. This reduces the burden on the user — they should only need to fill gaps, not describe things you can already see.

Tag every fact with a confidence level: `[confirmed]` (read from source), `[inferred-high]` (strong evidence), `[inferred-low]` (partial evidence), or `[unknown]`. Low-confidence and unknown findings become clarifying questions in Step 2.

See [references/analysis-phases.md](references/analysis-phases.md) for detailed tool actions, grep patterns, extraction checklists, and record templates.

**Phase 1 — Project Metadata Scan:** Glob for package manager files (`pyproject.toml`, `package.json`, etc.), env templates, Dockerfiles, CI/CD configs, and toolchain files. Read each and extract: project name/version, language, dependencies (categorized with purposes), scripts/commands, environment variables (required vs optional), CI stages, license.

**Phase 2 — Architecture Scan:** Glob for all source files to map directory structure. Grep for entry point markers (`if __name__`, `main()`, etc.) and read each entry point. Build the import graph by grepping for import statements across all source files — classify modules as core (high in-degree), leaf, or orchestrator. Identify the architecture pattern (pipeline, MVC, layered, microservices, event-driven, CLI, monolith) using the indicator checklist. Grep for config-loading patterns to find runtime config files.

**Phase 3 — Deep Module Analysis:** Read each significant source file (prioritized: core → entry point → largest → rest). For each, extract: purpose (one sentence), key exports with signatures, design notes (non-obvious decisions, edge cases, conventions), and internal dependencies. Trace the primary workflow end-to-end through the import graph, labeling what data types flow between modules. For codebases with 8+ source files, dispatch parallel subagents grouped by dependency cluster.

**Phase 4 — Supporting Infrastructure Scan:** Glob for test files and fixtures. Read first 30-50 lines of each test file to build a test-to-module mapping. Grep for custom exception classes and `raise` statements to map the error hierarchy. Scan templates, assets, and existing docs. Extract common error scenarios for the Troubleshooting table.

### Step 2: Ask clarifying questions

After analysis, ask the user about things you couldn't confidently infer. Keep it focused — don't ask about things you already know. Common gaps include:

- **Project purpose**: What problem does this solve? Who uses it? (if not obvious from code)
- **Setup gotchas**: Are there non-obvious prerequisites, VPN requirements, internal package registries, or database setup steps?
- **Key workflows**: What are the 2-3 things a developer does most often with this project?
- **Deployment**: How/where is this deployed? (if not clear from CI/CD configs)
- **Team conventions**: Any naming conventions, branching strategies, or patterns to call out?
- **Contact info**: Who owns/maintains this project? (name + email for the Contact section)

Present your questions concisely. If the codebase is straightforward and you're confident in your analysis, you may only need 1-2 questions — or even none. Use your judgment.

### Step 3: Generate the README.md

Write the README using the full section template in the **README Structure** section of [references/analysis-phases.md](references/analysis-phases.md) — it defines the section skeleton (Table of Contents through License), the badge and Mermaid diagram placeholders, and the horizontal-rule and table formats. Load it before drafting, then apply the badge, diagram, and writing guidance below.

## Shields.io Badges

Always include shields.io badges directly after the `# Title` heading (3-6 badges covering language, framework, key library, package manager, database, infrastructure). See [references/badge-reference.md](references/badge-reference.md) for format, examples, and color suggestions by category.

## Mermaid Diagram Guidelines

Use mermaid diagrams generously — they make architecture, data flows, and processes immediately understandable. A typical README should have **3-6 diagrams**; complex projects (data pipelines, multi-service systems) might have **6-10+**. See [references/mermaid-guidelines.md](references/mermaid-guidelines.md) for when to use each diagram type, best practices, and project-type-specific recommendations.

## Writing Guidelines

- **Be specific over generic.** "Run `npm run dev`" beats "Start the development server." Include actual commands, file paths, and variable names.
- **Write for the new team member.** Assume general engineering skills but zero project context.
- **Bold key terms and product names** on first mention and in overviews. This helps readers scan.
- **Use numbered lists for sequential processes.** "1. **Extracts** data from X. 2. **Transforms** it. 3. **Loads** into Y." — bold the verb.
- **Code examples should be runnable.** Copy from the actual codebase when possible.
- **Environment variable tables are non-negotiable.** List every single one.
- **Troubleshooting in table format** (Symptom | Likely Cause | Fix) — scannable and consistent.
- **Folder structure annotations should be brief.** One short phrase per directory.
- **Always include a Contact section.** Ask the user who maintains the project. Format: `**Name** — email@company.com`.
- **Use `---` horizontal rules** between all major sections for visual structure.

## Output

Save the README as `README.md` in the root of the repository (or the current working directory if no repo root is identifiable). End the file with the provenance footer below. When a `docs/reference/` set exists, add a short "Reference docs" pointer in the overview linking to it.

## Provenance & maintenance

The README carries a provenance footer so it can be kept current instead of silently rotting. As the last line of the file, write an HTML comment (invisible when rendered):

```
<!-- readme-generator: baseline=<commit-sha> covers=<comma,separated,paths> -->
```

- `baseline` — the commit the README was last synced to (`git rev-parse HEAD`).
- `covers` — the README's **front-door anchors**: the dependency/manifest files, env templates, CI configs, and entry points its factual claims derive from. These are the things a README goes stale on.

**Updating (existing README):** if a README already exists, do not blindly overwrite. Read its footer, then `git diff --name-only <baseline>..HEAD -- <covers...>`. If nothing in `covers` changed, leave it alone. If anchors changed, revise only the affected sections (dependencies, commands, env vars, badges), preserve hand-edits and prose, and re-stamp the footer. If there is no footer (older README), confirm with the user before overwriting — they may want to keep parts.

**Checking (read-only):** run `scripts/check_readme.py --readme README.md --repo-root .` to report anchors that moved, disappeared, or changed since baseline. It writes nothing and exits non-zero on drift, so it can gate CI or a pre-promote check.
