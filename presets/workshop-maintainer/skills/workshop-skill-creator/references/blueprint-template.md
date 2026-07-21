# Skill Blueprint Template

This template defines the structured blueprint that Phase 3 (Plan) produces. The agent fills this out based on gathered and grilled requirements, then presents it for user approval before implementation begins.

---

## Section 1: Proposed File Tree

ASCII tree showing every file the skill will contain.

```
skill-name/
├── SKILL.md
├── references/
│   ├── reference-a.md
│   └── reference-b.md
└── scripts/           (if needed)
    └── helper.sh
```

---

## Section 2: SKILL.md Outline

Section headings with a 1-line purpose for each.

| Section           | Purpose                                       |
| ----------------- | --------------------------------------------- |
| Frontmatter       | Name and description with "Use when" triggers |
| Quick Start       | Minimal working example or invocation         |
| Workflows         | Step-by-step processes with checklists        |
| Advanced Features | Links to reference files for deeper content   |

---

## Section 3: Reference Files

| Filename                | Purpose               | Est. Lines |
| ----------------------- | --------------------- | ---------- |
| `references/example.md` | What this file covers | ~80        |

---

## Section 4: Key Instructions Per Section

For each SKILL.md section, list the core instructions it will contain.

- **Frontmatter** — Description text, trigger phrases
- **Quick Start** — Entry point, minimal example
- **Workflows** — Ordered steps, decision points, checklists
- **Advanced Features** — Reference file links, when to consult them

---

## Section 5: Description Text

The proposed frontmatter description. Must satisfy:

- Under 1024 chars
- Written in third person
- First sentence: what it does
- Second sentence: "Use when [specific triggers]"

---

## Example Blueprint

Below is a filled-in blueprint for a hypothetical `format-sql` skill.

### Proposed File Tree

```
format-sql/
├── SKILL.md
└── references/
    └── dialect-rules.md
```

### SKILL.md Outline

| Section           | Purpose                                                |
| ----------------- | ------------------------------------------------------ |
| Frontmatter       | Name and description with SQL-related triggers         |
| Quick Start       | Format a single SQL file in place                      |
| Workflows         | Multi-file formatting, dialect selection, dry-run mode |
| Advanced Features | Link to dialect-rules.md for vendor-specific rules     |

### Reference Files

| Filename                      | Purpose                                                      | Est. Lines |
| ----------------------------- | ------------------------------------------------------------ | ---------- |
| `references/dialect-rules.md` | Formatting rules per SQL dialect (PostgreSQL, MySQL, SQLite) | ~90        |

### Key Instructions Per Section

- **Frontmatter** — "Format and lint SQL files. Use when user asks to format, clean up, or lint SQL queries or migration files."
- **Quick Start** — Run formatter on target file, show diff, apply if approved
- **Workflows** — Detect dialect from file extension or project config; batch format all .sql files; dry-run to preview changes
- **Advanced Features** — Consult dialect-rules.md when vendor-specific formatting is needed

### Description Text

```
Format and lint SQL files following dialect-specific conventions. Use when user asks to format, clean up, or lint SQL queries, migration files, or stored procedures.
```
