# /link — Wikilink Insertion Helper

Search the vault for matching notes and help insert wikilinks.

## Usage

```
/link <search term>
```

## Process

1. Search for notes matching the search term:
   - Check note filenames (exact and partial match)
   - Check frontmatter descriptions
   - Check note content for the term

2. Present matching notes with their paths and descriptions.

3. If one clear match: suggest the wikilink syntax `[[Note Name]]`.

4. If multiple matches: list them and ask which one to link.

5. If no match: suggest creating a new note with that name, and ask which folder it belongs in.

## Constraints

- Search is case-insensitive
- Show the full path so the user knows where the note lives
- If the note doesn't exist, suggest the most appropriate folder based on the search term
