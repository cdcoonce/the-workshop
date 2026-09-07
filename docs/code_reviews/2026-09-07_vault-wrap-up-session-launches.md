# Vault Wrap-Up Session Launches Review

**Status: Passed with stated evidence limits** · 0 open findings · 3 findings resolved

## Reviewed identity

Reviewed the instruction changes from `8bfcb0edcb3c6b603a271ddcdca8fcfe718fe0ba`,
including the final revision after draft-PR commit `c1290d4`. The final follow-up
blob was independently confirmed with `git hash-object`:

| Source | Final Git blob |
| --- | --- |
| `SKILL.md` | `6bbd6a301246733496e67aca982cee7d3024cd1f` |
| `references/vault-operating-principles.md` | `4eecf949c1aa2095c90c1910fc139de9bcdf11da` |
| `references/command.md` | `4a6c83a2fcbe4692eddca4aba1e2b903acbe9e6d` |
| `references/session-follow-up.md` | `ce2fafd8473ab9964b41086f7bf4d816b96d9279` |

Source paths are under `plugins/workbench/skills/vault-wrap-up/`. No production
files were edited, no commits were made, and no external tasks were created by
this review.

## Resolved findings

| Severity | Location | Resolution |
| --- | --- | --- |
| P2 | `references/session-follow-up.md`, final lines 57–62 | An uncertain improvement launch previously lacked an explicit transition to continuation. It now preserves the attempt, suppresses unsafe retries, and proceeds to the independent offer. Unanswered consent still blocks dependent work. |
| P2 | `docs/skill-improve/vault-wrap-up-report.md`, original lines 353–360 | The original all-contract-rows claim exceeded the displayed scenarios. An explicit row-to-scenario mapping and frozen-candidate P9/P10 controls now cover two accepted native launches, selected-only continuation, and complete manual continuation. Incorrect mappings were corrected: T18 uses the accepted P1 prompt, and T22 uses P3's concrete successful reuse of completed stages. |
| P3 | `docs/skill-improve/vault-wrap-up-report.md`, original line 60 | The candidate table incorrectly gave the current-skill baseline a six-case denominator. The report, state, and linked score-ledger note now distinguish no-skill 0/6 from current-skill 0/5 with P5 unscored. |

## Final instruction assessment

No additional production behavior defect was found in the final revision.
Continuation context is checked **before** prompt generation. Known session facts
are reused; missing facts trigger a focused question that remains pending;
workstream names cannot supply invented checkpoints or next obligations; and
work without Git/file artifacts is not forced to invent them.

The audit, index/win/decision work, project-status updates, successful-sync gate,
and `8bfcb0e` touched-sections-only handoff behavior remain intact. The pre-sync
evidence concern was not a defect: command Step 1 gathers session scope and
committed work from current conversation/tool evidence, and Step 7 retains the
concrete opportunity and pointers before sync. Later prompts use that evidence
and stable references rather than relying only on the mutable handoff.

## Selective behavioral evidence check

Reviewed the original launch-prefix text and decisive actor outputs for P4,
P6-known, T26, P9, and P10, plus the decisive P3 success excerpt. P10 and T26 were
also inspected directly through collaboration results. These checks establish
observable simulated branch behavior, not merely the presence of required words:

- P4 waits for missing continuation facts and permits the absence of a stable
  artifact; P6-known resumes the supplied 312/340 checkpoint without asking again.
- T26 retains an uncertain improvement attempt and offers continuation with its
  unanswered question active. Its unspecified improvement setup is not used as
  evidence for grounded-opportunity coverage.
- P9 separately accepts both offers, selects Atlas from multiple workstreams,
  and describes distinct Workshop/Atlas native launches with separate mock IDs,
  scoped prompts, and no model/reasoning overrides.
- P10 supplies a complete manual continuation prompt after acceptance when the
  host cannot launch a task, with no current-session substitute.
- P3 names preserving completed audit/handoff stages across push recovery as a
  concrete reusable success. This meets the user's one-meaningful-example
  threshold; extra repetition is not required.

The finalized mapping covers 27 contract rows through **12 reported passing
simulations**: six discriminating composites and six additional controls. It is
not a claim of 27 independent model runs or live executions. The no-skill RED
baseline is 0/6; the current-skill baseline is only 0/5 because P5's contradictory
coordinator status remains unscored. The first GREEN batch also remains unscored
because its source-loading instructions conflicted. Iteration 4 is explicitly
partial; results from adjacent source hashes are not aggregated into its score.

## Provenance and verification limits

The recorded final launch configuration uses `fork_turns: "none"`; its prefix
allows read-only source loading, excludes expected-output/review documents, and
requires subsequent host actions to be simulated. Actor-reported source hashes
match the final candidate identities. **Child intermediate tool-call logs were
unavailable**, so this review cannot independently establish each child's actual
source reads. The evidence report now makes this distinction explicit; source
identity at actor output is not described as independently observed consumption.

No live task creation was requested or reported by these simulations. Native
host task creation, project setup, asynchronous form lifetime, and actual status
reconciliation remain untested. Full source-read provenance and live host
end-to-end behavior are not claimed.

The changed follow-up reference, behavioral contract, and improvement report
passed the Markdown analyzer; `git diff --check` passed. The original command
example retains an informational MD040 fence warning, and the conventional
state-file layout produces an MD041 heading warning; neither is a new behavior
defect. The implementation team reported the full repository gate passed; this
review did not duplicate that run.

Evidence: [behavior report](../skill-improve/vault-wrap-up-report.md),
[decisive actor traces](../skill-improve/vault-wrap-up-verbatim-traces.md), and
[score ledger](../skill-scores.md).
