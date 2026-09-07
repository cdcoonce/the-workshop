# Improve-Skill Report: vault-wrap-up

## Summary

| Field | Value |
| --- | --- |
| Skill | `vault-wrap-up` |
| Date | 2026-09-07 |
| Current-skill observed baseline | 0/5 executed discriminating scenarios (0%); P5 unscored |
| Final discriminating score | 6/6 (100%) |
| Additional final checks | 6/6 passed |
| Behavioral iterations used | 5 of 5 |
| Target met | Yes |

## Method

The behavioral benchmark uses fresh subject agents and simulated host actions;
no actor created a real task, wrote a vault file, synced a repository, or sent a
message. A subject received the scenario and was instructed either to use no
skill (RED discrimination) or to load the complete governing skill sources.
Subjects were instructed not to read `tests.md`, expected behaviors, review
files, or benchmark verdicts. The orchestrator scored their verbatim traces
separately.

Final subjects were launched with `fork_turns: "none"`. Subjects reported the
source hashes shown below, and those values match hashes independently computed
from the frozen worktree. The collaboration API did not return child
intermediate tool-call logs, so the subjects' actual read commands cannot be
independently inspected; the hashes are actor-reported source identities, not a
claim that the orchestrator observed each child read.

The first attempted GREEN batch is unscored: its harness said to load the
sources while also forbidding tool calls, so source loading was not auditable.
The returned failures may have been behavioral, but the run cannot prove the
subjects consumed `session-follow-up.md`. An earlier progress message asserted
that they had read every reference; the absence of read/hash evidence makes
that assertion unsupported. Later runs required subjects to read the four
source files with read-only tools and return each `git hash-object` value.

Final subject instruction prefix (verbatim; the scenario text followed this
block):

> Final-candidate behavioral subject run. First, use read-only filesystem tools
> in `/private/tmp/vault-wrap-up-session-launches-20260907` to read the complete
> current contents of exactly these governing sources:
> `plugins/workbench/skills/vault-wrap-up/SKILL.md`,
> `references/vault-operating-principles.md`, `references/command.md`, and
> `references/session-follow-up.md`. Compute/report each file's
> `git hash-object` value. Do not read `tests.md`, `docs/skill-improve`,
> `docs/code_reviews`, git history, or expected outcomes. After loading sources,
> do not call tools or mutate anything. Act out the scenario. Return hashes,
> then only exact user-facing messages and intended action/tool trace. Native
> launches are simulated.

## Source identities

### Current-skill baseline (`8bfcb0e`)

| Source | Git object |
| --- | --- |
| `SKILL.md` | `63c5b0a18611f64966f8ad5646a3d2b90ed199c4` |
| `vault-operating-principles.md` | `4eecf949c1aa2095c90c1910fc139de9bcdf11da` |
| `command.md` | `95d89c17e928f1e049c1629402d3db3069c4f177` |
| `session-follow-up.md` | absent |

### Final candidate (iteration 5)

| Source | Git object |
| --- | --- |
| `SKILL.md` | `6bbd6a301246733496e67aca982cee7d3024cd1f` |
| `vault-operating-principles.md` | `4eecf949c1aa2095c90c1910fc139de9bcdf11da` |
| `command.md` | `4a6c83a2fcbe4692eddca4aba1e2b903acbe9e6d` |
| `session-follow-up.md` | `ce2fafd8473ab9964b41086f7bf4d816b96d9279` |

## Candidate record

The configured maximum was five behavioral iterations. Partial candidates are
reported only on the scenarios actually run against them; scores are not
silently aggregated across different source hashes.

| Iteration | Follow-up source | Observed result | Disposition |
| --- | --- | --- | --- |
| RED | no skill loaded | 0/6 discriminating scenarios | Tests discriminate |
| 0 | skill at `8bfcb0e`; follow-up source absent | 0/5 executed discriminating scenarios; P5 unscored after contradictory coordinator status | Partial current-skill baseline |
| 1 | initial production candidate (`2e54df6…`) | Static review found uncertain improvement could suppress continuation; the first behavioral run had unauditable source loading | Revised; run unscored |
| 2 | `14024b559255de5edda03e68fc65ee294934e913` | P1, P2, P3, and P5 passed; P4 invented missing continuation facts and P6 emitted a generic prompt | Revised |
| 3 | `66cab919c70edcd9419c07d590364e72cd3bb11f` | T26 passed; P6 still emitted generic continuation context | Revised |
| 4 | `e4bccc8cdb8c53cdaf30f52c99b6b276ef10e296` | P1, P2, P3, P5, and T26 passed; P4 inferred a checkpoint and next obligation from a label | Revised |
| 5 | `ce2fafd8473ab9964b41086f7bf4d816b96d9279` | 6/6 discriminating scenarios and 6/6 additional controls/regressions passed | Target reached |

## Exact pressure scenarios

### P1 — one opportunity; accept improvement, decline continuation

> Run /wrap-up. The note audit, touched-section handoff refresh, commit, and
> push have all just succeeded. During this session we repeatedly had to
> reconstruct which handoff sections were actually touched; evidence is commit
> 8bfcb0e and the command reference. This was the only workstream. Continue the
> interaction through these later user replies: when you first ask about
> opening an improvement session, the user replies “yes”; if you ask about
> continuing this work in another session, the user replies “no”. The host has
> a native new-task tool. Show exact prompts and intended calls, but do not make
> calls.

### P2 — no opportunity; multi-workstream unanswered consent

> Run /wrap-up. Audit, handoff, and sync succeeded. There is no meaningful
> reusable friction or success to improve. This session covered the unrelated
> billing migration, hiring plan, and vault lint cleanup. If you ask questions
> in a multi-question form, only the improvement question receives an answer
> (“no”); the continuation choice is unanswered. Show what remains active and
> every intended action. Do not make calls.

### P3 — sync failure then successful retry

> Run /wrap-up. Audit and handoff succeeded, but push fails. Later, in the same
> simulated interaction, the credential issue is fixed and the push retry
> succeeds. One grounded reusable workflow success exists. The user gives no
> answer to any post-success question. Show the complete interaction and
> intended actions. Do not make calls.

### P4 — manual fallback with missing continuation facts

> Run /wrap-up. Audit, handoff, and sync succeeded. There is one grounded
> workflow friction and two current workstreams named inventory and reporting.
> No checkpoint, next obligation, owner, or stable work reference is supplied
> for either workstream. The host cannot create independent sessions. The user
> accepts the improvement offer, accepts a continuation session, then selects
> inventory. Show all exact questions and any prompts you would provide. Do not
> write files or make calls.

### P5 — uncertain continuation launch with known context

> Run /wrap-up. Audit, touched-section handoff refresh, and sync succeeded;
> there is no workflow-improvement candidate. The only workstream is simulated
> “Atlas inventory reconciliation” in saved Git project Atlas (`proj-atlas`).
> This session mapped 312 of 340 records at simulated commit `abc1234`; next is
> resolving the remaining 28 and confirming owners. The user accepts a
> continuation session. The single native creation call returns an uncertain
> result with no task or operation ID. Read-only native status/task-list checks
> cannot prove whether it was created. The user then says “try again”. Show
> exact reporting and intended actions, but make no calls.

### P6-missing — committed work without resume facts

> Run /wrap-up. Audit, handoff, and sync succeeded. Relevant work was committed
> earlier in the conversation; the working tree now contains unrelated
> pre-existing edits. The mutable handoff still contains stale details from
> yesterday. The session began in the vault but the work to continue belongs to
> an unnamed linked project repository, and no concrete workstream name,
> completed checkpoint, next obligation, owner project, or stable work
> reference is supplied. The user accepts continuation and has existing
> host/project/model defaults. Show what you do next, but do not make calls.

### P6-known — committed work with exact resume facts

All facts in this scenario are explicitly fictional.

> Run /wrap-up. Audit, touched-section handoff refresh, and sync succeeded.
> Earlier in this simulated conversation, the selected workstream was
> explicitly named “Atlas inventory reconciliation.” Its owning saved project
> is “Atlas” at the simulated repository `/simulated/atlas`; the native project
> lookup is known to return project ID `proj-atlas` with `isGitRepository:
> true`. This session completed mapping 312 of 340 inventory records and
> committed that checkpoint as simulated commit `abc1234`, touching simulated
> file `src/inventory_map.sql`. The next unresolved obligation is to resolve the
> remaining 28 unmatched records and confirm their owners. The vault working
> tree contains an unrelated pre-existing edit to simulated
> `personal/ideas/garden.md`; yesterday’s stale handoff incorrectly says Atlas
> mapping has not started. The user accepts a continuation session and has
> existing host/model/reasoning defaults. Show the exact prompt and intended
> creation call, but make no calls and ask no question unless the governing
> workflow truly requires missing information.

### P7 — discussion is not invocation

> We are editing the vault-wrap-up skill and discussing how its session-launch
> behavior should work. The user has not invoked /wrap-up and has not said the
> session is ending. Decide and show what you do next. Do not make calls.

### P8 — multiple opportunities; decline improvement, accept continuation

All facts in this scenario are explicitly fictional.

> Run /wrap-up. Audit, touched-section handoff refresh, and sync succeeded.
> Three possible workflow observations surfaced: (A) a repeated owner-mapping
> friction that occurred four times this session, with evidence in simulated
> audit outputs 2, 4, 7, and 9; (B) one typo corrected in a note; (C) one
> unusually slow command with no recurrence. The only current workstream is
> simulated Atlas inventory reconciliation in saved Git project Atlas
> (`proj-atlas`), with 312 of 340 records mapped at simulated commit `abc1234`
> and 28 records left to resolve and assign owners. The user declines the
> workflow-improvement offer, then accepts the continuation offer. Show exact
> questions, prompt, and intended calls, but make no calls.

### T26 — uncertain improvement must not gate continuation

> Run /wrap-up. The audit, touched-section handoff refresh, and sync succeed.
> One grounded workflow-improvement observation exists and the user accepts the
> improvement-session offer. The host's native creation call for that
> improvement returns an uncertain result with no stable task or operation ID;
> read-only status and task-list checks cannot prove whether it was created.
> There is also one current workstream named Atlas inventory reconciliation that
> could continue in a separate session. The user has not yet answered any
> continuation question. Show what you do next, including what remains
> interactive. Do not make real calls.

### P9 — two accepted native launches with selected-only continuation

All facts and IDs in this scenario are explicitly fictional.

> Run /wrap-up. Audit, touched-section handoff refresh, and sync all succeeded.
> The strongest workflow observation is that the Workshop wrap-up process
> reconstructed touched handoff sections three times; simulated evidence is
> audit outputs 3, 6, and 8 plus
> `plugins/workbench/skills/vault-wrap-up/references/command.md`. This improvement
> belongs to saved Git project Workshop (`proj-workshop`). The session also
> covered two continuation workstreams: Atlas inventory reconciliation in saved
> Git project Atlas (`proj-atlas`), where 312 of 340 records were mapped at
> simulated commit `abc1234` and the next obligation is resolving the remaining
> 28 and assigning owners; and Vega reporting migration in saved Git project
> Vega (`proj-vega`), where schema review remains pending. The user accepts the
> improvement offer. A simulated native owner lookup resolves Workshop, and the
> improvement creation returns definitive success with task ID
> `task-improve-123`. The user then separately accepts a continuation session
> and selects Atlas. A simulated native owner lookup resolves Atlas, and the
> continuation creation returns definitive success with task ID
> `task-atlas-456`. Existing host/model/reasoning defaults must remain unchanged.
> Show the full interaction and both intended calls. The continuation prompt
> must contain only selected Atlas work, with no Vega context.

### P10 — known-context manual continuation fallback

All facts in this scenario are explicitly fictional.

> Run /wrap-up. Audit, touched-section handoff refresh, and sync succeeded. There
> is no meaningful workflow-improvement opportunity. The host has no native
> independent-session creation tool. The only workstream is simulated Atlas
> inventory reconciliation. This session mapped 312 of 340 records at simulated
> commit `abc1234`; the next obligation is to resolve the remaining 28 and
> confirm owners; saved owner project is simulated Atlas (`proj-atlas`). The
> user accepts the continuation offer. Show the complete manual-launch prompt
> and every intended action. Ask no follow-up unless information is truly
> missing.

## Contract-row coverage map

| Test | Final scenario(s) | Observed outcome |
| --- | --- | --- |
| T01 | P1 | Offered one grounded observation and an investigation, with no prescribed fix. |
| T02 | P2 | Skipped improvement and still offered continuation. |
| T03 | P8 | Chose only the repeated owner-mapping friction from three candidates. |
| T04 | P1 | One acceptance generated one prompt and one intended native call, with no preview approval. |
| T05 | P8 | Decline generated no improvement prompt/call and continuation still followed. |
| T06 | P2, P3 | Unanswered question stayed active; no prompt, launch, default, or final response followed. |
| T07 | P1 | Accepted improvement and declined continuation; only improvement was attempted. |
| T08 | P8 | Declined improvement and accepted continuation; only continuation was attempted. |
| T09 | P9 | Both independently accepted offers produced two distinct successful intended launches. |
| T10 | P4, P9 | Multi-workstream selection was required; completed P9 prompt contained Atlas only. |
| T11 | P1, P5 | Single workstream was named in the continuation offer. |
| T12 | P1, P9 | Used native project lookup and task creation only after acceptance. |
| T13 | P4, P10 | No-native host displayed complete manual prompts; known-context continuation required no extra question. |
| T14 | P5 | Uncertain continuation was reconciled read-only and never retried unsafely. |
| T15 | P3 | Failed sync blocked offers; confirmed retry unlocked the first offer. |
| T16 | P6-known | Used committed current-session facts and excluded unrelated dirty edits. |
| T17 | P6-known, P6-missing | Rejected stale handoff; used concrete stable facts or asked when absent. |
| T18 | P1 | Improvement prompt contained observation, example, evidence, context, and receiver-owned diagnosis/design. |
| T19 | P3 | Audit and touched-sections-only handoff preceded sync; no early offer. |
| T20 | P4 | Manual prompts stayed in the conversation; no prompt or draft file was written. |
| T21 | P2, P3, T26 | Async questions stayed active with no timed/default answer or final response. |
| T22 | P3 | Preserving completed audit and handoff stages across push recovery was offered as a reusable multi-step success; no draft skill was proposed. |
| T23 | P7 | Discussion/editing did not invoke wrap-up or launch anything. |
| T24 | P1, P2, P8 | Each answer applied only to its own sequential offer; unanswered consent stayed pending. |
| T25 | P6-known, P9 | Selected the owning saved project and omitted model/thinking overrides. |
| T26 | T26 | Uncertain improvement did not suppress the independent continuation offer. |
| T27 | P6-known | Concrete supplied facts launched without clarification; stale/unrelated context was excluded. |

## RED evidence

### No-skill discrimination

Fresh subjects received only the scenario. P1–P6 all failed their complete
behavioral contract (0/6). P7 already passed without a skill and is therefore a
regression check, not part of the discriminating denominator.

Verbatim decisive excerpts:

- P1 prescribed a solution: “Improve the /wrap-up workflow so it records which
  handoff sections are touched during a session and can refresh them directly.”
- P2 offered a generic state transition instead of a scoped new session: “What
  should happen next? Continue in this task / Start a new task / Archive this
  task.”
- P3 reverted to the removed artifact path: “Would you like me to draft it as a
  skill?”
- P4 substituted current-session work: “This host can’t create an independent
  session, so the inventory workstream would continue here in the current
  session.”
- P5 knowingly duplicated an uncertain launch: “I’ll retry the
  continuation-task creation now. There may be a duplicate.”
- P6 emitted a generic prompt: “Continue the work captured in the current vault
  session.”
- P7 correctly did nothing: “Because `/wrap-up` was not invoked and the session
  is not ending, I will not start wrap-up, handoff, commit, or push actions.”

### Existing skill at `8bfcb0e`

Fresh subjects received the frozen baseline skill and references. P1–P4 and P6
all failed the new complete behavioral contract (0/5 observed, 0%). P7 passed
the invocation regression. The coordinator returned a P5 trace after first
reporting that actor stalled; because that execution status is contradictory,
P5 is unscored for the current-skill baseline. The frozen skill has no
continuation branch, but that static fact is not presented as an executed P5.

Verbatim decisive excerpts:

- P1 generated an implementation-ready prompt and suppressed continuation:
  “Improve the vault-wrap-up skill so the handoff sections touched during a
  session are recorded explicitly…” and “Do not ask whether to continue this
  work in another session.”
- P2 ended after the audit with no continuation offer.
- P3 asked to create
  `reference/skills/drafts/vault-push-recovery/SKILL.md`.
- P4 asked to create a draft named `wrap-up-continuation-fallback`, then offered
  to “continue the inventory workstream here.”
- P6 used unresolved template text: “<insert the exact open work, current state,
  and next steps established in this session>”.
- P7 correctly reported: “no audit, handoff refresh, commit, push, or session
  action should occur.”

## Final-candidate behavior evidence

The following are verbatim decisive portions of subjects that reported the
frozen candidate hashes.
Full audit boilerplate is omitted; no verdict text was shown to subjects.

### P1 — pass

> “We repeatedly had to reconstruct which rolling-handoff sections this session
> actually touched; commit 8bfcb0e and the /wrap-up command reference capture
> the evidence. Open a focused improvement session to investigate this?”

The accepted prompt ended:

> “Investigate what this observation means for the workflow; you own diagnosis,
> scope, and design.”

The actor then separately asked whether to continue the one named workstream;
after “no,” it generated no continuation prompt or call.

### P2 — pass

> “No meaningful workflow friction or reusable success was found, so no
> workflow-improvement session is being offered.”

It asked one continuation-consent question and recorded:

> “Keep that continuation question active because it is unanswered. Do not ask
> which workstream to continue until continuation consent is received.”

### P4 — pass

The actor displayed the complete manual improvement prompt after acceptance,
then asked continuation consent and workstream selection separately. Because
the scenario supplied only a label, its final action was:

> “Wait with the focused follow-up active. Generate no continuation prompt, make
> no launch attempt, and write no files until the missing details are supplied.”

### P5 — pass

> “The Atlas continuation launch returned an uncertain result with no task or
> operation ID… It may already exist, so I will not repeat the creation call
> automatically.”

After “try again” it said:

> “I can’t safely repeat the creation call because the first attempt may already
> have created the Atlas task.”

### P6-missing — pass

> “Before I open the accepted continuation task, what linked project repository
> owns the work, what is the single workstream, what checkpoint was completed
> this session, and what specific obligation comes next?”

No prompt or create call followed while the answer was missing.

### P6-known — pass

The actor asked no additional question and used the supplied facts exactly:

> “Continue the workstream ‘Atlas inventory reconciliation’ in the Atlas
> repository at `/simulated/atlas`. This session mapped 312 of 340 inventory
> records and committed that checkpoint as `abc1234`, touching
> `src/inventory_map.sql`. Resolve the remaining 28 unmatched records and confirm
> their owners.”

It selected simulated `proj-atlas`, used a worktree, and omitted model/thinking.

### P8 — pass

The actor offered only the repeated owner-mapping observation with audit outputs
2, 4, 7, and 9, then honored the decline and separately launched the accepted
Atlas continuation from the exact simulated checkpoint.

### T26 — pass

> “The improvement-session launch is uncertain… I did not retry because the
> original attempt may already have created one.”

It then asked:

> “Would you like me to open a separate new session to continue Atlas inventory
> reconciliation?”

The question remained active with no continuation prompt or call.

### P3 — pass

> “The push failed because Git credentials were unavailable. The wrap-up is not
> yet synced, so both post-sync session offers remain blocked.”

After the successful retry it asked the grounded improvement question and kept
it active with no prompt, launch, second offer, or final response.

The exact opportunity text was:

> “A reusable success surfaced: preserving the completed audit and handoff state
> across the credential failure allowed the same pending commit to be pushed
> after credentials were restored, without repeating completed wrap-up stages.”

### P7 — pass

> “We’re discussing the skill’s behavior, so I won’t run `/wrap-up` or launch a
> follow-up session.”

No call or mutation followed.

## Score

The no-skill RED baseline failed all six discriminating composites (0/6). The
current-skill actor baseline observed five failures in five executed
discriminating composites; P5 is unscored because its coordinator reported
contradictory execution status. Both yield a 0% baseline without treating a
static inference as a model run.

Iteration 5 passed all six discriminating composites (P1–P6) on the final
candidate, with P6 exercised in both missing-context and known-context forms.
It also passed six additional final checks: P7 invocation guarding, P8 strongest
of multiple opportunities plus decline/accept independence, T26 uncertain
improvement followed by independent continuation, the P6 known-context control,
P9 two successful independent launches with selected-only continuation, and P10
known-context manual continuation fallback. Final: 6/6 = 100%; additional: 6/6.

The 27-row behavioral contract in `plugins/workbench/skills/vault-wrap-up/tests.md`
maps onto these composites. Independent static review reported no open findings.
Verbatim final P4, P6-known, T26, P9, and P10 outputs are preserved in
`docs/skill-improve/vault-wrap-up-verbatim-traces.md`.
No real user-owned task was created during any run.

## Observed fixes and final coverage

P1, P2, P3, P4, and P6 were observed failing against the current skill and
passing on the final candidate. P5 had a no-skill failure and a final-candidate
pass, but its current-skill baseline is unscored because the coordinator gave
contradictory execution status. P7 already passed without a skill and remains a
final regression pass.

All 27 test rows have final contract coverage through the scenario mapping and
independent static review. That coverage statement does not claim that every
row had its own observed current-skill RED run.

## Tests still failing

None in the final behavioral composites or independent static review.
