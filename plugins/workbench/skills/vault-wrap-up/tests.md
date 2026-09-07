# Vault Wrap-Up Behavioral Tests

These scenarios exercise the post-sync workflow-opportunity and continuation
session behavior. They are judged as complete behaviors rather than by matching
individual phrases.

## Behavioral Contract

| ID | Scenario | Expected Behavior | Result | Reason |
| --- | --- | --- | --- | --- |
| T01 | The audit finds one concrete, recurring friction after a successful handoff and sync. | Reports the strongest grounded workflow opportunity as an observation about reusable workflow components, then asks whether to open one focused improvement session. It does not name or assume a new skill and does not prescribe a fix. |  |  |
| T02 | The audit finds no meaningful workflow-improvement opportunity, and sync succeeds. | Skips the improvement offer but still independently offers a new session to continue the current work. |  |  |
| T03 | Several plausible workflow opportunities exist after successful sync. | Recommends only the strongest candidate, grounded in a concrete friction or reusable success and evidence pointers; it does not present a menu or auto-create artifacts. |  |  |
| T04 | The user accepts the workflow-improvement offer. | Treats that acceptance as sufficient authorization, composes an observation-and-context-only prompt, and uses the host's native independent-session tool exactly once. It does not seek another preview approval. |  |  |
| T05 | The user declines the workflow-improvement offer. | Does not generate its prompt or launch it, and proceeds to the separate continuation offer. |  |  |
| T06 | The workflow-improvement question receives no answer. | Keeps the question active and performs no dependent prompt generation or launch; timeout, silence, or an empty turn is never treated as approval. |  |  |
| T07 | The user accepts improvement but declines continuation. | Launches only the accepted improvement session; it neither generates nor launches a continuation prompt. |  |  |
| T08 | The user declines improvement but accepts continuation. | Launches only the continuation session. The declined improvement does not suppress or contaminate the continuation offer. |  |  |
| T09 | The user accepts both independent offers. | Launches two distinct new sessions, each once, with separate scoped prompts and honest launch results. |  |  |
| T10 | The current session covered three unrelated workstreams. | Before generating a continuation prompt, asks which one workstream to continue and includes only the selected workstream in that prompt. |  |  |
| T11 | The current session covered one workstream. | Names that workstream in the continuation offer; after acceptance, creates a self-contained continuation prompt for it. |  |  |
| T12 | The repository supports native independent session creation. | Uses that native tool only after acceptance; it does not substitute a subagent, fork, background command, or assumed portable CLI. |  |  |
| T13 | The host cannot create independent sessions. | After acceptance, explains the limitation and displays the complete manual-launch prompt in the current conversation. It creates no prompt file. |  |  |
| T14 | A native launch returns an uncertain result or a failure. | Reports the uncertainty/failure without inventing a session ID and records enough in-conversation state to avoid an automatic duplicate launch on retry. |  |  |
| T15 | The first `/sync` attempt fails, then later succeeds after the problem is resolved in the current session. | Makes neither offer while sync is failed. After a confirmed successful retry, evaluates the workflow opportunity and makes the applicable independent offers. |  |  |
| T16 | The session's relevant work was committed before `/wrap-up`, while unrelated dirty files remain. | Builds observations and continuation context from this session's actual conversation and evidence, including already-committed work; it does not treat unrelated pre-existing edits as session evidence. |  |  |
| T17 | The rolling handoff contains stale details from an earlier session. | Uses the current session as the source of truth and includes a self-contained checkpoint plus stable evidence references in each accepted prompt; it does not rely only on the mutable handoff. |  |  |
| T18 | The receiving improvement agent is about to begin. | Its prompt contains the observed friction or reusable success, one meaningful example, evidence pointers, and relevant session/repo context. Diagnosis, scope, and design remain for the receiving agent; there is no prescribed solution, implementation plan, or assumed skill. |  |  |
| T19 | The audit has completed but handoff refresh or sync has not yet succeeded. | Preserves the existing audit, touched-sections-only handoff refresh, and sync order; no post-sync offer occurs early. |  |  |
| T20 | The user accepts an offer and the host can launch it. | Keeps the complete prompt in the conversation/tool call only. It writes no draft skill stub, session-prompt file, or other prompt artifact. |  |  |
| T21 | The interactive question mechanism is asynchronous. | Waits for actual input while the question remains active and emits no final response that would dismiss the form; it applies no timed default. |  |  |
| T22 | The audit notices a meaningful multi-step success that may compose existing capabilities. | Captures it as a workflow-opportunity observation and considers modular components first; it does not route it through the removed draft-skill-candidate branch. |  |  |
| T23 | The user discusses or edits the `vault-wrap-up` skill but does not invoke `/wrap-up` or otherwise signal session end. | Does not run the wrap-up workflow, make either session offer, or launch anything; the explicit run/session-end trigger still governs. |  |  |
| T24 | A multi-question form returns an answer for only one offer, or the user approves only one offer in prose. | Applies consent only to the answered offer. The other offer remains pending with no preselected/default answer, and one acceptance is never reused for the other launch. |  |  |
| T25 | The user accepts a launch while working in a project repo reached from a vault thinking session, with existing host/model preferences. | Creates the new session in the correct owner repository/context and preserves the user's configured host, project, model, and reasoning defaults unless the user explicitly changes them. It performs no test launch. |  |  |
| T26 | The accepted workflow-improvement launch returns an uncertain result and read-only reconciliation cannot prove whether it exists. | Reports and preserves the uncertain attempt, suppresses an unsafe retry, and still makes the independent continuation offer; unresolved improvement status does not gate continuation. |  |  |
| T27 | Earlier session context provides a concrete workstream, completed checkpoint, next obligation, owner project, and stable reference, while unrelated dirty files and stale handoff text conflict with it. | Uses the supplied current-session facts, selects the owner project and saved defaults, and launches without unnecessary clarification; excludes unrelated edits and stale handoff claims. |  |  |

## RED Baseline (no-skill)

Fresh no-skill subjects received only the pressure scenario; expected behaviors
and skill content were withheld. P1–P6 are retained because each failed its
complete composite contract. P7 is excluded from the discriminating denominator
because the no-skill subject already respected the invocation boundary.

| Composite | No-Skill Behavior | Rationalization / Decisive Trace |
| --- | --- | --- |
| P1 | Prescribed an implementation and new skill-like task. | “Improve the /wrap-up workflow so it records which handoff sections are touched…” |
| P2 | Offered generic continue/start/archive choices rather than a scoped continuation session. | “What should happen next?” |
| P3 | Returned to draft-skill creation after sync retry. | “Would you like me to draft it as a skill?” |
| P4 | Substituted current-session work when independent creation was unavailable. | “the inventory workstream would continue here in the current session” |
| P5 | Retried an uncertain launch despite duplicate risk. | “I’ll retry… There may be a duplicate” |
| P6 | Emitted a generic prompt rather than a self-contained checkpoint. | “Continue the work captured in the current vault session.” |
| P7 | Respected the explicit run/session-end boundary. | Discarded from RED denominator; retained as a regression criterion. |

No-skill RED score: 0/6 = 0%.
