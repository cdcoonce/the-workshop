# Repository Walkthrough

## What to Explain

A repository walkthrough builds understanding of a codebase's architecture, key abstractions, and data/control flow.

## Overview Phase

Generate a visual showing:
- **Top-level module structure** — major directories/packages and their responsibilities
- **Dependency flow** — which modules depend on which (arrows show import/call direction)
- **Entry points** — where execution starts (main, CLI, API routes, event handlers)
- **Data flow** — how data moves through the system (input → processing → output)

Best diagram type: **D3 force-directed graph** with modules as nodes, dependencies as edges, entry points highlighted. Alternatively, a **Mermaid flowchart** for simpler repos.

## Drill-Down Sections

Offer these as drill-down options (adapt to what actually exists):

1. **Architecture & boundaries** — how the codebase is divided, what each layer owns
2. **Core data model** — key types/classes/schemas that everything revolves around
3. **Request/data flow** — trace a typical operation end-to-end
4. **Configuration & environment** — how the app is configured, what env vars matter
5. **Testing strategy** — how tests are organized, what's covered, how to run them
6. **Build & deploy** — CI/CD pipeline, build steps, deployment targets
7. **Key patterns & conventions** — naming, error handling, logging, common abstractions

## Exploration Strategy

- Start with `ls` and `find` to understand directory structure.
- Read README, CLAUDE.md, AGENTS.md, package.json/pyproject.toml for project metadata.
- Check git log for recent activity and active areas.
- Read key entry point files to understand the main flow.
- Don't read every file — read enough to explain the architecture confidently.

## Visual Updates on Drill-Down

When the user drills into a section, generate a focused visual:
- **Architecture** → layered diagram or module boundary map
- **Data model** → ER diagram or class diagram (Mermaid)
- **Request flow** → sequence diagram (Mermaid)
- **Config** → table/tree of configuration options
- **Testing** → treemap of test coverage by module (D3)
