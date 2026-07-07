# /dump — Freeform Capture and Routing

Accept freeform content from the user and route it to the appropriate vault location with proper frontmatter, folder placement, and wikilinks.

## Usage

```
/dump <raw text — a thought, meeting summary, decision, incident report, idea, anything>
```

## Process

1. **Classify** the input text to determine what type of note this is:
   - Work categories: decision, incident, 1-1, win, project-update, person-context
   - Personal categories: learning, project-idea, side-project, task
   - Default: thought (goes to thinking/)

2. **Determine the target**:
   - For new notes: create in the suggested folder with the appropriate template
   - For updates to existing notes: find and update the relevant note
   - For wins: update `perf/Brag Doc.md` AND create evidence if substantial
   - For tasks: append to the current week's task file in `personal/tasks/` using `task_manager.add_task()`. Extract any wikilinks from the text. Do NOT create a standalone note — tasks go into the weekly file.

3. **Apply the template**:
   - Use the correct template frontmatter for the note type
   - Fill in `date` with today's date
   - Write a concise `description` (~150 chars) summarizing the content
   - Add appropriate `tags`
   - Fill in type-specific fields (status, project, participant, etc.)

4. **Add wikilinks**:
   - Link to any people mentioned → `[[Person Name]]`
   - Link to any projects mentioned → `[[Project Name]]`
   - Link to related competencies → `[[Competency Name]]`
   - Link to related decisions or incidents if referenced

5. **Update indexes**:
   - Add the new note to the appropriate index file
   - If it's a win, also update `perf/Brag Doc.md`
   - If it mentions a person, check if `org/people/<Name>.md` exists; suggest creating it if not

6. **Report what was created**:
   - Show the file path and a brief summary
   - List any wikilinks added
   - Note any index updates made
   - Flag if any referenced people/projects don't have vault notes yet

## Naming Conventions

- Work notes: `work/active/<descriptive-slug>.md`
- Decision records: `work/active/<decision-slug>.md`
- 1:1 notes: `work/1-1/<Person Name> <YYYY-MM-DD>.md`
- Incidents: `work/incidents/<incident-slug>.md`
- Learning notes: `personal/learning/<topic-slug>.md`
- Side projects: `personal/projects/<project-name>.md`
- Ideas: `personal/ideas/<idea-slug>.md`
- Person profiles: `org/people/<Full Name>.md`
- Task files: `personal/tasks/<YYYY-W##>-tasks.md` (append to current week's file)
- Thoughts: `thinking/<YYYY-MM-DD>-<descriptive-slug>.md`

## Constraints

- Always validate frontmatter before saving (the PostToolUse hook will check, but get it right)
- Never overwrite an existing note without asking — update or append instead
- When classifying is ambiguous, state what you chose and why
- If the dump contains multiple distinct topics, split into separate notes
