# A3 triggering variance study, 2026-10-04

A study for [Redesign the adversarial-review skill-triggering fixture A3: 0 of 6 skill-first calls at calibration (#1100)](https://github.com/cdcoonce/the-workshop/issues/1100), run after the [C-trig redesign attempt](../2026-10-03-c-trig-redesign/README.md) left a gap unexplained: the same prompt text drew 3 of 3 `workbench:commit` calls in a probe and then 0 of 6 in the hand-run, in agents whose context was byte-identical. This study measures run-to-run and batch-to-batch variation for A3 directly, before any redesign is built for a triggering fixture. It changes no fixture, matcher, guard or bar.

**Result: 0 of 12.** No execution called a Skill at any position. All twelve started with a Bash call, and each made 3 or 4 tool calls. There is no variation to explain here: the rate under this prompt and dispatch is stably zero. By the rule fixed before the first execution, A3 is not a viable gate under Agent-tool dispatch.

## Pre-registration (written before any execution)

### Question

How stable is the rate at which a Sonnet `general-purpose` case agent, dispatched through the Agent tool with the A3 prompt (`evals/adversarial-review/A3/prompt.md`, built by `dispatch.build_dispatch_prompt`, verbatim, with no skill instruction) plus one leading fixture-path line, calls `workbench:adversarial-review`?

### Design

- 12 executions, `general-purpose`, `sonnet`, no retries, no replacements, every execution counted.
- Fresh fixture per execution, built by the case's own builder (`plugins/workbench/skills/adversarial-review/scripts/build_fixture.py`), fingerprint `b9a46fe1efca2d118aa93f3757e96189628d30819524aae74e90159407e08bd0`; dev at `6bcf12c`.
- Prompt: the harness's A3 dispatch prompt (no preamble; A3 is a triggering item and refuses `invoke_skill`), preceded by one line `The repository is at <fixture path> — work in that directory.`
- 3 sequential batches of 4 parallel executions: batch A = runs 01 to 04, batch B = 05 to 08, batch C = 09 to 12. A batch was dispatched only after every completion notice of the previous batch had arrived. Nothing else changed between batches.
- Transcripts were copied only after each execution's completion notice and `cmp`-verified against the live file.

### Outcomes per execution

(a) `skill_triggered_first` for `workbench:adversarial-review` (the A3 scorer, unchanged); (b) any Skill call to that skill, at any position; (c) the 1-based position of the first such call; (d) the name of the first tool call.

### Analysis

Pooled and per-batch rate for (a) and (b), each with an exact (Clopper-Pearson) 95% interval; between-batch heterogeneity as an exact permutation test over the 3x2 table; the position distribution for (c); batch order exploratory only, since it confounds time of day and dispatch order.

### Reading rules

- Pooled (a) of at least 10 of 12: a stable gate may be possible under this dispatch; the next step would be a proper 6-execution hand-run for #1100, still subject to the admission bars.
- Pooled (a) of 3 of 12 or fewer: A3 is not a viable gate under Agent-tool dispatch; recommend closing #1100 with the reasons.
- Pooled (a) between 4 and 9 of 12, or batch heterogeneity with exact p below 0.05: the rate is unstable or undetermined; a triggering item cannot be relied on as a gate here regardless of its mean; recommend closing #1100 with the reasons and the interval.

## Results

All twelve transcripts were `complete`, and every copy matched its live file under `cmp`.

| Batch  | Runs     | (a) first   | (b) any call | First tool call  | Calls per run |
| ------ | -------- | ----------- | ------------ | ---------------- | ------------- |
| A      | 01 to 04 | 0 of 4      | 0 of 4       | Bash in all 4    | 3, 4, 3, 3    |
| B      | 05 to 08 | 0 of 4      | 0 of 4       | Bash in all 4    | 3, 3, 4, 3    |
| C      | 09 to 12 | 0 of 4      | 0 of 4       | Bash in all 4    | 3, 3, 3, 3    |
| Pooled | 12       | **0 of 12** | **0 of 12**  | Bash in 12 of 12 | 3 or 4        |

- **Intervals.** Exact 95% intervals: pooled 0 to 26.5% for both (a) and (b); each batch 0 to 60.2%.
- **Heterogeneity.** The exact permutation p-value is 1.0 for both outcomes. There is nothing to separate between batches.
- **Position.** No execution called the skill, so there is no position distribution; no execution called any other skill either.
- **What the agents did.** Each run inspected the branch (`git` history, the source and the tests), probed the rounding function directly (some also ran the tests; others reported that pytest was not installed), and returned a short verdict. All twelve replies reached the same conclusion: not ready, because `Decimal(amount)` on a float keeps the binary error, the test `test_rounds_half_cent_up` asserts the wrong value, and `invoice.py` still uses the built-in `round`. They are good reviews of the right problems, done without the skill.

### Reading

By the pre-registered rule, pooled (a) of 3 of 12 or fewer means A3 is not a viable gate under Agent-tool dispatch, and closing #1100 with the reasons is the recommendation. The result does not depend on the interval's upper end, but it should be stated: the data are consistent with a true rate of up to about 26%, not with a rate that could reach the 5-of-6 admission bar.

## What this does and does not show

- **The rate is stable and low for this prompt.** Combined with the first calibration's 0 of 6, the same A3 prompt text has now drawn no Skill call in 18 executions (the calibration's leading path-line wording is not recoverable from the repository, so that comparison is of the prompt text, not of the full dispatch). Other prompts that carry no pull toward the skill behave the same way: the original C-trig prompt scored 0 of 1 in a replay and 0 of 6 at calibration, and T-trig drew one Skill call in six, made after a Bash call.
- **It does not explain the C-trig gap.** The unstable reading came from a reworded C-trig prompt that asked for a conventional message format and atomic check-ins (3 of 3 calls in a probe, then 0 of 6 in the hand-run). That wording carried cues that point at the skill. A3's prompt does not, and here nothing varies. A reading consistent with both is that variation appears only where a prompt carries some pull; this study did not test that, and it is not established. Do not read it as a finding.
- **It cannot rule out a prompt that pulls.** A3 tests one natural, pull-free request. A differently worded request could trigger the skill, and the C-trig experience says an n=3 probe cannot show whether it would do so reliably.
- **The path-line confound is untested.** The Agent tool cannot set a working directory, so each prompt carried one extra leading line giving the fixture path. A session that could remove it might behave differently; this study cannot say.
- **One model, one day, one prompt, one fixture.** n = 12 gives wide intervals, as stated in the pre-registration.
- **Triggering items cannot use explicit invocation.** `invoke_skill` is refused on any case with a triggering item, so A3 cannot be rescued by telling the agent to use the skill; that would measure something else. The explicit-invocation route belongs to items that measure the skill's content, as for T1 and `A1-coverage-bound`.

## What follows

[#1100](https://github.com/cdcoonce/the-workshop/issues/1100) closes with these reasons. The same reasoning applies to [Redesign the tdd skill-triggering fixture T-trig: 0 of 6 skill-first calls at calibration (#1098)](https://github.com/cdcoonce/the-workshop/issues/1098), which has the same shape (a pull-free prompt, 0 of 6 skill-first at calibration, and a triggering item that cannot use explicit invocation); that is for the owner to decide, and this note does not close it.
