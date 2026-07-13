---
name: write-a-skill
description: Create new agent skills with proper structure, progressive disclosure, and bundled resources. Use when user wants to create, write, or build a new skill.
---

# Writing Skills

A 4-phase pipeline: **Gather → Grill → Plan → Implement**.

## Phase 1: Gather

Use `AskUserQuestion` with domain-batched questions across 4 domains. Each domain gets 1 call with 2-4 options and a recommendation (first option = `(Recommended)`).

1. **Purpose** — What task/domain does the skill cover? Who uses it?
2. **Use Cases** — What specific scenarios trigger this skill? What keywords?
3. **Structure** — Does it need scripts? Reference files? Single SKILL.md or multi-file?
4. **Tooling** — Which tools or other skills should it invoke or reference?

## Phase 2: Grill

Invoke the `grill-me` skill, passing gathered requirements. Direct it to use the skill-tailored domains in [skill-grill-domains.md](references/skill-grill-domains.md) (Intent, Scope, Design, Edge Cases). Skip irrelevant domains (Data Flow, Dependencies, Deployment, Testing).

**Fallback (grill-me unavailable):** Run an inline mini-grill using `AskUserQuestion` directly. For each domain in [skill-grill-domains.md](references/skill-grill-domains.md), batch 2-4 questions per call with recommendations and options.

## Phase 3: Plan

Produce a structured skill blueprint using the template in [blueprint-template.md](references/blueprint-template.md). Present the blueprint in conversation context (not written to disk). The user must approve before proceeding. If the user requests changes, revise and re-present.

## Phase 4: Implement

Create all skill files following the approved blueprint. Fully automated — the agent writes everything.

Then run **Phase 4b: Review** using criteria from [quality-criteria.md](references/quality-criteria.md):

1. **Auto-verify** — Check measurable criteria (line count, description length, triggers, reference depth). Fix any failures before proceeding.
2. **Subjective review** — Present the checklist to the user via `AskUserQuestion`. If the user flags issues, revise and re-verify.

## Skill Structure

```
skill-name/
├── SKILL.md           # Main instructions (required, <100 lines)
├── references/        # Supporting docs (if needed)
│   └── domain-ref.md
└── scripts/           # Utility scripts (if needed)
    └── helper.sh
```

## Fallback (no AskUserQuestion)

If `AskUserQuestion` is unavailable, fall back to text-based questions:

**[Header] — [Topic]**
**Recommended:** [Your recommendation and why]
**Alternatives:** (A) [Option] — [trade-off] | (B) [Option] — [trade-off]

## Quality Standards

See [quality-criteria.md](references/quality-criteria.md) for description requirements, auto-verify criteria, subjective review checklist, and guidance on when to add scripts or split files.

## Keep Generated Docs in Sync

If the repo generates documentation from its components (look for a `make docs`
target, a `scripts/build_docs.py`, or a `docs/reference/` tree), regenerate it
and commit the output **with** your new skill. In the claude-workflow repo that
means running `make docs && make build && make test` — the last step gates on
doc/dist staleness, so a new skill that skips it lands the build red. A skill
that isn't in the reference is a skill the team can't discover.
