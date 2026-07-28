# workshop-maintainer

Tools for auditing and maintaining The Workshop's skills, presets, and distribution boundaries

## Conventions

- Inventory before reorganizing
- Keep source ownership distinct from distribution membership
- Regenerate docs and dist after changing any component

## Skills

| Skill | Summary |
| --- | --- |
| `/add-the-workshop-hook` | Design and ship a new core hook in this repo (the-workshop) — fetch the exact event schema, write a stdlib-only fail-open script, TDD it against real subprocess+git behavior, wire it into every affected preset, and push to both GitHub and GitLab. |
| `/commit` | Git commit workflow with enforced conventional commit style. |
| `/daa-code-review` | AI-powered code quality analysis for Python, Markdown, and Mermaid diagrams. |
| `/grill-me` | Interview the user relentlessly about a plan or design until reaching shared understanding, resolving each branch of the decision tree. |
| `/improve-skill` | Use when user says "improve skill", "benchmark skill", "make skill better", or invokes /improve-skill to raise a skill's benchmark pass rate before merging a PR. |
| `/land-skill-candidate` | Take an already-identified skill candidate — a named gap or improvement surfaced against a skill this repo owns, often from a /wrap-up session or similar review elsewhere — and ship it into The Workshop: locate the canonical source, apply the smallest fix, run the full gate sequence, and land it via branch to PR to dev on GitHub. |
| `/persona-builder` | Build an installable, portable, self-tuning coach/sounding-board persona for a named owner. |
| `/skill-inventory` | Audits agent skills and their package boundaries. |
| `/sync-gitlab-dev` | Push this repo's GitHub dev to GitLab as a reviewable merge request into GitLab dev, since GitLab is a manually-updated downstream copy (no auto-mirror bot) with its own 1-approval dev gate. |
| `/tdd` | Test-driven development with red-green-refactor loop. |
| `/using-workflow` | Use when starting any conversation or task in this project — establishes precedence between instructions and skills, requires invoking any skill that might apply, and sets the order skills run in before any response or action. |
| `/workshop-skill-creator` | Creates and revises skills owned by The Workshop repository. |

## Agents

| Agent | Role | Summary |
| --- | --- | --- |
| qa-tester | `qa-tester` | Evaluates skill instructions against a test suite. |
| skill-analyst | `analyst` | Analyzes skill instructions for weaknesses across surface, behavioral, and adversarial tiers. |
| skill-builder | `implementer` | Builds Claude Code skills, hooks, and MCP server integrations |
| skill-reviewer | `reviewer` | Reviews Claude Code skills and hooks for correctness and best practices |
| skill-writer | `skill-writer` | Rewrites Claude Code skills to fix failing test cases. |
| strategy | `strategy` | Analyzes stalled skill improvement runs and proposes a concrete rewrite strategy. |

## CLAUDE.md Template

Copy the following into your project's `CLAUDE.md` to reference this plugin:

```
# Project Name

## Plugins

This project uses the workshop-maintainer plugin for Claude Code configuration.

## Methodology

See plugin documentation for TDD, root cause tracing, and subagent development processes.
```
