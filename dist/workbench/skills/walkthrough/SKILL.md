---
name: walkthrough
description: >
  Interactive visual walkthrough of any artifact — repos, merge requests, emails,
  projects, or databases. Detects artifact type, generates rich Mermaid + D3 visuals
  in the browser, and lets the user drill down interactively until understanding is
  complete. Produces a summary note at the end.
  Use when: user says "walk me through", "walkthrough this repo", "walk me through
  this MR", "walk me through this email", "walk me through this project",
  "walk me through this database", "explain this repo/MR/project to me".
---

# Walkthrough — Interactive Visual Explanation

## Philosophy

Understanding is not a wall of text. It's a layered, visual, conversational process. This skill takes any artifact the user provides — a codebase, a merge request, an email draft, a project, a data model — and builds comprehension through progressive disclosure: start with the big picture, render it visually, then let the user steer deeper into what matters to them.

The agent is the **explainer**. The user is the **learner**. The conversation is driven by curiosity, not a fixed agenda.

## Artifact Detection

When invoked, identify the artifact type from context:

| Signal | Type | Reference |
|--------|------|-----------|
| User is in a git repo, mentions "this repo", or asks about codebase structure | **Repository** | [references/repo.md](references/repo.md) |
| User provides an MR/PR URL, mentions a branch, or asks about a diff | **Merge Request** | [references/mr.md](references/mr.md) |
| User pastes or references an email, Slack message, or Teams chat | **Email/Message** | [references/email.md](references/email.md) |
| User asks about a project, initiative, or workstream holistically | **Project** | [references/project.md](references/project.md) |
| User asks about tables, schemas, ERDs, data lineage, or a database | **Database** | [references/database.md](references/database.md) |

Load the matching reference file for type-specific guidance on what to explain and how to structure the visual.

If the type is ambiguous, ask with `AskUserQuestion` before proceeding.

## Process

### Phase 1: Gather & Orient

1. Identify the artifact type (see table above).
2. Load the type-specific reference file.
3. Read/explore the artifact thoroughly using appropriate tools (filesystem for repos, git for MRs, user-provided content for emails).
4. Build an internal model of the artifact's structure, key components, and relationships.

### Phase 2: Overview Visual

5. Generate an HTML page with a high-level visual representation of the artifact:
   - Use **Mermaid** (loaded from CDN) for standard diagrams: flowcharts, sequence diagrams, ER diagrams, class diagrams, architecture graphs.
   - Use **D3.js** (loaded from CDN) for custom interactive visuals: force-directed graphs, treemaps, zoomable hierarchies, annotated timelines.
   - The HTML is a local file opened in the browser — full CDN access, no sandbox restrictions.
   - See [references/visuals.md](references/visuals.md) for rendering guidance.
6. Open the HTML in the browser and present a concise textual overview alongside it — the "map" of what you're looking at.

### Phase 3: Interactive Drill-Down

7. Ask the user what they want to explore deeper using `AskUserQuestion`:
   - Options should be the major sections/components identified in the overview.
   - Always include a "I understand enough — wrap up" option.
8. For the chosen section:
   - Explain it in depth with specifics (code references, data flows, decisions, implications).
   - Update or generate a new focused visual if it helps understanding.
   - Surface connections to other parts of the artifact.
9. Repeat steps 7–8 until the user signals they're done.

### Phase 4: Summary

10. Produce a markdown summary note capturing:
    - What the artifact is and its purpose.
    - Key structural insights (architecture, flow, relationships).
    - Anything surprising or noteworthy surfaced during drill-downs.
    - Inline Mermaid diagrams (no HTML dependency) for portability.
11. Ask the user where to save the summary (or suggest a default location based on context).

## Depth Calibration by Artifact Type

- **Repository / Project** → Progressive. Start with architecture-level, drill to module-level, drill to function-level only on request.
- **Merge Request** → Change-focused. Start with "what changed and why," drill into specific files/hunks.
- **Email / Message** → Concise. Tone, structure, subtext, how it will land. One level of depth is usually enough.
- **Database** → Relational. Start with entity relationships, drill into specific tables/columns/lineage.

## Visual Generation Rules

1. Every HTML file must be self-contained (inline styles, CDN script tags, no local dependencies).
2. Load Mermaid from `https://cdn.jsdelivr.net/npm/mermaid/dist/mermaid.min.js`.
3. Load D3 from `https://cdn.jsdelivr.net/npm/d3@7/dist/d3.min.js`.
4. Use a dark theme by default (dark background, light text, colored accents) — matches IDE context.
5. Make visuals **interactive** where possible: hover tooltips, clickable nodes, zoomable areas.
6. Keep diagram complexity manageable — 15-20 nodes max per view. Break larger systems into focused sub-diagrams.
7. Write the HTML to a temp file and open it with the browser tool.

## Directives

1. **Visuals are not optional.** Every walkthrough MUST include at least one rendered HTML visual. Text-only explanations defeat the purpose of this skill.
2. **Explain, don't critique.** This is not a review skill. The goal is understanding, not judgment. State what things ARE, not whether they're good or bad.
3. **Let the user steer.** After the overview, the user chooses what to explore. Don't impose a fixed order.
4. **Stay concrete.** Reference specific files, lines, tables, fields, sentences. Abstract explanations without grounding are useless.
5. **Depth adapts to the artifact.** Don't over-explain an email. Don't under-explain a database schema.
6. **Produce the summary.** Every walkthrough ends with a persistent markdown note. The browser visuals are ephemeral; the summary is the durable artifact.
7. **Use `AskUserQuestion` for navigation.** Don't ask "what do you want to explore?" as plain text. Use the tool with concrete options derived from the artifact's structure.

## When to Stop

The walkthrough is complete when:
- The user selects "I understand enough — wrap up" or equivalent.
- The summary note has been produced and saved.
