# /clickup-task-sync — Sync Vault Action Items into ClickUp

Take a set of action items (from a note or a freeform recap) and land them in ClickUp without creating duplicates — matching each item to its right existing task, updating/commenting instead of re-creating where one already exists, and asking the user only when placement is genuinely ambiguous.

## When to run

- After a 1:1 outcome note, meeting recap, or `Tasks.md` capture produces a batch of action items that need to exist in ClickUp.
- The user says "sync this to ClickUp" or hands you a list of action items.

## Inputs

- A note path (e.g. a 1:1 outcome note) **or** a freeform recap pasted by the user.
- Extract discrete action items: one line/bullet each, with any stated owner/due date.

## Process

1. **Extract the action items.** Read the source note (or parse the recap). One action item per line; keep owner and due-date hints attached — don't lose them in normalization.

2. **Match each item to the board.** Search ClickUp (via the connector) for the relevant existing task by project/theme, using the tag taxonomy from [[2026-06-29 ClickUp Board Organization Model]] (`proj:` initiative, `tech:` system) as the primary matching signal, task title as secondary.
   - **Resolving duplicate/stale parents:** when multiple candidate tasks share a name, prefer the one that is **not cancelled** and, among non-cancelled candidates, the **most recently updated**. Never write to a cancelled duplicate.

3. **Check for a near-duplicate before creating anything.** Within the matched parent's existing subtasks (or, for flat tasks, the task's own checklist items), look for one that already covers this action item.
   - **Near-duplicate found** → update it: bump the due date, or add a clarifying comment. Do not create a new subtask/checklist item for something already tracked.
   - **No near-duplicate** → create it as a **checklist item** on the matched flat task, or a **subtask** if the matched task is one of the three parent-container programs (AMRT, PCI Upload Pipeline, REC Dashboard) per the container rule in [[2026-06-29 ClickUp Board Organization Model]].

4. **When no clear parent exists, ask — don't guess.** Offer the user 2–3 concrete placement options (existing task/tag candidates, or "new flat top-level task"). Only create a brand-new top-level task after the user confirms — a wrong new task is harder to undo than a wrong subtask, since the connector cannot create or delete tags and stale top-level tasks accumulate as clutter.

5. **Apply tags on creation.** Any newly created task gets the appropriate `proj:`/`tech:` tags from the existing taxonomy. **Never invent a new tag name** — the connector cannot create tags via API; if a needed tag doesn't exist yet, tell the user rather than silently skipping it or typing a near-miss.

6. **Report a clean summary.** For each action item: created / updated / skipped-as-duplicate, with a link or task name. Flag anything left unresolved (ambiguous placement the user didn't answer, missing tag, etc.) explicitly rather than silently dropping it.

## Constraints

- Never create a duplicate top-level task when an existing one (non-cancelled, most-recently-updated) already covers the theme.
- Never invent a new ClickUp tag — flag the gap instead.
- Ask before creating a new top-level (non-subtask) task when placement is ambiguous; subtask/checklist-item creation under a confidently-matched parent does not require asking.

## Related

- [[2026-06-29 ClickUp Board Organization Model]] — container rule + tag taxonomy this skill matches against
- [[Tasks|Work Tasks]] — vault-side task capture this often syncs from
