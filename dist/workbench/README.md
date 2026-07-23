# workbench

The complete Workshop toolkit — every skill, agent, methodology doc, and safety hook in one package. Plan, build, and ship with the full first-party dev workflow on Claude Code, Codex, and Cortex Code.

## Conventions

- Test-driven development: write the failing test first
- Regenerate docs and dist after changing any component
- Progressive disclosure over monolithic instructions
- Conventional commits; stage explicitly, never git add .
- Repo artifacts stay in-repo; machine-local skill output defaults to ~/.workshop/<skill>/ unless a destination is configured

## Skills

| Skill | Summary |
| --- | --- |
| `/chart-taste` | Applies chart-design taste to React data visualization — a chart-type decision tree and adjustable dials (annotation density, complexity, color restraint) to stop charts from being technically-rendered-but-uninformative. |
| `/commit` | Git commit workflow with enforced conventional commit style. |
| `/create-hook` | Create and register Claude Code hooks (PreToolUse, PostToolUse) as Python scripts. |
| `/daa-code-review` | AI-powered code quality analysis for Python, Markdown, and Mermaid diagrams. |
| `/dagster-expert` | Expert guidance for working with Dagster and the dg CLI. |
| `/dbt-expert` | Expert guidance for working with dbt Core. |
| `/design-an-interface` | Generate multiple radically different interface designs for a module using parallel sub-agents. |
| `/dev-cycle` | Use when user says "dev cycle", "development workflow", "full development pipeline", or invokes /dev-cycle to take a GitHub-issues-driven feature from brainstorm through a merged PR. |
| `/dignified-python` | Production Python coding standards with automatic version detection (3.10-3.13). |
| `/finish-branch` | Use when implementation is complete, all tests pass, and you need to decide how to integrate a finished development branch — merge, open a PR, keep it, or discard it. |
| `/github-cli` | GitHub CLI (gh) integration for managing issues, pull requests, branches, commits, and code reviews directly from the terminal. |
| `/gitlab-mr-create` | Create GitLab merge requests with `glab` using the `HEAD` conventional-commit subject as the exact title, a Markdown description file with real newlines, and API read-back verification. |
| `/grill-me` | Interview the user relentlessly about a plan or design until reaching shared understanding, resolving each branch of the decision tree. |
| `/mr-merge-order` | Use when several MRs or PRs are open against the same branch and the user asks which to merge first, whether one blocks another, why merging one breaks another, or in what order to land a queue. |
| `/mr-review-fixes` | Use when a user says an MR, PR, merge request, or pull request has review feedback, review comments, changes requested, an approval blocker, or asks to see what needs to be fixed after review. |
| `/plan-ceo-review` | CEO/founder-mode review that rethinks a plan to find the 10-star product. |
| `/prd-to-issues` | Break a PRD into independently-grabbable GitHub issues using tracer-bullet vertical slices, with executor-ready issue bodies an autonomous agent can build from directly. |
| `/prd-to-plan` | Turn a PRD into a multi-phase implementation plan using tracer-bullet vertical slices, saved as a local Markdown file in docs/plans/. |
| `/project-context` | Generate or update the `.claude/docs/project.md` file that gives Claude project-specific context. |
| `/react-ui-ux` | Applies deliberate design taste to React UI generation — adjustable dials (variance, motion, density) and explicit anti-genericness rules to stop AI-generated components from defaulting to the generic shadcn/Tailwind look. |
| `/readme-generator` | Use when the user asks to create, write, generate, update, or improve a README for any project or repository, or asks for project documentation in markdown. |
| `/request-refactor-plan` | Use when user wants to plan a refactor, create a refactoring RFC, break a refactor into safe incremental steps, or find architectural improvement opportunities (deepening shallow modules, consolidating tightly-coupled code, making a codebase more testable or AI-navigable). |
| `/security-review` | Security code review for vulnerabilities with confidence-based reporting. |
| `/setup-pre-commit` | Set up pre-commit hooks for the current repo. |
| `/shared-tree-safety` | Protect work when a git working tree or worktree may be shared with a live autonomous agent or another session. |
| `/tdd` | Test-driven development with red-green-refactor loop. |
| `/transcript-notes` | Turn a YouTube lecture/talk or a raw transcript (VTT, SRT, or plain text) into a readable Obsidian-markdown study note — imposed structure, reconstructed LaTeX with plain-word glosses, flagged missing visuals, and per-section reading prompts. |
| `/triage-issue` | Use when user reports a bug, wants to file an issue, mentions "triage", or wants to investigate and plan a fix for a problem. |
| `/triage-quarantine` | Diagnose why an autonomous agent run failed, quarantined, or was rejected before re-running anything. |
| `/using-workflow` | Use when starting any conversation or task in this project — establishes precedence between instructions and skills, requires invoking any skill that might apply, and sets the order skills run in before any response or action. |
| `/write-a-prd` | Use when user wants to write a PRD, create a product requirements document, or plan a new feature. |

## Agents

| Agent | Role | Summary |
| --- | --- | --- |
| analysis-builder | `implementer` | Builds data analysis notebooks and scripts with pandas, SQL, and visualization |
| api-builder | `implementer` | Builds Python API endpoints with FastAPI, Flask, or Lambda |
| backend-builder | `implementer` | Builds backend services with Node.js, databases, and APIs |
| code-reviewer | `reviewer` | Reviews code for quality, structure, and correctness |
| data-quality-reviewer | `reviewer` | Reviews data pipelines for correctness, completeness, and reliability |
| frontend-builder | `implementer` | Builds frontend components with React, TypeScript, and modern CSS |
| pipeline-builder | `implementer` | Builds data pipelines with ETL/ELT patterns and orchestration |
| security-reviewer | `reviewer` | Reviews Python APIs for security vulnerabilities and auth issues |
| tdd-implementer | `implementer` | Implements features using test-driven development |
| ux-reviewer | `reviewer` | Reviews frontend code for UX quality, accessibility, and consistency |

## CLAUDE.md Template

Copy the following into your project's `CLAUDE.md` to reference this plugin:

```
# Project Name

## Plugins

This project uses the workbench plugin for Claude Code configuration.

## Methodology

See plugin documentation for TDD, root cause tracing, and subagent development processes.
```
