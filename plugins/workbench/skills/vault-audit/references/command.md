# /vault-audit — Comprehensive Structural Audit

Perform a full structural audit of the vault. This is a deeper check than /wrap-up — it covers the entire vault, not just the current session.

## Process

0. **Run the executable audit**:

   ```bash
   uv run python "<engine>/vault_audit.py" --json
   ```

   Use `--limit N` on the Markdown form to control rows per category. The script is read-only and uses the shared `vault_scope.py` policy.

   Its `issues` categories **are** the audit — do not re-check them by hand:

   - `frontmatter` — required fields (date, description, tags) and type-specific
     fields detected from tags, including template conformance
     (`frontmatter_engine.validate`, called from `vault_audit.audit`).
   - `no_wikilinks` / `broken_links` / `ambiguous_links` — notes over 300 chars
     with no wikilinks, and wikilink targets that don't resolve
     (`vault_audit.audit`'s link-scan loop).
   - `orphans` — notes with no incoming backlinks (`vault_audit.audit`'s orphan
     loop).
   - `work_index` / `personal_index` — notes missing from their index file
     (`vault_audit.audit` + `_indexed`).
   - `stale_active` — `status: active` notes untouched for 90+ days
     (`vault_audit.audit`'s staleness loop).
   - `duplicate_descriptions` — notes sharing a description
     (`vault_audit.audit`'s description-grouping loop).

1. **Folder structure** (not computed by the script — check by hand): verify
   all expected top-level directories (brain/, work/, personal/, org/, perf/)
   exist.

2. Read the script's `issues` object and prioritize the **Recommendations**
   from its findings — highest-signal categories first (broken links and
   frontmatter errors block other tooling; staleness and duplicates are
   lower urgency).

## Output Format

Built from the script's JSON (`summary`, `issues`, `thinking_promotion_queue`,
`obsidian_dashboard_gaps`):

```
## Vault Audit Report

### Summary
- Governed notes: X
- Graph/search notes: X
- Issues: X

### Issues by Category
#### Frontmatter (X issues)
- file.md: missing description

#### No Wikilinks (X issues)
- file.md: 450 chars, no wikilinks

#### Broken Links (X issues)
- file.md: broken [[Nonexistent Note]]

#### Ambiguous Links (X issues)
- file.md: ambiguous [[Target]] -> a.md, b.md

#### Orphans (X notes)
- file.md: no incoming backlinks

#### Work Index Drift / Personal Index Drift (X issues)
- work/active/project.md: missing from work/Index.md

#### Stale Active (X notes)
- work/active/old-project.md: active; updated age 120 days

#### Duplicate Descriptions (X issues)
- file.md: description shared by N notes: a.md, b.md

### Folder Structure (manual check)
- [any missing expected directories]

### Recommendations
- [prioritized list of fixes, driven by the script's findings]
```

## Constraints

- Read-only by default — report issues, don't auto-fix
- Ask before making any changes
- Never delete notes
- If dispatching subagents (cross-linker), wait for their results before reporting
