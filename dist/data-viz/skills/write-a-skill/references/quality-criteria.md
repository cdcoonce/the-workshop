# Quality Criteria

Standards and checklists for validating a completed skill. Split into description requirements, auto-verify criteria, subjective review, and structural guidance.

---

## Description Requirements

The description is **the only thing the agent sees** when deciding which skill to load. It must give the agent enough information to know what the skill does and when to trigger it.

- Max 1024 chars
- Write in third person
- First sentence: what it does
- Second sentence: "Use when [specific triggers]"

**Good example:**

```
Extract text and tables from PDF files, fill forms, merge documents. Use when working with PDF files or when user mentions PDFs, forms, or document extraction.
```

**Bad example:**

```
Helps with documents.
```

The bad example gives the agent no way to distinguish this skill from any other document-related skill.

---

## Auto-Verify Criteria

The agent checks these automatically after implementation. All must pass before presenting the skill to the user.

- [ ] SKILL.md is under 100 lines
- [ ] Description is under 1024 characters
- [ ] Description includes a "Use when" trigger phrase
- [ ] References are one level deep (no nested references directories)
- [ ] No time-sensitive information (dates, versions that will expire)
- [ ] All reference files listed in SKILL.md actually exist
- [ ] No duplicate content between SKILL.md and reference files
- [ ] For discipline/process skills: at least one pressure scenario exists in `tests.md` with a recorded no-skill RED failure (see [pressure-testing.md](pressure-testing.md))

---

## Subjective Review Checklist

Present these to the user via AskUserQuestion after auto-verify passes. The user evaluates each item and flags anything that needs revision.

- [ ] Does the skill cover all stated use cases from the requirements?
- [ ] Is terminology consistent throughout SKILL.md and all reference files?
- [ ] Are concrete examples included where they aid understanding?
- [ ] Would a new user understand how to invoke this skill?
- [ ] Is the scope appropriately bounded — not too broad, not too narrow?

---

## When to Add Scripts

Add utility scripts to the skill when:

- The operation is deterministic (validation, formatting, file generation)
- The same code would be generated repeatedly across invocations
- Errors need explicit handling that is hard to express in prose instructions

Scripts save tokens and improve reliability compared to generated code.

---

## When to Split Files

Split SKILL.md content into separate reference files when:

- SKILL.md exceeds 100 lines
- Content has distinct domains that are independently useful
- Advanced features are rarely needed by most invocations
- A section contains structured data (tables, templates, domain lists)

Keep references one level deep. Never nest a references directory inside another references directory.
