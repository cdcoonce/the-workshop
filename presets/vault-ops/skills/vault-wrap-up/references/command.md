# /wrap-up — Session Audit and Cleanup

Audit all notes created or modified during this session. Validate quality, fix minor issues, and flag major ones.

## Process

1. **Identify session changes**: Use `git diff --name-only` and `git status` to find all notes created or modified this session.

2. **Validate each note**:
   - Check frontmatter: date, description, tags, type-specific fields
   - Check wikilinks: notes >300 chars must have at least one `[[link]]`
   - Check folder placement: is the note in the right directory for its type?

3. **Check index synchronization**:
   - Scan `work/Index.md` — are all active work notes listed?
   - Scan `personal/Index.md` — are all personal notes listed?
   - Scan `perf/Brag Doc.md` — were any wins captured today?
   - Scan `brain/Memories.md` — does it need updating?
   - Scan `brain/Key Decisions.md` — were any decisions made today that aren't recorded?

4. **Find orphan notes**: Notes without any incoming or outgoing wikilinks.

5. **Surface uncaptured wins**: Review today's work for impact statements, completed milestones, or positive outcomes not yet in the Brag Doc.

6. **Harvest decisions**: Review the session for significant decisions — architecture choices, tooling selections, process or convention changes, anything whose _why_ you'd want to recover months later. For each one not already recorded, draft an entry for `brain/Key Decisions.md`: what was decided, the context/why, alternatives considered, and the date. Link it (`[[wikilink]]`) to the notes, projects, or people it affects. This is the durable hand-off that keeps the vault self-sufficient — decisions live in the graph, never only in chat or auto-memory. Confirm net-new entries with the user before writing if the decision is ambiguous.

7. **Extract skill candidates**: Scan the session for repeatable patterns that aren't yet a skill. Look for:
   - Workflows Claude had to figure out from scratch that would benefit from codified instructions
   - Moments a skill was invoked but felt limited or incomplete (like today's `repo-crash-course` map structure fix)
   - New task types handled well enough to be reusable
   - Repeated multi-step sequences that could be a single `/command`

   For each candidate: write a one-line description and a suggested skill name. Present the list and ask the user to approve before creating anything. Approved candidates go to `reference/skills/drafts/<skill-name>/SKILL.md` as stubs for later refinement. Dismissed candidates are dropped. **Never auto-create a skill without user approval.**

8. **Fix obvious issues in-place**: missing date from git history, trivial frontmatter gaps, a missing wikilink with an obvious target. Fix silently; only ask about ambiguous cases.

9. **Refresh the rolling handoff** (`/handoff`): rewrite `.brain/handoff-<context>.md` (pick the file via `.vault-context`) as a fresh digest — _resume-from-here / where we are / what's running / open threads / mode_ — so the next session resumes accurately. This is the connective tissue that makes the next `/standup` correct: `session-start.py` injects this file at every session start. Overwrite in place; keep it lean (it's a digest, not a log). Fold in the open threads and next steps surfaced by the audit above. See `/handoff` for the full procedure.

10. **Commit & push** (`/sync`): commit the audited fixes, the harvested decisions/wins, and the refreshed handoff, then push — so the handoff and today's work reach the other machine. Without this, the refreshed handoff never leaves this machine and the next session (here or elsewhere) resumes from stale state.

11. **Report**:

- For each note audited, report: ✓ (pass) or ✗ (issue found + what it is)
- Confirm the handoff was refreshed and the session pushed
- Flag major issues for user approval (e.g., note in wrong folder, missing description)

## Output Format

```
## Session Audit

### Notes Reviewed
- ✓ work/active/pipeline-redesign.md — all checks pass
- ✗ work/1-1/Jane 2026-04-04.md — missing wikilink to [[Jane Smith]]

### Index Status
- work/Index.md: ✓ up to date
- perf/Brag Doc.md: ⚠️ no new entries today

### Orphan Notes
- (none found)

### Uncaptured Wins
- "Shipped the new data quality dashboard" in pipeline-redesign.md → suggest adding to Brag Doc

### Decisions Harvested
- "Adopted workspace-scoped CLAUDE.md" → drafted entry in brain/Key Decisions.md

### Skill Candidates
- `repo-map-mermaid` — skill for generating Mermaid-based repo maps → approved, stub created
- `snowflake-cortex-query` — pattern for ad-hoc Cortex queries from Claude sessions → dismissed

### Actions Taken
- Added date field to thinking/draft.md from git history
```

## Constraints

- Fix obvious issues silently; only ask about ambiguous cases
- Never delete notes during audit
- If vault is empty/new, say so and suggest `/dump` to start
