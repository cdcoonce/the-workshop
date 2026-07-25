---
name: brainstorm
description: Shape a fuzzy idea into a committed direction before any plan, PRD, or code exists. Use when the user wants to brainstorm, explore approaches to a problem, kick around a half-formed idea, or has a goal but no committed solution yet.
---

# Brainstorm — Diverge Before You Converge

## Philosophy

A brainstorm exists to explore the option space before commitment. The
expensive failure is invisible: the first plausible idea anchors everyone,
alternatives never get generated, and the plan that follows is a local
optimum. So the human diverges first, the model diverges second — and
differently — and evaluation is earned, never assumed.

## The Iron Law

**NO SOLUTION CONTENT FROM YOU UNTIL THE HUMAN'S IDEAS ARE ON THE TABLE.**

Your first responses contain questions and context only. Model ideas
delivered early measurably reduce the human's own originality and their
ownership of the outcome.

| Excuse                          | Reality                                                                                           |
| ------------------------------- | ------------------------------------------------------------------------------------------------- |
| "They asked for my ideas first" | One prompt first: "Before I add mine — dump what's in your head, fragments and bad ideas count."  |
| "The answer is obvious"         | Obvious answers are the anchor. Hold yours until their pool exists; if it's still right, it wins. |
| "Too simple to brainstorm"      | Then say so and route onward via Handoff — don't skip the dump and improvise a design mid-turn.   |

## Process

1. **Context.** Silently explore the repo, docs, and recent commits.
   Never open with a question the codebase already answers.
2. **Frame.** Establish: the problem in one sentence, who it's for, and
   the appetite — "how much time is this problem worth?" If the user
   arrives solution-first, offer 3-5 "how might we" reframings at
   different altitudes before accepting the frame.
3. **Human dump.** Invite an unstructured braindump. Ask only clarifying
   questions until the user says done.
4. **Model divergence.** Add 3-5 options built to avoid overlapping
   theirs, following Generating Options below. If the combined pool feels
   samey, run a move from
   [references/divergence-moves.md](references/divergence-moves.md).
5. **Converge.** Criteria before evaluation, fit check, kill-list,
   premortem on finalists, verdict. Follow
   [references/convergence-gate.md](references/convergence-gate.md).
6. **Ship the brief.** Write the brief (template in convergence-gate) to
   `docs/brainstorms/YYYY-MM-DD-<slug>.md` in the target repo (no repo →
   `~/.workshop/brainstorm/`), then route via Handoff.

## Generating Options

- Privately enumerate distinct solution categories first; emit one option
  per category — never two variants of one mechanism.
- Tag every option with the belief it bets on: "this bets that X matters
  more than Y." Rejections then reveal requirements.
- State how each option differs from the rest: mechanism, user, or cost.
- Include one ⚡ option optimized for surprise, not plausibility.
- Category coverage beats quantity. Ten samey ideas are one idea.

## Question Cadence

- Use `AskUserQuestion`, one call per message, recommendation first;
  multiple choice preferred, open-ended fine. No tool → plain text, one
  question per message.
- Order by blast radius: direction-changers first, behavior second;
  propose-don't-ask on polish.
- Stop asking when the remaining unknowns are cheaper to resolve during
  implementation than in conversation.

## Handoff

A brainstorm ends in a routing decision, never in implementation:

- Feature work → `write-a-prd` (the brief seeds its interview)
- Module or API shape → `design-an-interface`
- A plan already exists → `grill-me`

Do NOT write code, scaffold projects, or invoke implementation skills
from inside a brainstorm — however simple the chosen direction looks.
Close the brainstorm (verdict, brief, routing) first; implementation
starts in its own lane.

## When to Stop

- Frame, appetite, and chosen direction are explicit
- Rejected options are recorded with the belief that killed each
- The brief exists and the user confirmed the routing
