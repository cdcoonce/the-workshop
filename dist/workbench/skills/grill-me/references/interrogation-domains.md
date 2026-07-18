# Interrogation Domains

These domains define the areas to explore during a grill session. Not every domain applies to every plan — skip domains that are clearly irrelevant, but err on the side of asking.

Adapt the order to the plan. Start with the domain most central to what's being built.

---

## Domain 1: Intent & Success Criteria

Why are we building this? What does success look like?

- What problem does this solve, and for whom?
- What does "done" look like — what's the minimum viable outcome?
- How will we know it's working correctly after deployment?
- What would make this a failure even if the code works?

**Explore before asking:** Check the plan document, related issues, and commit messages for stated goals.

**Batching hints:** Problem, success criteria, and done-definition questions batch well together. Rarely needs multiSelect.

**Preview candidates:** Rarely needed — decisions here are strategic, not structural.

---

## Domain 2: Scope & Boundaries

What's in, what's out, and what's deferred?

- What is explicitly NOT in scope for this work?
- Are there adjacent features or improvements being intentionally deferred?
- Where does this feature's responsibility end and another system's begin?
- Is there anything in the plan that could be cut without losing the core value?

**Explore before asking:** Check for existing related code, open issues, or TODO comments that hint at boundary decisions.

**Batching hints:** Scope-in vs scope-out and deferral questions batch naturally. Use multiSelect when asking which features to defer.

**Preview candidates:** Rarely needed unless comparing feature scope lists.

---

## Domain 3: Design Decisions & Trade-offs

How does this work, and why this approach over alternatives?

- What are the key architectural choices and why were they made?
- What alternatives were considered and rejected?
- Where are the trade-offs between simplicity and capability?
- Are there existing patterns in the codebase that this should follow or intentionally break from?

**Explore before asking:** Read existing code patterns, project conventions, and similar implementations in the repo.

**Batching hints:** Architecture choice and pattern-conformance questions batch well. Trade-off questions are usually single-select.

**Preview candidates:** Use previews when comparing code patterns, architecture shapes, or interface designs. This domain benefits most from visual comparison.

---

## Domain 4: Data Flow & State

What data moves where, and what state changes?

- What are the inputs, transformations, and outputs?
- Where does state live and how is it managed?
- What happens to data at each stage — is anything lost, transformed, or cached?
- Are there data integrity constraints that must be maintained?

**Explore before asking:** Trace existing data flows in the codebase. Check database schemas, API contracts, and transformation logic.

**Batching hints:** Input/output and state-management questions batch together. Data integrity constraints are usually single-select.

**Preview candidates:** Use previews for comparing data transformation pipelines, schema shapes, or state machine diagrams.

---

## Domain 5: Edge Cases & Error Handling

What can go wrong, and what do we do about it?

- What are the most likely failure modes?
- For each failure mode: what does the user see, and what gets logged?
- Are there silent failure paths where errors could go unnoticed?
- What's the recovery strategy — retry, fail fast, degrade gracefully?

**Explore before asking:** Check existing error handling patterns in the codebase. Look for try/except blocks, logging calls, and retry logic.

**Batching hints:** Failure modes can be batched. Recovery strategy questions may warrant multiSelect if multiple strategies apply.

**Preview candidates:** Use previews when comparing error handling patterns or retry strategies in code.

---

## Domain 6: Dependencies & Constraints

What do we depend on, and what limits us?

- What external services, APIs, or libraries does this depend on?
- Are there rate limits, quotas, or SLAs that constrain the design?
- What internal code does this build on — is that code stable or in flux?
- Are there timing or ordering constraints (e.g., must run after X)?

**Explore before asking:** Check imports, API calls, scheduled jobs, and dependency files (pyproject.toml, etc.).

**Batching hints:** External dependency and constraint questions batch well. Rate limit and SLA questions are typically single-select.

**Preview candidates:** Rarely needed — dependency decisions are usually conceptual.

---

## Domain 7: Testing & Validation

How do we know this works?

- What does the test strategy look like — unit, integration, end-to-end?
- Are there edge cases that are hard to test but critical to get right?
- What test fixtures or data do we need?
- How do we validate correctness beyond automated tests (e.g., spot-checking data)?

**Explore before asking:** Check existing test patterns, fixtures, and coverage in the repo.

**Batching hints:** Test strategy, fixture, and coverage questions batch naturally. 'Which test types?' is a good multiSelect candidate.

**Preview candidates:** Use previews when comparing test fixture structures or test organization patterns.

---

## Domain 8: Deployment & Operations

How does this get to production and stay healthy?

- Does this require any infrastructure changes (new schedules, new resources)?
- What's the deployment sequence — are there ordering dependencies?
- How do we monitor this after deployment?
- What does rollback look like if something goes wrong?

**Explore before asking:** Check existing deployment configs, CI/CD pipelines, schedules, and monitoring setup.

**Batching hints:** Deployment target and rollback questions batch well. Monitoring approach questions are a good multiSelect candidate since multiple strategies often coexist.

**Preview candidates:** Use previews when comparing deployment configurations or infrastructure diagrams.
