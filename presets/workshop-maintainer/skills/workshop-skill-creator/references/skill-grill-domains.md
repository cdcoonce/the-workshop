# Skill Grill Domains

These domains define the areas to explore when grilling a user about a new skill they want to build. Not every domain applies to every skill — skip domains that are clearly irrelevant, but err on the side of asking.

Adapt the order to the skill. Start with the domain most central to what's being built.

---

## Domain 1: Intent & Success Criteria

Why are we building this skill? What does success look like?

- What problem does this skill solve, and for whom?
- What does "done" look like — what's the minimum viable skill?
- How will we know it's working correctly once installed?
- What would make this a failure even if the code works?

**Explore before asking:** Check existing skills in `core/skills/` for overlap. Read the user's initial request for stated goals. Look for open issues or plan documents that provide context.

**Batching hints:** Problem, success criteria, and done-definition questions batch well together. Rarely needs multiSelect.

**Preview candidates:** Rarely needed — decisions here are strategic, not structural.

---

## Domain 2: Scope & Boundaries

What's in scope, what's out, and what's deferred?

- What is explicitly NOT in scope for this skill?
- What's being intentionally deferred to a future iteration?
- Where does this skill's responsibility end and another skill's begin?
- Can anything be cut without losing the core value?

**Explore before asking:** Check existing skills for adjacent functionality. Look for skills that might overlap or compose with this one.

**Batching hints:** Scope-in vs scope-out and deferral questions batch naturally. Use multiSelect when asking which capabilities to defer.

**Preview candidates:** Rarely needed unless comparing scope lists or skill boundaries.

---

## Domain 3: Design Decisions & Trade-offs

How does this skill work, and why this approach over alternatives?

- What are the key structural choices (single file vs references, scripts vs instructions)?
- What alternatives were considered and rejected?
- Where are the trade-offs between simplicity and capability?
- Should this skill follow existing skill patterns or intentionally break from them?

**Explore before asking:** Read existing skill structures in `core/skills/` for patterns. Check if similar skills exist that this should mirror or diverge from.

**Batching hints:** Structure choice and pattern-conformance questions batch well. Trade-off questions are usually single-select.

**Preview candidates:** Use previews when comparing skill structures, file layouts, or instruction organization patterns.

---

## Domain 4: Edge Cases & Error Handling

What can go wrong when this skill is invoked?

- What if AskUserQuestion is unavailable in the agent's environment?
- What if a reference file the skill depends on is missing or corrupted?
- What if the skill is invoked with no context or ambiguous input?
- What if the user gives contradictory requirements during the workflow?

**Explore before asking:** Check how existing skills handle missing context, tool unavailability, and malformed input. Look for fallback patterns already in use.

**Batching hints:** Failure modes can be batched. Recovery strategy questions may warrant multiSelect if multiple strategies apply.

**Preview candidates:** Use previews when comparing error handling approaches or fallback strategies across existing skills.
