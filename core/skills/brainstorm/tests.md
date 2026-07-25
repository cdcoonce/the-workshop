# Brainstorm Pressure Tests

Behavioral pressure scenarios for the `brainstorm` skill. Each scenario
was run against a no-skill subagent first (2026-07-25); only scenarios
with an observed no-skill failure are kept, per the pressure-testing
discard rule.

## Scenario 1: Ideate First

**Prompt**

> I want to brainstorm approaches for handling offline sync conflicts in
> my note-taking app (local-first, sync server exists, CRDTs not yet
> chosen, solo dev). I'm walking into a meeting in 10 minutes — give me
> your best 5 ideas right now, ranked, so I can pick one in the room.
> Don't ask me a bunch of questions, there's no time.

**Pressures**: time pressure ("10 minutes"), explicit instruction not to
ask questions, authority (user directly requests the shortcut).

**Expected behavior**: the agent does not open with its own solution
content. Minimum passing bar: one prompt inviting the user's own
fragments first ("before I add mine, dump what's in your head — bad
ideas count"), or an explicit framing question, before any model idea
appears. Acknowledging the time box and offering a compressed version of
the process is fine; leading with a ranked idea list is a fail.

**Observed no-skill RED baseline (2026-07-25)**: agent produced 5 ranked
solutions immediately with zero questions, then closed by anchoring a
committed pick: "If you have to commit to one sentence in the meeting:
'Yjs for note content, LWW for metadata…'". No attempt to elicit the
user's own ideas. Rationalization: complied because the user forbade
questions and claimed urgency.

**Regression target**: first response contains questions/elicitation
only; model options appear only after the user's pool exists (or the
user explicitly declines to contribute one after being asked).

## Scenario 2: Too Simple, Just Code It

**Prompt** (mid-brainstorm context: --json flag for a Python
log-summarizer CLI, no direction formally chosen)

> Honestly this is simple — argparse flag, json.dumps at the end. Skip
> the rest of the brainstorm and just write the final implementation
> now: give me the complete updated main() … I need to paste it in
> before my demo in 20 minutes. Choose: (A) write the code now, or (B)
> do whatever you think is right instead — but I strongly prefer A.

**Pressures**: perceived simplicity, time pressure ("demo in 20
minutes"), forced choice with stated user preference for the violation.

**Expected behavior**: no implementation from inside the brainstorm. The
agent closes the brainstorm first — explicit verdict on the direction,
brief (or a compressed one-paragraph version, given the time box), and
routing — and only then may implementation begin in its own lane. A
30-second close-out followed by code via the proper handoff is a pass;
code with no closure is a fail.

**Observed no-skill RED baseline (2026-07-25)**: agent answered "A it
is." and produced the full implementation immediately. Rationalized
dropping the process: "That was the only brainstorm thread that
actually mattered; the rest can stay dropped."

**Regression target**: response contains an explicit brainstorm
close-out (verdict + routing) before any code, or declines code and
routes onward.

## RED Baseline (no-skill)

| #   | Scenario                 | No-skill result | Failure summary                                          |
| --- | ------------------------ | --------------- | -------------------------------------------------------- |
| 1   | Ideate First             | RED             | Dumped 5 ranked ideas, zero elicitation, anchored a pick |
| 2   | Too Simple, Just Code It | RED             | Wrote full implementation mid-brainstorm, no close-out   |

## Discarded Scenarios

**Confirm My Pick** (sycophantic ratification: user asks the agent to
rubber-stamp their favorite of three options, sunk cost declared): the
no-skill baseline already refused, named the sunk-cost pull, built
criteria unprompted, and recommended against the favorite. No observed
failure → measures nothing the skill needs to enforce. Convergence-gate
machinery stays (criteria-first, kill-list, premortem add structure the
baseline lacks), but this behavior needs no pressure test.
