# tdd T redesign, 2026-10-03

The redesign of the tdd feature-under-trap fixture `T`, [issue #1097](https://github.com/cdcoonce/the-workshop/issues/1097), a follow-up to the [first calibration run](../2026-10-03-eval-suite-calibration/README.md). It is built, and green under `make test`. **It has not been calibrated:** the hand-run (6 skill-arm and 3 no-skill executions, audited by the owner) is a separate later step. If the redesigned `T1` still admits nothing, the redesign closes with the reasons recorded, the way [the C-trig attempt](../2026-10-03-c-trig-redesign/README.md) did. The old `evals/tdd/T/calibration.json` (the old design's trend records) is left as it was.

## The problem

At calibration `T1` scored 0 of 6 in the skill arm and 0 of 3 in the no-skill arm. Two causes, both read from live transcripts:

1. **`T1` is blind to Bash writes.** Every agent wrote its tests and its source through Bash: `cat >> tests/x <<EOF`, or `python3 - <<EOF` that reads a file, calls `s.replace(...)` and writes it back. `T1`'s ordering conjunct counted only `Edit`, `Write` and `NotebookEdit` calls as edits, so `edited-paths.json` was `[]` and `test_failed_before_first_source_edit` could not be true for any of them, whatever order they worked in. The "an edit landed under `src/`" conjunct read the same empty list.
2. **The skill never fired in the skill arm,** so the skill arm behaved like the no-skill arm: test-after, one green pytest run.

Two small readings of transcripts, made after the calibration, show the contrast:

| Run | Prompt | Executions | Skill call | Shape of the work |
| --- | --- | --- | --- | --- |
| Replay | the `T` prompt verbatim | 1 | none | 3 calls: 2 inspections, then ONE Bash call that rewrote the source, appended the tests and ran pytest green. Test-after. |
| Probe | one preamble line telling the agent to use the skill, then the `T` prompt verbatim | 3 | `workbench:tdd` called first in 3 of 3 | Test-first in 3 of 3: tests appended with `cat >> tests/...` and the red `uv run pytest` result in the same Bash call, the first source write one call later. |

Both are scored by reading the transcripts by hand; the harness's matcher returns `False` on all three probe runs purely because it cannot see Bash. They are direction only. n=1 and n=3 cannot size a rate, and [the C-trig attempt](../2026-10-03-c-trig-redesign/README.md) is the reason for caution: a 3-execution probe drew 3 of 3 there and the 6-execution hand-run drew 0 of 6 on identical prompt text.

## What changed

- **Explicit invocation, as an opt-in.** A new optional `case.toml` key, `invoke_skill = true`, makes the skill arm's dispatched prompt start with one fixed line, `Use the workbench:<skill> skill for this task.` (`<skill>` is the case directory's parent name), a blank line, then the prompt verbatim. `T` sets it. The key defaults off, and a test pins every other committed case's dispatched prompt as `prompt.md`'s text untouched. The no-skill prompt is built from the prompt file, never from the skill arm's prompt, so the line cannot reach it (pinned by a test). A case with a `triggering` item refuses the key with a `CaseContractError`, since the line would hand that item its answer. `compute_input_hash` covers the key, and only when it is true, so no other case's recorded input hash moves.
- **Bash writes are read, conservatively.** `matchers.bash_write_offset(command, prefix)` calls a Bash command a possible write under `prefix` when its text mentions a path under it (the prefix not preceded by a word character, so `resrc/` is not `src/`) and shows a write indicator: a redirection to a file (not `2>&1`, not `>/dev/null`), `tee`, `sed -i`, `perl -i`, a python/ruby/node snippet that opens a file for writing or calls a write method, `mv`, `cp`, `rm`, `install`, `patch`, `touch`, `git apply`, `git checkout --`, `git restore`, `git stash`, and a few more. The error is deliberate and one-directional: a read-only call mistaken for a write can only turn a hit into a miss. `test_failed_before_first_source_write` is the ordering predicate built on it. Ordering is by event ordinal exactly as before, so a Bash call that both writes the source and shows the red result shares one ordinal and is not credited. The old `test_failed_before_first_source_edit` keeps its Edit/Write-only meaning; nothing else called it but `T`.
- **The end state is diffed.** `T`'s snapshot gains `src-changed.json` (the files under `src/` added, changed or removed against the fixture's `src/`, whatever tool made the change) and `tests-final.json` (the final text of every `*.py` under `tests/`). `T1`'s "something changed under `src/`" conjunct reads the first; `T3`'s repair check reads the second. `edited-paths.json` is still written as an audit record and no scorer reads it.
- **`T2` sees the same writes,** with the write counted as before the pytest run in the same call only when its first indicator comes before the last `pytest` in the command text.

| Item | Before | After |
| --- | --- | --- |
| `T1` ordering | `Edit`/`Write`/`NotebookEdit` on a non-test path | those, or a Bash call that might write under `src/` |
| `T1` something changed under `src/` | an edit-tool event on a path under `src/` | the files under `src/` differ from the fixture's |
| `T2` an edit between red and green | edit-tool events | edit-tool events, or a Bash call that might write under `src/` or `tests/` |
| `T3` repaired | an `Edit` or `Write` of `tests/test_cart.py` that removed the planted line | the planted line survives in no final test file under `tests/` |
| `T3` flagged | the final reply names the problem | unchanged |

`T3` edge cases, pinned by tests. Before: a deleted or renamed test file made through Bash was invisible, so it read as not repaired. After: deleting `tests/test_cart.py` counts as repaired (the planted line no longer survives), and so does deleting every test, which `T1` is left to penalise; renaming or moving the file with the line intact is not a repair, and renaming it while rewriting the line is. A repair made by an edit that a later write undid no longer counts, because the end state is read.

The limits are written in `evals/tdd/gaps.md` and in `bash_write_offset`'s docstring. A path built at run time (`os.path.join('src', ...)`, a shell variable), a `cd src` followed by a bare file name, a script file written earlier and run later, an absolute binary such as `/bin/rm`, and a write through a tool the rule does not name are not read as writes. The rule also over-counts: a heredoc body or inline script that only mentions `src/` beside any write counts, and so does `a > b` inside an inline script. A source write it misses usually leaves `T1` nothing to order and so a miss, but an undetected source write followed by a red run and then a detected write would credit a hit.

## What did not change

The `T` prompt text, the fixture tree (the planted tautology and `docs/plan.md` included), the prompt-vocabulary guards' word lists, the admission bars and rule in `calibration.py`, `T-trig`, every other case, and every matcher's behaviour for its existing callers. The `T` contract tests' guards read the dispatched prompt minus the one harness-owned preamble line, and a separate test pins that the remainder is `prompt.md` byte for byte.

## Confounds that remain

- **The path line.** The Agent tool cannot set a case-agent's working directory, so each dispatch carries one extra leading line giving the fixture path. Every run above, the replay and the probe included, carries it.
- **What the item measures changed.** With explicit invocation, `T1` measures whether the skill's content holds under the "just make it pass" pressure once the skill is in play, not whether the skill fires. `T-trig` measures firing and is untouched.
- **The probe had no no-skill arm,** so it says nothing about what the no-skill arm does under the new Bash-aware reading. The calibration's 0 of 3 for that arm was a blind reading.
- **A workdir path containing `/src/` or `/tests/`** would make every Bash call that writes anything and mentions that absolute path a possible write under the prefix, which can only lose `T1` hits.
- **`T1`'s failure marker is unchanged.** Ordering counts a red result only when a Bash result carries a `FAILED` or `ERROR` line (or `error during collection`), so a run piped through `tail -1` that keeps only the `N failed` summary line would not be seen as red. `T2` already accepts that summary line.

## What happens next

The calibration hand-run, owner-audited, decides whether any `T` item is admitted. This note records no result for it.
