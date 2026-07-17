# full-stack

React/Next.js frontend + Python backend

## Conventions

- Separate frontend and backend test runners
- Shared fixture patterns across the stack
- Typed API contracts between layers

## Skills

| Skill | Summary |
| --- | --- |
| `/add-claude-workflow-hook` | Design and ship a new core hook in this repo (claude-workflow) — fetch the exact event schema, write a stdlib-only fail-open script, TDD it against real subprocess+git behavior, wire it into every affected preset, and push to both GitHub and GitLab. |
| `/commit` | Git commit workflow with enforced conventional commit style. |
| `/create-hook` | Create and register Claude Code hooks (PreToolUse, PostToolUse) as Python scripts. |
| `/daa-code-review` | AI-powered code quality analysis for Python, Markdown, and Mermaid diagrams. |
| `/design-an-interface` | Generate multiple radically different interface designs for a module using parallel sub-agents. |
| `/dev-cycle` | Orchestrate the full GitHub-issues-driven development lifecycle. |
| `/dignified-python` | Production Python coding standards with automatic version detection (3.10-3.13). |
| `/finish-branch` | Use when implementation is complete, all tests pass, and you need to decide how to integrate a finished development branch — merge, open a PR, keep it, or discard it. |
| `/github-cli` | GitHub CLI (gh) integration for managing issues, pull requests, branches, commits, and code reviews directly from the terminal. |
| `/grill-me` | Interview the user relentlessly about a plan or design until reaching shared understanding, resolving each branch of the decision tree. |
| `/improve-codebase-architecture` | Explore a codebase to find opportunities for architectural improvement, focusing on making the codebase more testable by deepening shallow modules. |
| `/improve-skill` | Benchmark-driven skill improvement pipeline. |
| `/plan-ceo-review` | CEO/founder-mode plan review. |
| `/prd-to-issues` | Break a PRD into independently-grabbable GitHub issues using tracer-bullet vertical slices. |
| `/prd-to-plan` | Turn a PRD into a multi-phase implementation plan using tracer-bullet vertical slices, saved as a local Markdown file in docs/plans/. |
| `/project-context` | Generate or update the `.claude/docs/project.md` file that gives Claude project-specific context. |
| `/react-ui-ux` | Applies deliberate design taste to React UI generation — adjustable dials (variance, motion, density) and explicit anti-genericness rules to stop AI-generated components from defaulting to the generic shadcn/Tailwind look. |
| `/readme-generator` | Generate comprehensive, high-quality README.md files for code repositories. |
| `/request-refactor-plan` | Create a detailed refactor plan with tiny commits via user interview, then file it as a GitHub issue. |
| `/security-review` | Security code review for vulnerabilities with confidence-based reporting. |
| `/setup-pre-commit` | Set up pre-commit hooks for the current repo. |
| `/tdd` | Test-driven development with red-green-refactor loop. |
| `/triage-issue` | Triage a bug or issue by exploring the codebase to find root cause, then create a GitHub issue with a TDD-based fix plan. |
| `/write-a-prd` | Create a PRD through user interview, codebase exploration, and module design, then submit as a GitHub issue. |
| `/write-a-skill` | Create new agent skills with proper structure, progressive disclosure, and bundled resources. |

## Agents

| Agent | Role | Summary |
| --- | --- | --- |
| backend-builder | `implementer` | Builds backend services with Node.js, databases, and APIs |
| code-reviewer | `reviewer` | Reviews code for quality, structure, and correctness |
| frontend-builder | `implementer` | Builds frontend components with React, TypeScript, and modern CSS |
| qa-tester | `qa-tester` | Evaluates skill instructions against a test suite. |
| skill-analyst | `analyst` | Analyzes skill instructions for weaknesses across surface, behavioral, and adversarial tiers. |
| skill-writer | `skill-writer` | Rewrites Claude Code skills to fix failing test cases. |
| strategy | `strategy` | Analyzes stalled skill improvement runs and proposes a concrete rewrite strategy. |
| tdd-implementer | `implementer` | Implements features using test-driven development |
| ux-reviewer | `reviewer` | Reviews frontend code for UX quality, accessibility, and consistency |

## CLAUDE.md Template

Copy the following into your project's `CLAUDE.md` to reference this plugin:

```
# Project Name

## Plugins

This project uses the full-stack plugin for Claude Code configuration.

## Methodology

See plugin documentation for TDD, root cause tracing, and subagent development processes.
```
