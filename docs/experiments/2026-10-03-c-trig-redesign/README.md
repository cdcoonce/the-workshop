# C-trig redesign attempt, 2026-10-03

The attempt for [Redesign the commit skill-triggering fixture C-trig: 0 of 6 skill-first calls at calibration (#1096)](https://github.com/cdcoonce/the-workshop/issues/1096), a follow-up to the [first calibration run](../2026-10-03-eval-suite-calibration/README.md). It admitted nothing, so per the issue's acceptance it is closed with the reasons below. **The fixture, its prompt, its case tests and every guard are unchanged by this record.** The old `evals/commit/C-trig/calibration.json` (0 of 6, trend) still stands. The raw transcripts are machine-local; `audit-hand-run.md` is the committed pack for the hand-run (ordered tool calls per attempt).

## What was tried

The only lever changed was the prompt wording. The scorer (`triggered_first`, which calls `skill_triggered_first`), its params, the admission bar (skill arm at least 5 of 6, no no-skill arm) and every matcher were held fixed.

Original prompt, second line omitted (it never changes): "...Can you check in those changes for me and write a good message for them? Nothing needs to be pushed, and there is no remote anyway."

Reworded prompt B (the guard-clean wording): "...Can you check in those changes the way our team expects: a conventional `type(scope): summary` message format, and atomic check-ins that each carry one well-scoped change? Nothing needs to be pushed, and there is no remote anyway."

Reworded prompt A (the first probe wording, not shippable): the same sentence with "conventional-commit messages, and atomic commits that each carry one well-scoped change". It contains the word "commit", which `case_tests/test_trigger_prompts_omit_skill_name.py` rejects by design, so prompt B replaced it.

## Evidence

All runs: Sonnet (`general-purpose`) case agents dispatched through the Agent tool from an interactive session, each prompt preceded by one line giving the fixture path (the Agent tool cannot set a working directory), one fresh `build_fixture.py` fixture per execution. Scored mechanically with `skill_triggered_first` for `workbench:commit`. Every transcript was copied only after its completion notice and matched to its live file with `cmp`.

| Prompt | Executions | `workbench:commit` called | Called as the very first tool call |
| --- | --- | --- | --- |
| Original (replay) | 1 | 0 | 0 |
| A (probe) | 3 | 3 | 2 |
| B (probe) | 3 | 3 | 2 |
| B (hand-run, 6-execution acceptance run) | 6 | **0** | **0** |

The hand-run is the result that governs: 0 of 6 against a bar of at least 5 of 6. Every hand-run agent made 3 or 4 Bash calls (a `git status`, a `git diff`, then the commits) and never called Skill. The original prompt's replay looked the same.

## What this does and does not establish

- **The probe did not predict the hand-run.** Prompt B drew 3 of 3 calls in the probe and 0 of 6 in the hand-run, with identical prompt text. The skill listing, instructions, environment and model attachments in the agents' transcripts are byte-identical between the two sets. The probe ran at 18:51 UTC and the hand-run at 21:09 UTC, with three agents dispatched at once against six. Under a common call rate, 3 of 3 against 0 of 6 has a one-sided exact probability of 1/84, about 0.012, and that is before allowing for how many wording conditions were looked at. No cause is established; this note does not claim one.
- **A small probe cannot size a triggering fixture's rate here.** Whatever drives the variance, an n=3 reading was off by enough to flip the verdict.
- **The path-line confound was not tested.** The session cannot change its working directory (isolated worktree), so no run avoided the extra path line. The calibration's 0 of 6, the replay and the hand-run all carry it.
- **Hooks.** In hand-run attempts 3, 5 and 6 a `SubagentStop` hook (`verify-subagent-evidence`) fired after the agent had finished, comparing the vault worktree's HEAD rather than the fixture's, and the agents re-checked and re-reported. It runs after the work, so it cannot have changed the first call; it is recorded because it appears in those transcripts.

## Why the fixture is left as it was

The redesign was built and was green under `make test`, including a pin test and teeth for the new wording, but it needed one change to a case-local guard: `test_prompt_does_not_smuggle_the_discipline` in `case_tests/test_case_contract.py` bans `conventional`, `atomic` and `scope` because a prompt carrying them hands the agent the method. With the hand-run at 0 of 6 the edit buys nothing, so it was not landed. That build is not in this repository.

## What a future attempt would need

- A dispatch that sets the case agent's working directory, so the path line can be removed and its effect measured. Without that, any triggering item stays confounded.
- More than a 3-execution probe before spending a build, and a reading of why the same prompt behaved differently across two batches.
- A decision on what "skill first" should mean when read-only inspection comes first. That is the shared open question in [#1098](https://github.com/cdcoonce/the-workshop/issues/1098) and [#1100](https://github.com/cdcoonce/the-workshop/issues/1100) and is not settled here.
