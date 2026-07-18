# workbench

The complete claude-workflow toolkit — every skill, agent, methodology doc, and safety hook in one package. Plan, build, and ship with the full first-party dev workflow.

## Conventions

- Test-driven development: write the failing test first
- Regenerate docs and dist after changing any component
- Progressive disclosure over monolithic instructions
- Conventional commits; stage explicitly, never git add .

## Skills

| Skill | Summary |
| --- | --- |
| `/add-claude-workflow-hook` | Design and ship a new core hook in this repo (claude-workflow) — fetch the exact event schema, write a stdlib-only fail-open script, TDD it against real subprocess+git behavior, wire it into every affected preset, and push to both GitHub and GitLab. |
| `/chart-taste` | Applies chart-design taste to React data visualization — a chart-type decision tree and adjustable dials (annotation density, complexity, color restraint) to stop charts from being technically-rendered-but-uninformative. |
| `/commit` | Git commit workflow with enforced conventional commit style. |
| `/create-hook` | Create and register Claude Code hooks (PreToolUse, PostToolUse) as Python scripts. |
| `/daa-code-review` | AI-powered code quality analysis for Python, Markdown, and Mermaid diagrams. |
| `/dagster-expert` | Expert guidance for working with Dagster and the dg CLI. |
| `/dbt-expert` | Expert guidance for working with dbt Core. |
| `/deploy` | Deploy the portfolio chat agent Lambda function to AWS. |
| `/design-an-interface` | Generate multiple radically different interface designs for a module using parallel sub-agents. |
| `/dev-cycle` | Use when user says "dev cycle", "development workflow", "full development pipeline", or invokes /dev-cycle to take a GitHub-issues-driven feature from brainstorm through a merged PR. |
| `/dignified-python` | Production Python coding standards with automatic version detection (3.10-3.13). |
| `/finish-branch` | Use when implementation is complete, all tests pass, and you need to decide how to integrate a finished development branch — merge, open a PR, keep it, or discard it. |
| `/github-cli` | GitHub CLI (gh) integration for managing issues, pull requests, branches, commits, and code reviews directly from the terminal. |
| `/grill-me` | Interview the user relentlessly about a plan or design until reaching shared understanding, resolving each branch of the decision tree. |
| `/improve-codebase-architecture` | Explore a codebase to find opportunities for architectural improvement, focusing on making the codebase more testable by deepening shallow modules. |
| `/improve-skill` | Use when user says "improve skill", "benchmark skill", "make skill better", or invokes /improve-skill to raise a skill's benchmark pass rate before merging a PR. |
| `/persona-builder` | Build an installable, portable, self-tuning coach/sounding-board persona for a named owner. |
| `/plan-ceo-review` | CEO/founder-mode review that rethinks a plan to find the 10-star product. |
| `/prd-to-issues` | Break a PRD into independently-grabbable GitHub issues using tracer-bullet vertical slices. |
| `/prd-to-plan` | Turn a PRD into a multi-phase implementation plan using tracer-bullet vertical slices, saved as a local Markdown file in docs/plans/. |
| `/project-context` | Generate or update the `.claude/docs/project.md` file that gives Claude project-specific context. |
| `/react-ui-ux` | Applies deliberate design taste to React UI generation — adjustable dials (variance, motion, density) and explicit anti-genericness rules to stop AI-generated components from defaulting to the generic shadcn/Tailwind look. |
| `/readme-generator` | Use when the user asks to create, write, generate, update, or improve a README for any project or repository, or asks for project documentation in markdown. |
| `/request-refactor-plan` | Use when user wants to plan a refactor, create a refactoring RFC, or break a refactor into safe incremental steps. |
| `/security-review` | Security code review for vulnerabilities with confidence-based reporting. |
| `/setup-pre-commit` | Set up pre-commit hooks for the current repo. |
| `/tdd` | Test-driven development with red-green-refactor loop. |
| `/triage-issue` | Use when user reports a bug, wants to file an issue, mentions "triage", or wants to investigate and plan a fix for a problem. |
| `/using-workflow` | Use when starting any conversation or task in this project — establishes precedence between instructions and skills, requires invoking any skill that might apply, and sets the order skills run in before any response or action. |
| `/write-a-prd` | Use when user wants to write a PRD, create a product requirements document, or plan a new feature. |
| `/write-a-skill` | Create new agent skills with proper structure, progressive disclosure, and bundled resources. |

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
| qa-tester | `qa-tester` | Evaluates skill instructions against a test suite. |
| security-reviewer | `reviewer` | Reviews Python APIs for security vulnerabilities and auth issues |
| skill-analyst | `analyst` | Analyzes skill instructions for weaknesses across surface, behavioral, and adversarial tiers. |
| skill-builder | `implementer` | Builds Claude Code skills, hooks, and MCP server integrations |
| skill-reviewer | `reviewer` | Reviews Claude Code skills and hooks for correctness and best practices |
| skill-writer | `skill-writer` | Rewrites Claude Code skills to fix failing test cases. |
| strategy | `strategy` | Analyzes stalled skill improvement runs and proposes a concrete rewrite strategy. |
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
