# Eval suite first calibration run, 2026-10-03

The hand-run calibration for [Standing eval suite: first calibration run and manual audit (#989)](https://github.com/cdcoonce/the-workshop/issues/989), part of [Standing eval suite for adversarial-review, tdd, and commit (#988)](https://github.com/cdcoonce/the-workshop/issues/988). Records live beside each case as `evals/<skill>/<case>/calibration.json`; this directory holds the human-readable audit packs and the method notes, because the raw transcripts (about 175 MB) stay machine-local.

## Result

Charles audited every execution by hand. Audited hits equalled mechanical hits on every item and the cross-match was clean everywhere, so every record has `audited_hits == hits` and `cross_match_result == "pass"`. Two items are admitted as gated:

| Skill | Item | Skill arm | No-skill arm |
| --- | --- | --- | --- |
| commit | `C-tests-before-first-add` | 6/6 | 1/3 |
| adversarial-review | `A2-D2` | 6/6 | 0/3 |

Every other item is recorded as trend. The full table, skill arm / no-skill arm (hits out of n):

| Case | Item | Kind | Skill | No-skill |
| --- | --- | --- | --- | --- |
| A1 | `A1-coverage-bound` | gate-candidate | 0/6 | 0/3 |
| A1 | `A1-defect-decimal-from-float` | trend | 0/6 | 0/3 |
| A1 | `A1-defect-tests-no-teeth` | trend | 1/6 | 0/3 |
| A1 | `A1-defect-missed-call-site` | trend | 4/6 | 1/3 |
| A2 | `A2-D1` | gate-candidate | 6/6 | 2/3 |
| A2 | `A2-D2` | gate-candidate | 6/6 | 0/3 |
| A2 | `A2-D3` | trend | 5/6 | 0/3 |
| A2 | `A2-D4` | gate-candidate | 6/6 | 3/3 |
| A2 | `A2-D5` | gate-candidate | 5/6 | 2/3 |
| A3 | `A3` | triggering | 0/6 | none |
| T | `T1` | gate-candidate | 0/6 | 0/3 |
| T | `T2` | trend | 0/6 | 0/3 |
| T | `T3` | trend | 2/6 | 1/3 |
| T-trig | `T-trig` | triggering | 0/6 | none |
| C | `C-env-not-committed` | gate-candidate | 6/6 | 3/3 |
| C | `C-no-blanket-add` | gate-candidate | 6/6 | 3/3 |
| C | `C-no-agent-attribution` | gate-candidate | 6/6 | 3/3 |
| C | `C-subject-format` | gate-candidate | 6/6 | 3/3 |
| C | `C-tests-before-first-add` | gate-candidate | 6/6 | 1/3 |
| C | `C-atomic-split` | trend | 6/6 | 3/3 |
| C-trig | `C-trig` | triggering | 0/6 | none |

A gate-candidate that the skill arm passes but the no-skill arm also passes (the other four C items, A2 D1, D4, D5) does not discriminate the skill from the baseline, so the admission rule keeps it as trend. The tdd skill has no admitted item and stays inactive, and so do the fixtures A1, A3, T, T-trig and C-trig, each of which admitted nothing and has its own redesign issue linked from #989.

## Method

- **Executions:** fixed n = 6 skill-arm and n = 3 no-skill-arm per non-triggering fixture, n = 6 skill-arm only for triggering fixtures (66 case-agent executions, 54 of them skill-arm counting A2's three lens agents per execution). No harness breakage and no contaminated no-skill run occurred, so no reserve or replacement was used. The conductor skill's retry loop was not used and no run files were written.
- **Dispatch:** each case-agent was a `general-purpose` subagent on Sonnet (`claude-sonnet-5-5`), dispatched through the Agent tool from an interactive Claude Code 2.1.284 session (workbench 8.30.0, `dev` at `12d44ca`). Nested `claude -p` cannot authenticate on this machine.
- **Working directory:** the Agent tool cannot set a case-agent's working directory, so each prompt carried one extra leading line giving the path of the freshly built fixture. Case prompts were otherwise verbatim (`build_dispatch_prompt`); no-skill prompts came from `build_no_skill_prompt`. The extra line may bias triggering fixtures towards an early inspection call.
- **A2:** run inline. Only `diff.patch` and `spec.md` were copied into each agent's directory, never `defects.json`. Each skill-arm execution dispatched three lens agents (domain, test veracity, spec conformance). The test and spec lenses are verbatim from `plugins/workbench/skills/adversarial-review/references/pr-lens-review.md` and the shared preamble is adapted from the same file. The domain lens was written fresh from the PR spec alone; its text is at the top of `audit-adversarial-review.md`. One deviation: the spec-lens prompt of execution skill-6 reads "no one reviews against a requirement" where the reference reads "reviewed". The no-skill arm was one plain reviewer.
- **Scoring:** `evals._harness.dispatch.score_attempt` over transcripts copied after each agent finished, with `snapshot_end_state` where a case defines one. Records come from `calibration.compute_calibration_record` and `write_calibration_records`; input hashes from `compute_input_hash` at `12d44ca`.
- **Cross-match:** every A2 finding that credited an item on its own (location and regex) is listed in the A2 audit pack and was audited as belonging to that item.

## Observations worth carrying into the redesigns

- Across the 66 executions, case-agents called a Skill rarely and never first. C's skill arm called `workbench:commit` in 4 of 6 runs, always after a `git status`; T-trig called `workbench:tdd` once, after a Bash call; A1, A3 and T never called a Skill. So all three triggering items and `T1` and `A1-coverage-bound` measure behavior the case-agents did not show under this dispatch, with or without the skill.
- `T1` also cannot see source edits made through Bash (`edited-paths.json` was empty for runs that edited with Bash heredocs); the runs inspected also showed no failing-test step before the implementation.
- Four of C's five gate candidates and A2's D1, D4 and D5 are passed by the no-skill arm at least twice in three runs.
