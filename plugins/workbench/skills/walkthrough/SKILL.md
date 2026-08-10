---
name: walkthrough
description: >
  Interactive visual walkthrough of any artifact — repos, merge requests, emails,
  projects, or databases. Detects artifact type, generates rich Mermaid + D3 visuals
  in the browser, and lets the user drill down interactively until understanding is
  complete. Produces a summary note at the end. Stateful — persists progress to
  .workbench/walkthrough/ and can resume across sessions.
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

## State Management

The walkthrough skill is **stateful and resumable**. All state persists to `.workbench/walkthrough/` in the project root.

### Directory Structure

```
.workbench/walkthrough/
├── index.md                        # Log of all walkthroughs in this project
├── <slug>/                         # One directory per walkthrough session
│   ├── state.json                  # Session state (phase, progress, findings)
│   ├── summary.md                  # The final summary note (written at end)
│   ├── overview.html               # The initial overview visual
│   └── drilldown-<section>.html    # Drill-down visuals (named by section)
```

### state.json Schema

```json
{
  "artifact_type": "repository",
  "artifact_name": "the-workshop",
  "slug": "the-workshop-repo",
  "created": "2026-07-31T20:00:00Z",
  "updated": "2026-07-31T20:45:00Z",
  "phase": "drill-down",
  "status": "in-progress",
  "sections": {
    "architecture": { "status": "explored", "summary": "..." },
    "data-model": { "status": "explored", "summary": "..." },
    "request-flow": { "status": "pending" },
    "config": { "status": "pending" },
    "testing": { "status": "pending" },
    "build-deploy": { "status": "pending" }
  },
  "key_findings": [
    "Plugin system uses directory-convention discovery",
    "Dist is generated from presets via build_preset script"
  ],
  "drill_down_history": [
    { "section": "architecture", "timestamp": "2026-07-31T20:15:00Z" },
    { "section": "data-model", "timestamp": "2026-07-31T20:30:00Z" }
  ]
}
```

### State Rules

1. **Create `.workbench/walkthrough/` if it doesn't exist.** Add `.workbench/` to `.gitignore` if not already present.
2. **Derive `<slug>` from the artifact** (kebab-case, e.g. `the-workshop-repo`, `mr-547`, `q3-planning-email`).
3. **Write `state.json` at every phase transition** — after overview, after each drill-down, on wrap-up.
4. **On invocation, check for existing state first:**
   - If `.workbench/walkthrough/<slug>/state.json` exists and `status` is `"in-progress"`:
     - Read the state, summarize where you left off, and ask if the user wants to **resume** or **start fresh**.
   - If resuming: skip to the current phase, present unexplored sections as drill-down options.
   - If starting fresh: archive the old directory (rename to `<slug>-<date>`) and begin anew.
5. **Track explored sections** — after each drill-down, update the section's status to `"explored"` and write a one-line summary of what was learned.
6. **Accumulate key findings** — noteworthy discoveries go into `key_findings` as the session progresses. These feed the final summary.
7. **Mark `status: "complete"` when the summary is produced.**
8. **Append to `index.md` on completion:** a line linking to the slug's summary with date, artifact type, and status.

## Process

### Phase 1: Gather & Orient

1. Check for existing state (see State Rules #4 above).
2. Identify the artifact type (see detection table).
3. Load the type-specific reference file.
4. Read/explore the artifact thoroughly using appropriate tools (filesystem for repos, git for MRs, user-provided content for emails).
5. Build an internal model of the artifact's structure, key components, and relationships.
6. Initialize `state.json` with `phase: "overview"`, all identified sections as `"pending"`.

### Phase 2: Overview Visual

7. Generate an HTML page with a high-level visual representation of the artifact:
   - Use **Mermaid** (loaded from CDN) for standard diagrams: flowcharts, sequence diagrams, ER diagrams, class diagrams, architecture graphs.
   - Use **D3.js** (loaded from CDN) for custom interactive visuals: force-directed graphs, treemaps, zoomable hierarchies, annotated timelines.
   - The HTML is a local file — full CDN access, no sandbox restrictions.
   - See [references/visuals.md](references/visuals.md) for rendering guidance.
8. Save to `.workbench/walkthrough/<slug>/overview.html` and open in the browser.
9. Present a concise textual overview — the "map" of what you're looking at.
10. Update `state.json`: `phase: "drill-down"`.

### Phase 3: Interactive Drill-Down

11. Ask the user what they want to explore deeper using `AskUserQuestion`:
    - Options = sections with `status: "pending"`.
    - Already-explored sections shown as disabled/noted (so user knows what's covered).
    - Always include a "I understand enough — wrap up" option.
12. For the chosen section:
    - Explain it in depth with specifics (code references, data flows, decisions, implications).
    - Generate a focused visual if it helps → save to `drilldown-<section>.html`, open in browser.
    - Surface connections to other parts of the artifact.
    - Record key findings.
13. Update `state.json`: mark section as `"explored"`, append to `drill_down_history`, update `key_findings`.
14. Repeat steps 11–13 until the user signals done.

### Phase 4: Summary

15. Produce a markdown summary note capturing:
    - What the artifact is and its purpose.
    - Key structural insights (architecture, flow, relationships).
    - All key findings accumulated during drill-downs.
    - Which sections were explored vs. skipped (transparency).
    - Inline Mermaid diagrams (no HTML dependency) for portability.
16. Save to `.workbench/walkthrough/<slug>/summary.md`.
17. Update `state.json`: `status: "complete"`, `phase: "done"`.
18. Append to `index.md`.

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
7. Save HTML visuals to `.workbench/walkthrough/<slug>/` and open them with the browser tool.

## Directives

1. **Visuals are not optional.** Every walkthrough MUST include at least one rendered HTML visual. Text-only explanations defeat the purpose of this skill.
2. **Explain, don't critique.** This is not a review skill. The goal is understanding, not judgment. State what things ARE, not whether they're good or bad.
3. **Let the user steer.** After the overview, the user chooses what to explore. Don't impose a fixed order.
4. **Stay concrete.** Reference specific files, lines, tables, fields, sentences. Abstract explanations without grounding are useless.
5. **Depth adapts to the artifact.** Don't over-explain an email. Don't under-explain a database schema.
6. **Produce the summary.** Every walkthrough ends with a persistent markdown note saved to `.workbench/walkthrough/<slug>/summary.md`.
7. **Use `AskUserQuestion` for navigation.** Don't ask "what do you want to explore?" as plain text. Use the tool with concrete options derived from the artifact's structure.
8. **State is sacred.** Write `state.json` at every transition. A crash between sessions must not lose progress.
9. **Resume gracefully.** On re-invocation, check for existing state and offer to continue. Never silently overwrite an in-progress walkthrough.

## When to Stop

The walkthrough is complete when:
- The user selects "I understand enough — wrap up" or equivalent.
- The summary note has been produced and saved to `.workbench/walkthrough/<slug>/summary.md`.
- `state.json` shows `status: "complete"`.
