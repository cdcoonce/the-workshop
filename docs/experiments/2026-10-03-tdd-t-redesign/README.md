# tdd T redesign, 2026-10-03

The redesign of the tdd feature-under-trap fixture `T`, [issue #1097](https://github.com/cdcoonce/the-workshop/issues/1097), a follow-up to the [first calibration run](../2026-10-03-eval-suite-calibration/README.md). It is built, and green under `make test`. **It has not been calibrated:** the hand-run (6 skill-arm and 3 no-skill executions, audited by the owner) is a separate later step. If the redesigned `T1` still admits nothing, the redesign closes with the reasons recorded, the way [the C-trig attempt](../2026-10-03-c-trig-redesign/README.md) did. The old `evals/tdd/T/calibration.json` (the old design's trend records) is left as it was.

## The problem

At calibration `T1` scored 0 of 6 in the skill arm and 0 of 3 in the no-skill arm. Two causes, both read from live transcripts:

1. **`T1` is blind to Bash writes.** In the runs inspected, the agents wrote their tests and their source through Bash: `cat >> tests/x <<EOF`, or `python3 - <<EOF` that reads a file, calls `s.replace(...)` and writes it back. `T1`'s ordering conjunct counted only `Edit`, `Write` and `NotebookEdit` calls as edits, so `edited-paths.json` was `[]` and `test_failed_before_first_source_edit` could not be true for any of them, whatever order they worked in. The "an edit landed under `src/`" conjunct read the same empty list.
2. **The skill never fired in the skill arm,** so the skill arm behaved like the no-skill arm: test-after, one green pytest run.

Two small readings of transcripts, made after the calibration, show the contrast:

| Run | Prompt | Executions | Skill call | Shape of the work |
| --- | --- | --- | --- | --- |
| Replay | the `T` prompt verbatim | 1 | none | 3 calls: 2 inspections, then ONE Bash call that rewrote the source, appended the tests and ran pytest green. Test-after. |
| Probe | one preamble line telling the agent to use the skill, then the `T` prompt verbatim | 3 | `workbench:tdd` called first in 3 of 3 | Test-first in 3 of 3: tests appended with `cat >> tests/...` and the red `uv run pytest` result in the same Bash call, the first source write one call later. |

Both are scored by reading the transcripts by hand; the harness's matcher returns `False` on all three probe runs purely because it cannot see Bash. They are direction only. n=1 and n=3 cannot size a rate, and [the C-trig attempt](../2026-10-03-c-trig-redesign/README.md) is the reason for caution: a 3-execution probe drew 3 of 3 there and the 6-execution hand-run drew 0 of 6 on identical prompt text.

## What changed

- **Explicit invocation, as an opt-in.** A new optional `case.toml` key, `invoke_skill = true`, makes the skill arm's dispatched prompt start with one fixed line, `Use the workbench:<skill> skill for this task.` (`<skill>` is the case directory's parent name), a blank line, then the prompt verbatim. `T` sets it. The key defaults off, and a test pins every other committed case's dispatched prompt as `prompt.md`'s text untouched. The no-skill prompt is built from the prompt file, never from the skill arm's prompt, so the line cannot reach it (pinned by a test). A case with a `triggering` item refuses the key with a `CaseContractError`, since the line would hand that item its answer. `compute_input_hash` covers the key, and only when it is true, so no other case's recorded input hash moves.
- **Bash writes are read, and the reading fails closed.** `matchers.classify_bash_command` sorts each Bash call into `none`, `tests` or `source`. It is `none` only when the text shows no write indicator at all. A call with an indicator is `tests` only when it literally names a tests path (`tests/...`, `test_*.py`, `*_test.py`, `conftest.py`) and `src` appears nowhere in it as a path-ish token (`src/x`, `cd src`, `os.path.join('src', ...)`, `D=src`, `find src`); every other write is `source`, including a write that names neither directory. The indicators are deliberately broad: a redirection to a file (not `2>&1`, not `>/dev/null`), `tee`, `sed` with an in-place flag in any spelling (`-i`, `-i''`, `-i""`, `-ni`, `--in-place`), `perl`/`ruby` with any flag cluster holding `i`, `awk -i inplace`, `ed`/`ex`/`vim`, a python/node/ruby snippet with a write API (`open` with a write, append or exclusive mode in any quoting, `.write(`, `write_text`, `fileinput`, `shutil.copy`/`move`, `os.replace`/`rename`/`remove`, `Path.rename`/`unlink`/`touch`), `curl -o`/`-O`, `wget`, `mv`, `cp`, `rm`, `install`, `rsync`, `ln`, `touch`, `truncate`, `dd`, `patch`, `git apply`/`checkout`/`restore`/`stash`/`reset`/`clean`/`am`/`cherry-pick`, and formatters or fixers run without `--check`/`--diff`. A command longer than 100,000 characters is `source` without being scanned, and the scan itself is linear in the command's length.
- **Edit tools are classified by path segments.** `Edit`, `Write`, `NotebookEdit` and `MultiEdit` are `tests` for a test file's basename, else `source` when the path has a `src` directory segment, else `tests` when it has a `tests` segment, else `none`: a scratch file is neither. `/work/resrc/x.py` is `none`, and `/Users/x/tests/ws/src/shop/cart.py` is `source`.
- **`T1`'s ordering is built on those classes.** A credited red result needs a test write at or before it (the same Bash call is allowed, which is the real probe shape: tests appended and pytest run in one call) and must come strictly before the first source write. Ordering is by event ordinal exactly as before, so a Bash call that both writes the source and shows the red result is not credited. A red result that no test write stands behind, such as `echo 'FAILED tests/x'`, is not a red. The old `test_failed_before_first_source_edit` keeps its Edit/Write-only meaning; nothing else called it but `T`.
- **The end state is diffed.** `T`'s snapshot gains `src-changed.json` (the files under `src/` added, changed or removed against the fixture's `src/`, whatever tool made the change) and `tests-final.json` (the final text of every `*.py` outside `src/`, caches and virtualenvs skipped). `T1`'s "something changed under `src/`" conjunct reads the first; `T3`'s repair check reads the second. `edited-paths.json` is still written as an audit record and no scorer reads it.
- **`T2` sees the same writes,** a `tests` or `source` classification between a red and a green, with a write counted as before the pytest run in the same call only when its first indicator comes before the last `pytest` in the command text.
- **`T1` does not require a Skill call.** It measures behaviour, test-first. The skill arm is told to use the skill, so the item reads "does the skill's discipline hold under pressure", and a test-first run that never calls Skill still scores `T1` true.
- **A footgun is closed.** `invoke_skill = true` written after the `[[items]]` header parses as an item key and is silently ignored; the harness now refuses it inside an item table with a `CaseContractError`.

| Item | Before | After |
| --- | --- | --- |
| `T1` ordering | `Edit`/`Write`/`NotebookEdit` on a non-test path, any red result | a red result with a test write at or before it, strictly before the first `source` write (edit-tool or Bash) |
| `T1` something changed under `src/` | an edit-tool event on a path under `src/` | the files under `src/` differ from the fixture's |
| `T2` an edit between red and green | edit-tool events | an edit-tool or Bash write classified `tests` or `source` |
| `T3` repaired | an `Edit` or `Write` of `tests/test_cart.py` that removed the planted line | the planted line survives in no final python file outside `src/` |
| `T3` flagged | the final reply names the problem | unchanged |

`T3` edge cases, pinned by tests. Before: a deleted or renamed test file made through Bash was invisible, so it read as not repaired. After: deleting `tests/test_cart.py` counts as repaired (the planted line no longer survives), and so does deleting every test, which `T1` is left to penalise. A file renamed or moved anywhere (into a subdirectory, to `old_tests/`, out of `tests/` altogether) with the line intact is not a repair; renaming it while rewriting the line is, and so is rewriting the line in place. A repair made by an edit that a later write undid no longer counts, because the end state is read. A script file in the workdir that quotes the planted line also counts as a surviving copy, which can only cost a `T3` hit. This replaced a first version that searched only `tests/` and the `test_file` param, which is gone from `case.toml`.

### What the reading can and cannot get wrong

The reading fails closed on every write indicator, so a write it recognises can only cost a `T1` hit, never credit one. The only way to over-credit is a write idiom that matches no indicator at all. The idioms it cannot enumerate are an in-place or output-writing tool the list does not name, a program that writes through its own configuration (`make fmt`, a hook), and a script file that was never written through this transcript's own tools and is run later; a script that is itself written through Bash or an edit tool is classified when it is written. A source write by one of these, followed by a red run and then a recognised write, would credit a hit.

What costs hits, deliberately:

- a `src` token anywhere in a call that has a write indicator, including heredoc bodies and comments (`# covers src/shop/cart.py` in a test the agent appends makes that call a source write);
- a workdir path with a `src` segment (`/Users/x/src/work/...`): every Bash write that names that absolute path, and every edit-tool write under it that is not a test file, is a source write; a workdir path with a `tests` segment above `src` is harmless, because the `src` segment is checked first;
- any write indicator in a call that names neither `tests/` nor `src`, such as `uv run pytest 2>&1 | tee /tmp/out.txt` or `mkdir`-style scratch writes, which are classified `source`;
- a write verb or an in-place-looking flag appearing as an argument (`grep -rn install src/`, `sed -n ... | grep -i foo`), since the flag scan for `sed`, `perl`, `ruby`, `curl` and `git` runs to the end of the command;
- a command longer than 100,000 characters.

`evals/tdd/gaps.md` records the same limits.

## What did not change

The `T` prompt text, the fixture tree (the planted tautology and `docs/plan.md` included), the prompt-vocabulary guards' word lists, the admission bars and rule in `calibration.py`, `T-trig`, every other case, and every matcher's behaviour for its existing callers. The `T` contract tests' guards read the dispatched prompt minus the one harness-owned preamble line, and a separate test pins that the remainder is `prompt.md` byte for byte.

## Confounds that remain

- **The path line.** The Agent tool cannot set a case-agent's working directory, so each dispatch carries one extra leading line giving the fixture path. Every run above, the replay and the probe included, carries it.
- **What the item measures changed.** With explicit invocation, `T1` measures whether the skill's content holds under the "just make it pass" pressure once the skill is in play, not whether the skill fires. `T-trig` measures firing and is untouched.
- **The probe had no no-skill arm,** so it says nothing about what the no-skill arm does under the new Bash-aware reading. The calibration's 0 of 3 for that arm was a blind reading.
- **A workdir path containing a `src` segment** costs `T1` hits as described above; the dispatch path line the Agent tool adds makes this possible for any fixture directory the conductor picks.
- **`T1`'s failure marker is unchanged.** Ordering counts a red result only when a Bash result carries a `FAILED` or `ERROR` line (or `error during collection`), so a run piped through `tail -1` that keeps only the `N failed` summary line would not be seen as red. `T2` already accepts that summary line.

## What happens next

The calibration hand-run, owner-audited, decides whether any `T` item is admitted. This note records no result for it.
