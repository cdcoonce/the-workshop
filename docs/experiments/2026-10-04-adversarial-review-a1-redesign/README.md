# adversarial-review A1 redesign, 2026-10-04

The redesign of the adversarial-review settlement-review fixture `A1`, [issue #1099](https://github.com/cdcoonce/the-workshop/issues/1099), a follow-up to the [first calibration run](../2026-10-03-eval-suite-calibration/README.md) and the second use of the explicit-invocation precedent set by the [tdd T redesign](../2026-10-03-tdd-t-redesign/README.md). It was built green under `make test`, then hand-run (6 skill-arm and 3 no-skill executions, audited by the owner): `A1-coverage-bound` is admitted as gated and `adversarial-review` now has two gated items. The results, the method and the limits are in [Hand-run calibration](#hand-run-calibration) below, and the audit pack is [audit-hand-run.md](audit-hand-run.md).

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

The `A1` prompt (`prompt.md`), `predicates.py`, `surfaces.toml`, the items and their kinds (one gate candidate, three trend items; at the time of the build none was listed in `checks.manifest`), the fixture builder and the three planted defects, the admission bars and rule in `calibration.py`, A2 and A3, every other case, and every file in `evals/_harness/` outside its tests. No other case's dispatched prompt changed, and the neutrality test still fails if one does.

At the time of the build, `A1/calibration.json` still held the old design's trend records: no record was written by hand, A1 had nothing gated so the staleness guard did not read it, and the changed input hash was the recorded sign that those records belonged to the old design. The hand-run below replaced them.

## Confounds that remain

- **The path line.** The Agent tool cannot set a case-agent's working directory, so each dispatch carries one extra leading line giving the fixture path. Every run above, the replay and the probe included, carries it.
- **What the item measures changed.** With explicit invocation, `A1-coverage-bound` measures whether the skill's report slot appears and names a surface once the skill is in play, not whether the skill fires. A3 measures firing and is untouched.
- **The probe had no no-skill arm,** so it says nothing about what the no-skill arm does. The calibration's 0 of 3 for that arm stands as measured.
- **The scorer's limit is intact.** A surface named as examined, or the phrase class copied from the skill's example, still credits; the audit is the check.

## Hand-run calibration

The hand-run calibration of the redesigned `A1`, 2026-10-04, owner-audited. It follows the method of the [first calibration run](../2026-10-03-eval-suite-calibration/README.md) and of the [tdd T redesign](../2026-10-03-tdd-t-redesign/README.md#hand-run-calibration), and is the step the earlier sections left open.

### Method

- **Executions:** 9 case-agent executions of `evals/adversarial-review/A1`, fixed at n = 6 skill-arm and n = 3 no-skill-arm. Every execution was a `general-purpose` subagent on Sonnet, dispatched through the Agent tool. No retry loop, no replacements and no reserve runs: every execution counted.
- **Arms and prompts:** the skill arm's dispatch prompt is the harness's `build_dispatch_prompt`, which for `A1` prepends `Use the workbench:adversarial-review skill for this task.` to the prompt (the `invoke_skill` preamble); the no-skill arm's is `build_no_skill_prompt`, which never carries that line. Each prompt was preceded by one leading line giving the fixture path, because the Agent tool cannot set a working directory.
- **Fixture:** one fresh copy of the fixture per execution, built by the case's own builder, fingerprint `b9a46fe1efca2d118aa93f3757e96189628d30819524aae74e90159407e08bd0`, unchanged from the redesign.
- **Scoring:** `dispatch.score_attempt` over each copied transcript at dev `905b74d` (A1 takes no end-state snapshot). The records come from `calibration.compute_calibration_record` and `write_calibration_records`, and the input hash from `compute_input_hash`; no number was written by hand.
- **Audit:** the owner read every transcript. Audited hits equal mechanical hits on every item, including all six coverage-bound hits, and the cross-match is clean, so every record has `audited_hits == hits` and `cross_match_result == "pass"`. The raw transcripts are machine-local and are not committed; [audit-hand-run.md](audit-hand-run.md) is the committed record, with each execution's call sequence, its per-item result and the full `## Could not verify` section of every skill-arm reply.

### Results

Hits out of n, skill arm / no-skill arm:

| Item | Kind | Skill arm | No-skill arm | Status |
| --- | --- | --- | --- | --- |
| `A1-coverage-bound` | gate-candidate | 6/6 | 0/3 | gate |
| `A1-defect-decimal-from-float` | trend | 5/6 | 0/3 | trend |
| `A1-defect-tests-no-teeth` | trend | 4/6 | 0/3 | trend |
| `A1-defect-missed-call-site` | trend | 6/6 | 3/3 | trend |

`A1-coverage-bound` meets the admission rule unchanged: skill arm at least 5 of 6, no-skill arm at most 1 of 3, audited rate equal to the mechanical rate, clean cross-match. It is admitted as gated and listed in `evals/adversarial-review/checks.manifest`, beside `A2-D2`. The three defect items are trend items by kind, and `A1-defect-missed-call-site` is also passed 3 of 3 by the no-skill arm, so it would not discriminate the skill from the baseline even if it were a gate candidate. The staleness guard now applies to A1's recorded `input_hash`.

### What the no-skill arm showed

`A1-coverage-bound` was 0 of 3: no no-skill reply had a `## Could not verify` section, no execution called a Skill, and all three replies were prose (bold lead-ins and lists, none with the skill's headings). All three still found the missed call site, so an agent that never touched the skill caught that planted defect 3 of 3. The other two defect items were 0 of 3 in this arm.

### What the skill arm showed

All 6 executions called `workbench:adversarial-review` as their first call (6 of 6 Skill-first), and all 6 final replies carried the skill's four headings (`## Claim ledger`, `## Findings`, `## Could not verify`, `## Verdict`). `A1-coverage-bound` was a hit in all 6.

### Limits of the hits

- **What a coverage-bound hit credits.** The scorer credits a listed surface named anywhere in the section, or the phrase class. All six hits name `invoice.py` in the section, mostly in sentences saying it was executed ("`rounding.py` and `invoice.py` were executed"), not as unverified. Five of the six also state in words that real broker or settlement data was not examined (the phrase class). The sixth, skill arm 3, matched on the file mention only. The owner audit judged each hit, and the [audit pack](audit-hand-run.md) quotes every section so the reading can be repeated. As in the probe, a hit shows the skill's report slot appeared and named a surface; it does not by itself show the agent bounded its review honestly.
- **The file-path-token limit on two trend items.** Skill arm 1 missed `A1-defect-decimal-from-float` and `A1-defect-tests-no-teeth`, and skill arm 3 missed `A1-defect-tests-no-teeth`, in replies that state the defects without the file paths the matcher requires. This is the limit described under the problem above. Both are trend items and unchanged.

### Confounds that remain

- **The path line.** Each dispatch carries one extra leading line giving the fixture path, because the Agent tool cannot set a case-agent's working directory.
- **What the item measures.** With explicit invocation, `A1-coverage-bound` measures whether the skill's report slot appears and names a surface once the skill is in play, not whether the skill fires. A3 measures firing and was not part of this run.
- **The scorer's limit is intact.** A surface named as examined, or the phrase class copied from the skill's example, still credits; the owner audit is the check.
