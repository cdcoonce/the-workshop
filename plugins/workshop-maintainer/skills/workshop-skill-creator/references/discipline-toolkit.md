# Discipline Toolkit: Counter-Rationalization Machinery

Bare mandates ("always do X", "every step is mandatory") do not survive contact with pressure. An agent under time pressure, ambiguity, or a plausible-looking shortcut will rationalize past a mandate that gives it nothing to argue against. This toolkit is the set of countermeasures to reach for when a skill's job is to make an agent choose correctly under that pressure — pair it with [pressure-testing.md](pressure-testing.md) to verify the machinery actually holds.

## Form-to-Failure-Mode Taxonomy

Match the countermeasure to the shape of the failure, not to the topic of the skill:

| Failure mode                                                                                                                                     | Countermeasure                                                                                                                                                    |
| ------------------------------------------------------------------------------------------------------------------------------------------------ | ----------------------------------------------------------------------------------------------------------------------------------------------------------------- |
| **Rule-skipping** — the agent omits a required step under pressure                                                                               | A prohibition stated as an absolute ("NO X WITHOUT Y FIRST"), paired with an excuse → reality table naming the specific rationalizations that will be reached for |
| **Wrong-shaped output** — the agent does the step but produces the wrong shape (e.g. a mock instead of a real test, a summary instead of a diff) | A positive recipe: show the correct shape directly, with a worked example, rather than only prohibiting the wrong one                                             |
| **Omission** — the agent's output is missing a required section or field entirely                                                                | A `REQUIRED` template slot in the output structure itself, so the omission is visible as a blank slot rather than a silent gap                                    |

Pick the countermeasure that matches the failure you're actually trying to prevent. A prohibition doesn't fix a wrong-shaped output (the agent did comply, just badly); a template slot doesn't fix rule-skipping (there's no step to skip if the step is "fill in this field").

## Never Add Nuance Clauses to an Iron Law

An Iron Law ("NO PRODUCTION CODE WITHOUT A FAILING TEST FIRST") must stay a single, unconditional sentence. Do not append "...unless it's a trivial one-liner" or "...except for prototypes" — the moment a law has an exception clause, every future rationalization routes through that clause instead of confronting the law directly. If a real exception exists, state it as a separate, clearly-bounded carve-out elsewhere in the skill (the tdd skill's `discipline.md` models this with its Excuse → Reality table), never as a qualifier inside the law's own sentence.

## Building the Machinery

For a discipline/process skill, include:

1. **The law itself** — one unconditional sentence, no nuance clauses.
2. **An excuse → reality table** — 3-5 rows, each row a specific rationalization the agent will actually reach for, paired with why it's wrong. Generic rows ("laziness" → "don't be lazy") don't work; the excuse must be phrased the way the agent would actually think it.
3. **A red flags list** — observable signals that the law has already been broken (e.g. "the test passed on the first run"), so the agent can catch itself mid-rationalization rather than only in retrospect.
4. **A numeric escalation threshold**, where the failure mode is repeated retries rather than a one-time skip (e.g. "3 failed fix attempts → stop, question the approach, ask the human"). Vague thresholds ("if it's taking too long") don't trigger; a specific number does.

Keep all four inline in the invocation-loaded file (`SKILL.md`) if the line budget allows; otherwise move the excuse table and red flags list to a `references/` file one level deep and leave the law itself and a pointer inline — the law is the part that must be seen every time the skill fires.

## Link This From Every Discipline Skill

If you're writing or editing a discipline/process skill, link back to this file from its `SKILL.md` (or its `references/discipline.md`) so the taxonomy stays discoverable, and check that your skill's own deep-dive doc (if one exists) doesn't contradict the enforcement layer you just wrote — the skill is the enforcement layer, the doc is the narrative version, and they must agree.
