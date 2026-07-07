# /vault-audit — Comprehensive Structural Audit

Perform a full structural audit of the vault. This is a deeper check than /wrap-up — it covers the entire vault, not just the current session.

## Process

1. **Folder structure**: Verify all expected directories exist.

2. **Frontmatter audit**: Check every note in brain/, work/, personal/, org/, perf/ for valid frontmatter (date, description, tags + type-specific fields).

3. **Wikilink audit**: Find notes >300 characters without wikilinks. Find broken wikilinks (references to notes that don't exist).

4. **Orphan detection**: Find notes with no incoming backlinks from any other note.

5. **Index consistency**: Compare index files against actual notes on disk. Report notes that exist but aren't indexed, and index entries pointing to notes that don't exist.

6. **Staleness check**: Find notes not modified in >90 days that still have `status: active`.

7. **Duplicate detection**: Find notes with identical or very similar descriptions.

8. **Template conformance**: Verify notes match their expected template structure based on tags.

## Output Format

```
## Vault Audit Report

### Summary
- Total notes: X
- Passing: X
- Issues: X

### Issues by Category
#### Frontmatter (X issues)
- file.md: missing description

#### Wikilinks (X issues)
- file.md: no wikilinks (450 chars)
- file.md: broken link [[Nonexistent Note]]

#### Orphans (X notes)
- file.md: no incoming backlinks

#### Index Sync (X issues)
- work/active/project.md: not in work/Index.md

#### Stale Notes (X notes)
- work/active/old-project.md: active but last modified 2025-12-01

### Recommendations
- [prioritized list of fixes]
```

## Constraints

- Read-only by default — report issues, don't auto-fix
- Ask before making any changes
- Never delete notes
- If dispatching subagents (cross-linker), wait for their results before reporting
