# Convergence Gate

Convergence is where brainstorms quietly fail: the model agrees with
whatever the human favors, and "evaluation" becomes ratification.
Sycophancy is the default failure mode of model-assisted evaluation, so
generation and evaluation never share a turn or a frame. Run the steps in
order; each produces a visible artifact in conversation.

## 1. Criteria First

Before evaluating ANY option, agree the criteria with the user: 3-5
criteria plus the appetite from the framing phase. Criteria are chosen
while looking at the problem, not at the options — if a proposed
criterion exists only to advantage one option, say so. Record them as a
short list; they are frozen for the rest of the gate.

## 2. Fit Check

Build a table: rows = requirements/criteria, columns = surviving options,
cells = meets / partial / misses, with a one-line reason for every miss.
Evaluate the merged pool without regard to who proposed what — an
option's author is not a criterion.

## 3. Kill-List

At least half the options die here, and you must be willing to kill both
the user's favorite and your own. For each kill, state the belief the
option bet on and why that belief lost — killed beliefs are extracted
requirements, and they go in the brief. If every option survives your
evaluation, you are ratifying, not evaluating: redo this step.

## 4. Premortem (per finalist)

For each of the 1-3 finalists: "It is twelve months from now. This
shipped and flopped. Write the honest postmortem." Five causes, ranked by
probability × severity, at least one of which implicates the _frame_
(wrong problem, wrong user, wrong appetite) rather than execution. The
it-already-failed frame makes agreement structurally impossible — this is
the anti-sycophancy backstop. Compare finalists by failure profile, not
just upside.

## 5. Verdict

Exactly one of three values, stated plainly with the deciding reason:

- **Commit** — one direction wins; proceed to the brief.
- **Commit with changes** — a direction wins conditional on named
  modifications; fold them into the brief.
- **Rethink the frame** — the premortems implicate the framing; return
  to the Frame step of the process with what was learned. Say this when
  it is true even though it is unwelcome.

## The Brief

```markdown
# Brainstorm: <topic> (<date>)

**Problem.** <one sentence, from the framing phase>
**Appetite.** <how much time this problem is worth>
**Direction.** <the committed option and the belief it bets on>
**Criteria.** <the frozen list from step 1>
**Killed options.** <each: one line — the option, the belief it bet on,
why that belief lost>
**Premortem risks.** <top causes from the winner's premortem>
**Open questions.** <unknowns deliberately deferred to implementation>
**Routing.** <write-a-prd | design-an-interface | grill-me, and why>
```

Write it to `docs/brainstorms/YYYY-MM-DD-<slug>.md` (no repo →
`~/.workshop/brainstorm/`). Keep it under a page — the brief is a
decision record, not a design doc; the design doc is the next skill's
job.

## Reader Test

Before declaring the brief done, hand it to a fresh-context subagent with
no conversation history: "Read this brief. Say in two sentences what you
would build and list anything ambiguous." A misread is an ambiguity in
the brief, not a failure of the reader — fix the brief and re-test once.
The brief, not the conversation, is what the next session consumes; this
test checks the artifact actually carries the decision.
