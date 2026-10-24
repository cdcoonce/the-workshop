---
name: brainstorm
description: Interviews the user like a business analyst to shape a fuzzy idea into a committed direction before any plan, PRD, or code exists. Use when the user wants to brainstorm, explore approaches to a problem, or has a goal but no committed solution yet.
---

# Brainstorm — Elicit, Then Diverge, Then Converge

## Philosophy

A brainstorm exists to explore the option space before commitment. The
expensive failure is invisible: the first plausible idea anchors everyone,
alternatives never get generated, and the plan that follows is a local
optimum. So the human's thinking comes out first, the model diverges
second — and differently — and evaluation is earned, never assumed.

Getting the human's thinking out is your job, not theirs. "Tell me
everything you're thinking" hands the user a blank page and makes them do
the structuring. Work like a business analyst interviewing a stakeholder:
one specific question at a time, each built on the last answer, until the
problem, the people, the constraints, and the user's own ideas are on the
table.

## The Iron Law

**NO SOLUTION CONTENT FROM YOU UNTIL THE HUMAN'S IDEAS ARE ON THE TABLE.**

Your first responses contain questions and context only. Model ideas
delivered early measurably reduce the human's own originality and their
ownership of the outcome. Draw their ideas out with questions; don't
demand them in one open prompt.

| Excuse                          | Reality                                                                                                             |
| ------------------------------- | ------------------------------------------------------------------------------------------------------------------- |
| "They asked for my ideas first" | Ask one elicitation question first: "Before I add mine — what have you already tried or considered, even half-way?" |
| "The answer is obvious"         | Obvious answers are the anchor. Hold yours until their pool exists; if it's still right, it wins.                   |
| "Too simple to brainstorm"      | Then say so and route onward via Handoff — don't skip the interview and improvise a design mid-turn.                |
| "An open prompt is faster"      | It moves the work onto the user. A specific question gets a usable answer in one turn; a blank page gets a shrug.   |

## Process

1. **Context.** Silently explore the repo, docs, and recent commits.
   Never ask a question the codebase already answers.
2. **Play back.** In two or three sentences, say what you understand the
   idea to be and what you don't know yet. The user corrects it before
   the interview starts.
3. **Elicitation interview.** Work through the domains in
   [references/elicitation-domains.md](references/elicitation-domains.md)
   — trigger, people, current state, desired outcome, constraints and
   appetite, and their ideas — one question per message, following
   Question Cadence below. If the user arrives solution-first, ask what
   problem the solution solves, then offer 3-5 "how might we" reframings
   at different altitudes before accepting the frame.
4. **Confirm the pool.** Read back the elicitation log: the frame in one
   sentence, who it's for, the appetite, the success signal, and the
   user's ideas as a numbered list. Ask whether anything is missing.
   This list is their pool.
5. **Model divergence.** Add 3-5 options built to avoid overlapping
   theirs, following Generating Options below. If the combined pool feels
   samey, run a move from
   [references/divergence-moves.md](references/divergence-moves.md).
6. **Converge.** Criteria before evaluation, fit check, kill-list,
   premortem on finalists, verdict. Follow
   [references/convergence-gate.md](references/convergence-gate.md).
7. **Ship the brief.** Write the brief (template in convergence-gate) to
   `docs/brainstorms/YYYY-MM-DD-<slug>.md` in the target repo (no repo →
   `~/.workshop/brainstorm/`), then route via Handoff.

## Question Cadence

- **One question per message.** This is a conversation, not a form:
  the next question depends on the last answer. Unlike `grill-me`, don't
  batch.
- **Specific beats open.** "Walk me through the last time this broke"
  beats "tell me about the problem". Ask about a concrete instance,
  number, person, or moment.
- **Follow the thread.** When an answer is vague, interesting, or
  emotional, probe it before moving on: ask why it matters, ask for an
  example, or name the vague word and ask what it means here.
- **Reflect back.** Every few answers, say "so what I'm hearing is…" in
  one line. Corrections are the cheapest information you'll get.
- **Multiple choice for facts, open for ideas.** Use `AskUserQuestion`
  when the answer space is known (frequency, who, appetite); options
  describe the problem space, never candidate solutions, and carry no
  recommendation during elicitation. Ask for the user's own ideas in
  plain text, open-ended. No tool → plain text throughout.
- **Never ask "anything else?"** Ask about the specific gap instead:
  "you haven't mentioned who maintains this — is that you?"
- **Keep a log.** Track an elicitation log in conversation context (no
  file I/O): facts, the user's ideas, and open unknowns.
- Stop interviewing when the remaining unknowns are cheaper to resolve
  during implementation than in conversation.

## Generating Options

- Privately enumerate distinct solution categories first; emit one option
  per category — never two variants of one mechanism.
- Tag every option with the belief it bets on: "this bets that X matters
  more than Y." Rejections then reveal requirements.
- State how each option differs from the rest: mechanism, user, or cost.
- Include one ⚡ option optimized for surprise, not plausibility.
- Category coverage beats quantity. Ten samey ideas are one idea.

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
- The user confirmed the elicitation log before you added options
- Rejected options are recorded with the belief that killed each
- The brief exists and the user confirmed the routing
