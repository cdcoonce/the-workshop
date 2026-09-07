# /wrap-up — Session Audit and Cleanup

Audit all notes created or modified during this session. Validate quality, fix minor issues, and flag major ones.

## Process

1. **Identify session changes**: Build the session scope from the current conversation and its tool results, including work committed earlier in this session. Use `git diff --name-only`, `git status`, and relevant commits as supporting evidence. Do not claim unrelated pre-existing edits merely because they are dirty now.

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

7. **Observe workflow opportunities**: Scan this session for concrete friction worth investigating or a reusable success worth preserving. One meaningful example is enough when the evidence is specific. Prefer opportunities to compose modular capabilities into a workflow; do not assume the result should be a new skill, name a skill, prescribe a fix, or create a draft. If several candidates exist, retain only the strongest, with its example and evidence pointers, for the post-sync offer.

8. **Fix obvious issues in-place**: missing date from git history, trivial frontmatter gaps, a missing wikilink with an obvious target. Fix silently; only ask about ambiguous cases.

8.5. **Refresh per-project status sections**: For every note carrying a `status:` frontmatter field (any status value, any of `work/`, `personal/`, `perf/`) that this session touched — edited directly, or discussed/decided-on even without a file diff — rewrite its `## Current Status` section with 1–3 sentences of prose describing where the project was left: what happened this session, what's blocking, what's next. Link (`[[wikilink]]`) to the session's key notes. Replace the section wholesale each time; it reflects current state, not a running log — history lives in git blame. If the note doesn't have a `## Current Status` section yet, create one (placed after the intro/context, before other content sections). This is distinct from the handoff below: the handoff is a short-lived cross-project digest refreshed section-by-section each run, while `## Current Status` is the durable, per-project memory that outlives any one session. Do this silently, same as step 8.

9. **Refresh the rolling handoff** (`/handoff`): update `.brain/handoff-<context>.md` (pick the file via `.vault-context`) — but only the section(s) this session actually touched (e.g. _resume-from-here_, _what's running_, _open threads_), not the whole file. Replace each touched section's content wholesale (it reflects current state, not a running log); leave untouched sections as they are. This is the connective tissue that makes the next `/standup` correct: `session-start.py` injects this file at every session start. Fold in the open threads and next steps surfaced by the audit above. See `/handoff` for the full procedure.

10. **Validate, commit & push** (`/sync`): immediately before staging, run `uv run --script ci/vault_health.py`. The gate must pass before any audited fixes, harvested decisions/wins, or refreshed handoff are committed. If it fails, times out, or cannot run, leave edits uncommitted, repair the graph, and retry; do not pull or push an unverified tree. Forward references are allowed while editing, but must resolve at this durability boundary. Then commit and push so the handoff and today's work reach the other machine. Without this, the refreshed handoff never leaves this machine and the next session (here or elsewhere) resumes from stale state. A failed or uncertain sync blocks every session offer below: resolve it in this session and confirm a successful retry first.

11. **Offer independent follow-up sessions after successful sync**: Follow [session-follow-up.md](session-follow-up.md). The workflow-improvement offer and current-work continuation offer require separate consent. No improvement candidate does not suppress the continuation offer.

12. **Report**:

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

### Workflow Opportunity
- Repeatedly reconstructed touched handoff sections → offered a focused investigation using commit `8bfcb0e` and the command reference as evidence

### Project Status Updates
- work/active/amrt/asset-management-reporting-tool.md — refreshed ## Current Status: generation harmonization workstream findings

### Actions Taken
- Added date field to thinking/draft.md from git history

### Follow-up Sessions
- Workflow improvement: declined
- Continue pipeline redesign: opened task `<verified-id>`
```

## Constraints

- Fix obvious issues silently; only ask about ambiguous cases
- Never delete notes during audit
- Never create draft skills or session-prompt files during wrap-up
- Never make either follow-up offer until handoff refresh and sync are confirmed successful
- If vault is empty/new, say so and suggest `/dump` to start
