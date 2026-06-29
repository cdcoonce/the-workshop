---
name: clearway-glossary
description: Look up Clearway Energy acronyms, terms, and definitions from the company glossary. Use when user asks about an acronym, says "what does X stand for", "define", "glossary", or "acronym", or when a 3+ letter all-caps word appears that may be a Clearway-specific term.
---

# Clearway Glossary Lookup

## Lookup

When the user asks about a specific acronym or term:

1. Search [glossary.md](references/glossary.md) for an exact match in the **Entry** column.
2. If found, respond with the entry, definition, and category.
3. If multiple rows share the same entry (e.g., AEP, BI, BP), present **all** matches with their categories so the user can disambiguate.

Format:

> **AEP** (Industry) — American Electric Power (utility service provider)
> **AEP** (Industry) — annual energy production

## Search by Description

When the user asks "what's the acronym for [concept]?" or describes something without knowing the acronym:

1. Search the **Definition** column in [glossary.md](references/glossary.md) for keyword matches.
2. Return the top matches ranked by relevance.
3. If no matches, say so — do not guess.

## Auto-Detection

When a word in the user's message meets **all** of these conditions, proactively provide its definition:

- 3 or more characters
- All uppercase letters (e.g., CAFD, BESS, ERCOT)
- Exists as an entry in [glossary.md](references/glossary.md)

Do **not** auto-trigger on common English words that happen to be uppercase (e.g., THE, AND, FOR). Only trigger on words found in the glossary.

## Not Found

If an acronym or term is not in the glossary:

- State clearly: "**[TERM]** is not in the Clearway glossary."
- Do **not** guess or infer a meaning.
- Suggest the user submit it to the [Clearway Glossary SharePoint list](https://clearwayenergy.sharepoint.com/sites/CpFn-HR-EmployeeResources/Lists/Clearway%20Glossary/AllItems.aspx) for inclusion.

## Data Source

The glossary data in [glossary.md](references/glossary.md) is a static snapshot exported from the Clearway Glossary SharePoint list. It may not reflect the latest additions. Direct users to the SharePoint list for the most current version.
