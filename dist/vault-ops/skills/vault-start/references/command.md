# /start — One-Time Productivity Bootstrap

Initialize the vault's productivity sync system. Scans existing vault content to seed Quick-Reference and Glossary, then interviews the user to fill gaps.

**Run this once after setting up the productivity sync feature.**

## Process

### 1. Check Prerequisites

- Verify `.vault-context` exists (if not, ask which machine this is and create it)
- Verify `brain/` directory exists
- Verify `work/` directory exists

### 2. Create work/Tasks.md

If `work/Tasks.md` doesn't exist, create it with proper frontmatter and sections:
- Active
- Waiting On
- Someday
- Done

Use the work_task_manager pattern from `.claude/scripts/work_task_manager.py`.

### 3. Scan Vault for Known Entities

Read these files to extract people, terms, and projects:
- `org/people/` — scan for person profiles
- `brain/North Star.md` — extract project names and people mentioned
- `work/Index.md` — extract active project names
- `personal/Index.md` — extract personal project names
- Recent git log (last 30 days) — extract commit patterns for project names

Build candidate lists:
- **People:** Names from org/people/ files + wikilinked person names
- **Terms:** Project aliases, acronyms found in note titles and content
- **Projects:** Active project names with status

### 4. Seed brain/Glossary.md

Create `brain/Glossary.md` with extracted terms. Each entry gets:
- **Term** (bold)
- **Meaning** (expanded form)
- **Category** (person, acronym, project, tool, team)

### 5. Seed brain/Quick-Reference.md

Create `brain/Quick-Reference.md` with the top entries from each category:
- **People** table: Name, Role, Context (from org/people/ or wikilink context)
- **Terms** table: Term, Meaning (top acronyms/shorthand)
- **Projects** table: Alias, Full Name, Status

### 6. Interview to Fill Gaps

Ask the user to fill in missing context:

"I found [N] people, [N] terms, and [N] projects in your vault. Let me ask about gaps:"

**People questions:**
- "Who are your key collaborators? (manager, skip-level, frequent 1:1 partners)"
- "Anyone with nicknames or abbreviated names I should know?"

**Terms questions:**
- "What acronyms do you use daily that aren't in the vault yet?"
- "Any project codenames or internal tool names?"

**Projects questions:**
- "Are the active projects I found correct? Any to add or remove?"
- "Any project aliases (e.g., AMRT for Asset Management Reporting Tool)?"

Add interview responses to Glossary and Quick-Reference.

### 7. Initialize Term Frequency

Create `.claude/data/term-frequency.json` with initial counts for all seeded terms (set each to `{"count": 1, "sessions": 1}`).

### 8. Summary

```
## Productivity Sync Initialized

- work/Tasks.md: Created ✓
- brain/Glossary.md: [N] entries
- brain/Quick-Reference.md: [N] people, [N] terms, [N] projects
- .claude/data/term-frequency.json: Initialized ✓

**Next steps:**
- Run `/standup` each morning for M365 sync + daily summary
- Use `/dump` to capture new terms, people, and work context
- Quick-Reference will auto-update as you use terms across sessions
```

## Constraints

- This is idempotent — running it again should fill gaps, not duplicate entries
- Don't overwrite existing Glossary or Quick-Reference entries
- Link people entries to their `org/people/` profiles using wikilinks
- Link projects to their work notes using wikilinks
