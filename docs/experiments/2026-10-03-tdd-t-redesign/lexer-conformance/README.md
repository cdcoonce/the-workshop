# Lexer conformance differential

The rig behind the "Sixth review pass" section of [the experiment README](../README.md). It asks one question: do `evals/_harness/bash_classify.py` and real shells agree on which text is executed as a command. It does not exercise any write, redirect-to-file or interpreter rule.

## Files

- `gen.py`: builds the strings. Fixed seed `20261004`. It composes about 100 wrapper constructs to depth 3 and adds token soup, from `echo`, `printf`, `true`, `:`, `cat` and one unknown marker command (`zzmarker`). It prints the number of distinct strings and writes `cases.jsonl` (one `[string, family]` per line) in the current directory.
- `runner.sh`: reads one case per line from stdin (newlines in a case are encoded as `\x01`), runs each under `eval` with `zzmarker` defined as a function that prints `ZZHIT` to stderr, and prints `HIT`, `SYN` (syntax error) or `NO` per case.
- `drive.py`: reads `cases.jsonl`, runs `runner.sh` under `bash --noprofile --norc` (3.2.57 was used) and `zsh -f` (5.9) in chunks of 1000 with 3 workers, kills a shell that stops producing output for 2 s and marks that case `TIMEOUT`, then calls `classify_bash_command` on every case and times it. It writes `results.json` (`res` per shell, `cls`, and `slow` for calls over 0.5 s), keeps per-chunk checkpoints in `ck/`, and uses an `empty/` directory as the working directory of the shells.

## Run

From a scratch directory (the outputs are written to the current directory, so do not run it inside the repository):

```
mkdir /tmp/lexer-run && cd /tmp/lexer-run
python3 /path/to/the-workshop/docs/experiments/2026-10-03-tdd-t-redesign/lexer-conformance/gen.py
WORKSHOP_REPO=/path/to/the-workshop python3 /path/to/.../lexer-conformance/drive.py
```

`WORKSHOP_REPO` is the checkout whose classifier is scored; unset, it defaults to the checkout containing this directory. To score another classifier version, point it at a worktree of that commit.

## Scoring

A disagreement is a case where either shell printed `HIT` and the classifier returned `none` or `tests`. The conservative direction (the classifier says `source` and neither shell ran the marker) is expected and is not a defect. `ck/` checkpoints are reused on a re-run, so delete it after changing `runner.sh` or the case set.
