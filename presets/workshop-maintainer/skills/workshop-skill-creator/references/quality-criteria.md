# Quality Criteria

Standards and checklists for validating a completed skill. Split into description requirements, auto-verify criteria, subjective review, and structural guidance.

---

## Description Requirements

The description is **the only thing the agent sees** when deciding which skill to load — it is a retrieval index, not a spec. The skill's body is the behavior spec: its process, phases, and modes. An agent that reads a workflow-bearing description tends to execute the lossy summary in the description instead of the body's actual instructions. Documented failure: a description saying "code review between tasks" caused an agent to run ONE review when the body's flowchart required TWO.

- Max 1024 chars
- Write in third person
- Content is trigger-only: symptoms, quoted user phrases, error strings, and scenario lists that tell the agent when to invoke this skill
- Never describe the skill's process, workflow, phase count, or mode list — phase counts (e.g. "7-phase"), the word "pipeline", "→" step chains, and narrated sequences ("interviews... then iterates... then files") belong in the body, not the description
- A short capability/domain clause is fine as long as it states _what_ the skill covers, not _how_ it executes internally

**Good example:**

```
Extract text and tables from PDF files, fill forms, merge documents. Use when working with PDF files or when user mentions PDFs, forms, or document extraction.
```

**Bad example (vague):**

```
Helps with documents.
```

The vague example gives the agent no way to distinguish this skill from any other document-related skill.

**Bad example (workflow-bearing):**

```
Interviews the user to build a test suite, scores the original skill, iterates with a Skill Writer and QA Tester loop until the target pass rate is reached, then files a PR. Use when user says "improve skill".
```

This narrates the skill's internal loop instead of its triggers. An agent that reads only the description believes the loop runs once, or skips steps the body's actual instructions require — it should read only "Use when user says 'improve skill'..." and defer to the body for how the loop runs.

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
