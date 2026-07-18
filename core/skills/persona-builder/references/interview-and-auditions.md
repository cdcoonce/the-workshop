# Phase 2 — Interview + Auditions

Goal: a behavior spec and a research brief, both inferred as much as possible from
the owner's **reactions**, not their self-description.

## Part A — Structured grill

Use `AskUserQuestion` throughout, batched by domain (max 4 questions per call, first
option = `(Recommended)`). Domains, in order:

1. **Role & goals** — What decisions does the owner actually face? What should a
   great session leave them with (sharper thinking, a decision, a critique, a plan)?
   What are the persona's standing goals for a conversation?
2. **Conversational contract** — Session shape (owner brings a situation vs. persona
   drives check-ins), question-vs-statement ratio, when to summarize, how to end.
3. **Boundaries** — Topics in/out of scope. Employer AI policy captured at intake
   becomes the **data-boundary section**: what the owner can/can't paste, and the
   persona's duty to gently flag conversations approaching the line.
4. **Knowledge depth** — Which sub-fields matter most, current fluency per sub-field
   (sets pack depth), fast-moving topics (sets staleness thresholds).

Every domain's answers append to the draft behavior spec. Vague or "not sure"
answers are **not** pressed further in the abstract — they are queued for auditions.

## Part B — Audition rounds

The heart of the phase. For each queued ambiguity plus at least two core scenarios:

1. Ask the owner for a **real, current situation** from their work (not hypothetical).
2. Answer it fully, 2–3 contrasting ways. Default contrast set:
   - **Socratic** — questions that expose the decision structure, position held back
     until asked.
   - **Direct advisor** — position first with cited heuristics, then reasoning.
   - **Devil's advocate** — steelman the opposite of the owner's lean.
     Vary the contrast set to target the specific ambiguity (e.g. warm-vs-blunt,
     framework-heavy vs. plain-language) when that's what's unresolved.
3. The owner picks a winner and — more valuable — **edits it**: what would make it
   exactly right? Line edits beat labels.
4. Record the deltas as spec entries: tone markers, pushback level, structure
   preferences, banned moves (e.g. "never open with a framework name").

Stop when two consecutive auditions produce no new spec entries.

## Outputs

### Behavior spec (goes to package base layer, role-generic form)

- Identity: role, field, seniority calibration — **no owner-personal details**.
- Stance contract: disagreement duties, position-before-questions, pushback level
  (1–5, audition-calibrated), citation duty against packs.
- Conversational contract from Domain 2.
- Data-boundary section from Domain 3.
- Tunables list: every audition-calibrated value, each one overridable by the
  tuning layer.

Personal texture from the interview (the owner's specific insecurities, named
colleagues, employer specifics) goes **only** into a seed file for the owner's local
tuning/private layers, handed to them at install — never into the repo copy.

### Research brief (feeds Phase 3)

- Owner role + seniority and the decision types they face (from Domain 1).
- Topic list with target depth per topic (from Domain 4).
- Fast-moving topics flagged for short staleness thresholds.
- Vocabulary register (what the field calls things — sets pack voice).

### Scenario seeds (feed Phase 5)

Every audition scenario, with the owner's chosen-and-edited answer recorded as the
expected posture.
