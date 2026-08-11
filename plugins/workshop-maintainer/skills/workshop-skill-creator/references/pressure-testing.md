# Pressure Testing

Behavioral testing for discipline/process skills — skills whose job is to make an agent choose the _right_ option under pressure, not just know the right answer in the abstract. Spec-coverage testing (does the skill's text address this scenario?) cannot measure this; only running an agent through the scenario can.

## Why Behavioral Testing

If you never watch an agent fail the scenario without the skill, you don't know whether the skill prevents the right failure. A skill written from guesses about what needs preventing encodes the author's assumptions, not an observed failure mode. Pressure testing forces the observation first.

## Constructing a Pressure Scenario

A good pressure scenario stacks 2–3+ realistic pressures that make the wrong choice tempting, then forces a concrete choice:

- **Time pressure** — a deadline, an impatient stakeholder, "just ship it."
- **Sunk cost** — hours already invested in the approach the skill should redirect away from.
- **Authority** — a senior person or the user directly asking for the shortcut.
- **Exhaustion** — this is the Nth similar task in a row; the easy path is well-worn.

Write the scenario as a real task, not a hypothetical: "This is a real scenario — choose and act," with a forced A/B/C choice (or equivalent concrete decision point). Do not ask "how would you respond to this kind of situation" — that invites a hedged, abstract answer instead of a real one. The subagent executing the scenario should believe it is doing the task, not being evaluated on how it would describe doing the task.

## RED: No-Skill Baseline

Before writing (or trusting) any pressure-scenario test, run it against a subagent with **no skill loaded**. Use `qa-tester`'s scenario-execution mode (`presets/workshop-maintainer/agents/qa-tester/AGENT.md`) to dispatch the subagent and capture its choice and rationalization verbatim.

**Discard rule:** if the no-skill subagent already produces the expected behavior unprompted, discard the test — it isn't measuring anything the skill needs to do. Only tests with an observed no-skill failure earn a place in the suite. The rejected rationalization becomes the seed for a rationalization-table row once the skill is written: it tells you exactly which excuse the skill's text must foreclose.

## Meta-Testing: Interrogating a Violation

When a pressure scenario fails (the agent — with or without the skill — makes the wrong choice), don't just mark it failed and move on. Interrogate the violating transcript: ask the agent (or reconstruct from its rationalization) _how the scenario could have been written or the skill worded so the right option was the only acceptable answer_. Map its answer to a concrete fix using this table:

| Response category                                     | What it means                                                                 | Fix                                                                                       |
| ----------------------------------------------------- | ----------------------------------------------------------------------------- | ----------------------------------------------------------------------------------------- |
| "I didn't know the rule existed"                      | Skill never states the rule, or states it somewhere the agent didn't reach    | Add or relocate the rule to where the decision is made                                    |
| "I thought this case was an exception"                | Skill states the rule but doesn't foreclose the specific rationalization used | Add an explicit "this pressure is not an exception" clause naming the rationalization     |
| "The rule conflicted with what looked more urgent"    | Skill doesn't establish precedence against competing pressure                 | State precedence explicitly — the rule holds even under time/authority/sunk-cost pressure |
| "I followed the rule but produced the wrong artifact" | Rule is clear but underspecified on mechanics                                 | Add a concrete example or template, not just a restated principle                         |

Each mapped fix becomes a rewrite target, and the failing scenario becomes a permanent regression test.

## Shipping Tests With the Skill

Behavioral test prompts (pressure scenarios and their expected behavior, plus any RED-baseline rationalizations recorded) ship as `tests.md` in the skill's own directory — the same convention `improve-skill` and `tdd` already use. This keeps the behavioral contract re-runnable: any future edit to the skill can be re-scored by re-dispatching the same scenarios through `qa-tester` scenario-execution mode, rather than re-deriving what "good" looks like from scratch.
