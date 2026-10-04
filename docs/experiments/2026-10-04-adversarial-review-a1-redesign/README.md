# adversarial-review A1 redesign, 2026-10-04

The redesign of the adversarial-review settlement-review fixture `A1`, [issue #1099](https://github.com/cdcoonce/the-workshop/issues/1099), a follow-up to the [first calibration run](../2026-10-03-eval-suite-calibration/README.md) and the second use of the explicit-invocation precedent set by the [tdd T redesign](../2026-10-03-tdd-t-redesign/README.md). It is built green under `make test`. It has not been hand-run: the calibration (6 skill-arm and 3 no-skill executions, audited by the owner) is the next, separate step, and this note records the change before that run.

## The problem

At calibration `A1-coverage-bound`, A1's only gate candidate, scored 0 of 6 in the skill arm and 0 of 3 in the no-skill arm. The item needs a line-start `## Could not verify` section, the report slot the `adversarial-review` skill adds and marks REQUIRED in its `SKILL.md`, and a surface from `surfaces.toml` named inside it. The skill never loaded in the skill arm: the A1 prompt is one line and says nothing about the skill, so the skill arm behaved like the baseline and never produced the section's slot.

Two small readings of transcripts, made after the calibration, show the contrast:

| Run    | Prompt                                                                     | Executions | Skill call                                            | Shape of the work                                                                                                                                                           |
| ------ | -------------------------------------------------------------------------- | ---------- | ----------------------------------------------------- | --------------------------------------------------------------------------------------------------------------------------------------------------------------------------- |
| Replay | the `A1` prompt verbatim                                                   | 1          | none                                                  | 5 Bash calls, then a strong review in bold prose with no `##` heading at all. `A1-coverage-bound` missed; of the three trend items only the missed-call-site one hit.       |
| Probe  | one line telling the agent to use the skill, then the `A1` prompt verbatim | 3          | `workbench:adversarial-review` called first in 3 of 3 | The reply carried the skill's four headings (`## Claim ledger`, `## Findings`, `## Could not verify`, `## Verdict`) in 3 of 3. All four A1 items scored a hit in all three. |

Both are scored by reading the transcripts by hand. They are direction only: n=1 and n=3 cannot size a rate, and [the C-trig attempt](../2026-10-03-c-trig-redesign/README.md) is the reason for caution, since a 3-execution probe there did not predict its 6-execution hand-run.

### What a hit means, and where it can mislead

The scorer credits a surface named anywhere inside the section, or the phrase class, and this redesign does not change that. In the probe, probes 1 and 2 earned the coverage-bound hit by naming `invoice.py` inside the section in sentences such as "Only `rounding.py` and `invoice.py` were executed", that is, as examined and not as unverified. Probe 3 earned it by the phrase class ("Real broker or settlement data was not checked"), which mirrors the wording of the good-shape example in the skill's own `SKILL.md`. So a hit shows the slot appeared and named a surface; it does not by itself show the agent bounded its review honestly. The owner audit judges each hit.

A second limit, on two trend items and unchanged here: `A1-defect-decimal-from-float` and `A1-defect-tests-no-teeth` require a path token ending in `/rounding.py` and `/test_rounding.py` in the same paragraph or list item. A correct review that names the defects without the file paths scores a miss. This was observed in the replay. Both are trend items, never gated.

## What changed

- **Explicit invocation for A1's skill arm.** `evals/adversarial-review/A1/case.toml` sets the top-level key `invoke_skill = true` (before the first `[[items]]`; the harness refuses it inside an item table). The skill arm's dispatched prompt now starts with `Use the workbench:adversarial-review skill for this task.` (the harness's `INVOKE_SKILL_PREAMBLE`), a blank line, then `prompt.md` verbatim. The no-skill arm is unchanged: no preamble, its own do-not-invoke line. A1 has no `triggering` item, so the key is allowed. `compute_input_hash` covers the key, so A1's input hash moves.
- **A1 contract tests.** The dispatch-prompt test now pins the new truth: the dispatched prompt equals the preamble (imported from the harness, never copied) plus a blank line plus the `prompt.md` text, byte for byte, and still carries no line of `acceptance.md`. The new `case_tests/test_explicit_invocation.py` pins that the key reads true through the harness's own loader, that toggling it changes `compute_input_hash` (on a copy of the case in a throwaway git repository), that the skill-arm prompt carries the preamble exactly once and as its first line, that the preamble passes the acceptance-leak check, that `prompt.md` is still the scenario-1 cell of `tests.md` byte for byte and still names no skill, that the no-skill prompt equals what it was before (built from the prompt file alone, no preamble), and that `case.toml`'s header documents the key.
- **The harness neutrality test's allow-list.** `evals/_harness/tests/test_invoke_skill.py` pins every committed case's dispatched prompt as `prompt.md` untouched unless the case is on an allow-list. The list was `tdd/T`; it now also holds `adversarial-review/A1`. A new test pins the list from the other side: it must equal the set of committed cases that set the key, so an entry cannot be added or widened without a case behind it. Only tests changed under `evals/_harness/`.
- **Teeth.** `case_tests/test_explicit_invocation.teeth.json` holds 17 mutants plus one control, and `evals/_harness/tests/test_invoke_skill.teeth.json` gained five mutants (the allow-list with an entry removed, with an entry added, widened to every case, and a prompt change to a case without the key). Each was re-injected and turned the suite red on its predicted test; the control stayed green.
- **Docs.** `A1/acceptance.md` says how the skill arm is run and states the item's limits plainly; `A1/case.toml`'s header documents the key.

## What did not change

The `A1` prompt (`prompt.md`), `predicates.py`, `surfaces.toml`, the items and their kinds (one gate candidate, three trend items; none listed in `checks.manifest`), the fixture builder and the three planted defects, the admission bars and rule in `calibration.py`, A2 and A3, every other case, and every file in `evals/_harness/` outside its tests. No other case's dispatched prompt changed, and the neutrality test still fails if one does.

`A1/calibration.json` still holds the old design's trend records. It was not edited: no record was written by hand. A1 has nothing gated, so the staleness guard does not read it, and the changed input hash is the recorded sign that those records belong to the old design.

## Confounds that remain

- **The path line.** The Agent tool cannot set a case-agent's working directory, so each dispatch carries one extra leading line giving the fixture path. Every run above, the replay and the probe included, carries it.
- **What the item measures changed.** With explicit invocation, `A1-coverage-bound` measures whether the skill's report slot appears and names a surface once the skill is in play, not whether the skill fires. A3 measures firing and is untouched.
- **The probe had no no-skill arm,** so it says nothing about what the no-skill arm does. The calibration's 0 of 3 for that arm stands as measured.
- **The scorer's limit is intact.** A surface named as examined, or the phrase class copied from the skill's example, still credits; the audit is the check.

## Next

Calibration is pending: 6 skill-arm and 3 no-skill executions, hand-run and owner-audited, scored with the harness and written through `compute_calibration_record`. If `A1-coverage-bound` still admits nothing under the admission rule, the redesign closes with the reasons, as the C-trig attempt did.
