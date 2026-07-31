# Project Walkthrough

## What to Explain

A project walkthrough builds understanding of an initiative holistically — goals, stakeholders, current state, architecture, risks, and trajectory.

## Overview Phase

Generate a visual showing:
- **Project map** — components/workstreams, their status, and relationships
- **Stakeholder landscape** — who owns what, who depends on what, decision-makers
- **Timeline/status** — what's done, what's in-progress, what's blocked
- **Architecture context** — how this project's technical components fit into the broader system

Best diagram type: **D3 force-directed graph** or **Mermaid flowchart** showing project components as nodes with status-colored borders (green=done, yellow=active, red=blocked, gray=planned).

## Drill-Down Sections

1. **Goals & scope** — what's the project trying to achieve, what's explicitly out of scope
2. **Architecture** — technical structure, key design decisions, trade-offs made
3. **Current state** — what's done, what's in-flight, what's blocked and why
4. **Risks & dependencies** — what could derail this, what external factors matter
5. **Key decisions** — significant choices that shaped the project, with rationale
6. **People & roles** — who's involved, who owns what, who to talk to about what

## Exploration Strategy

- Look for project documentation (README, ADRs, planning docs, tickets).
- Check git history for activity patterns and contributors.
- Read any existing status documents or indexes.
- If in a vault/knowledge system, check for related notes, decisions, meeting records.
- Ask the user for context that isn't written down (organizational politics, verbal agreements).

## Visual Updates on Drill-Down

- **Architecture** → system diagram with component boundaries and data flow
- **Current state** → Gantt-style or kanban visual of workstream status
- **Risks** → risk matrix (likelihood × impact) as a D3 scatter plot
- **People** → org chart / RACI-style responsibility visual
