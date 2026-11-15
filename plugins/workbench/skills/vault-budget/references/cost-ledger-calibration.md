# Cost ledger calibration procedure

How to measure the factor `cost_ledger.py --fixed-weight` multiplies its token estimates by. Run it on the personal machine, with a real Claude Code, once per Claude Code version you care about. The ledger side is in [command.md](command.md) and [cost-ledger-schema.md](cost-ledger-schema.md).

## The idea

The estimator guesses the tokens of the fixed context (system prompt, tool schemas, what your setup injects) from characters. To check the guess, run the same one-line prompt in fresh sessions two ways: `full` (your whole setup) and `bare` (the workbench plugin disabled). The first API call of a fresh session sends the fixed context and almost nothing else, so the difference in tokens on that call between a full and a bare session is the true weight of what the plugin adds. The estimator predicts that same difference from characters. Measured over predicted, summed over the pairs, is the factor.

## Commands and their status

Every `claude` command below was checked against the local `claude --help`, `claude plugin --help`, `claude plugin disable --help` and `claude plugin enable --help` output (Claude Code 2.1.316 when this was written); no session was started to write this document. A statement help text cannot confirm is marked `UNVERIFIED`; there are three, collected at the end.

## Prerequisites

- One Claude Code version for every run. Record it: `claude --version`. Do not update Claude Code between the first and last run; the script refuses a calibration whose sessions record two versions.
- A fresh, empty working directory, used for every run, so no project instructions or memory files vary between runs: `mkdir -p "$HOME/calibration-run" && cd "$HOME/calibration-run"`.
- The same model for every run: pass the same `--model <model>` each time (flag listed in `claude --help`), or change nothing about your default.
- The workbench plugin's id as Claude Code knows it: `claude plugin list`. The commands below write it as `<plugin>`.
- No other change to your setup (MCP servers, hooks, instructions) between runs.

## One run

The prompt is exactly this, with no other text:

```
Reply with the single word: ok
```

Give each run its own session id, so the id is known in advance and never has to be dug out of a transcript:

```
ID=$(python3 -c "import uuid; print(uuid.uuid4())")
claude -p --session-id "$ID" "Reply with the single word: ok"
echo "$ID"
```

`-p` (print and exit) and `--session-id <uuid>` (a valid UUID) are in `claude --help`. Write the id on a list, under `full` or `bare`, in the order you ran it. The transcript lands under `~/.claude/projects/<project-key>/<id>.jsonl`, which you can confirm with `find ~/.claude/projects -name "$ID.jsonl"`. `UNVERIFIED`: that a `-p` run writes its transcript there (the help says `--no-session-persistence` turns saving off for `-p`, which implies it is on by default). If the file is missing, stop; the script will refuse the id.

## The two arms

Run at least 5 sessions per arm, alternating: full, bare, full, bare, and so on, so drift in the service or in the machine falls on both arms equally. Pair i is the i-th full run with the i-th bare run.

Full run: the plugin enabled (the normal state). Run the command above.

Bare run:

1. Disable the plugin: `claude plugin disable <plugin>` (add `--scope user`, `project` or `local` to match where it is enabled, if auto-detection picks the wrong one; `claude plugin list` shows the state).
2. Run the one-run command above, in the same working directory.
3. Restore the plugin straight away: `claude plugin enable <plugin>`; check it with `claude plugin list`.

`UNVERIFIED`: that a session started right after `claude plugin disable` loads without the plugin (the help does not say when a disable takes effect). Check it once, on the first bare run: after the run, the bare transcript's skill listing must have no workbench entries, and its first call must be smaller than a full run's. If the bare run is not smaller, the plugin was still loaded; do not use the calibration.

`claude plugin disable` changes shared state, not one session: every Claude Code session started anywhere on the machine while the plugin is disabled loads without it. Close your other Claude Code sessions, or do not start any, from the first disable until you have re-enabled the plugin after the last bare run, and re-enable it immediately after each bare run, as step 3 says.

Do not leave the plugin disabled when you finish. If a run fails partway, enable it again and discard that pair's two ids (drop both, keep the order of the rest).

## Run the script

The script is `fixed_weight_calibrate.py` in the engine directory, beside `cost_ledger.py`: `plugins/workbench/machinery/engine/fixed_weight_calibrate.py` in a the-workshop checkout, or `machinery/engine/` under the installed plugin's base directory (written `<engine>` below, as in `command.md`). Run it with the ids in run order, one id per run, `full` first:

```
python3 "<engine>/fixed_weight_calibrate.py" \
  --full F1 F2 F3 F4 F5 \
  --bare B1 B2 B3 B4 B5
```

Options: `--projects-root DIR` (default `~/.claude/projects`), `--out PATH` (default: `cost_ledger_calibration.json` in the directory the `budget_burn` per-machine config is loaded from, which is where `cost_ledger.py --fixed-weight` looks without `--calibration`), `--min-runs N` (default 5, never below 2), `--claude-code-version V` (needed only when the transcripts record no version; it must match them when they do), `--date YYYY-MM-DD` (default today).

It refuses, with one line on stderr and nothing written, when: an id matches no main session file, or main files in more than one project (it says `full[2]`, the position in the arm counted from 1, never the id or a path); an id is given twice; the arms differ in size or are smaller than `--min-runs`; a session has no assistant call with usable usage; a pair predicts no more fixed tokens in full than in bare; a pair measured no more tokens in full than in bare (it says `pair[2]`, the position of the first such pair counted from 1: the plugin was not actually disabled for that bare run, or the arms are swapped or mismatched; every pair must measure a positive difference, which also guarantees `low` is above 0); the sessions record two Claude Code versions.

## What the output means

On stdout: runs per arm, the version, the mean measured and predicted token difference, the factor with its low and high, and the number of sessions without a prompt snapshot (their system prompt and tool schemas could not be counted, so the predicted side is short for them: if this is more than 0, the factor is suspect). The file holds:

- `factor`: the sum of measured differences over the sum of predicted differences. Multiply the estimator's tokens by it.
- `low`, `high`: the smallest and largest of the per-pair ratios. A wide range means the runs disagree; read the factor with the range, not alone. The report prints the setup share at factor 1, at the factor, and at low and high.
- `measured_tokens_diff` and `predicted_tokens_diff`: mean, min, max (and the sample standard deviation of the measured side).
- `runs_per_arm`, `date`, `claude_code_version`, `chars_per_token`, `sessions_without_snapshot`.

The file has numbers, a date and a version only: no session id, project key or path, so it is safe to quote.

Check the result: `python3 "<engine>/cost_ledger.py" --fixed-weight` (add `--calibration PATH` for a file elsewhere). The report drops the `UNCALIBRATED ESTIMATE` line and shows the calibration's date, runs and version.

## What to record on the issue

Numbers only: factor, low, high, runs per arm, Claude Code version, date. Nothing from the transcripts.

## What the factor does and does not cover

- It is measured on the first call of a main session, with a one-line prompt, on one Claude Code version. It says how far off the character estimate is for that call.
- The estimator applies it to every transcript file, subagent files included. A subagent has its own system prompt and tool set, and the characters-per-token ratio of that text is known to differ from a main session's, so the factor is a better fit for main sessions than for subagents.
- It does not cover text that changes over a session (conversation, tool results) or components added later in a session; the estimator already counts only what was sent before the first call.
- It goes stale when Claude Code changes its system prompt or tools. Re-run the procedure on a new version.

## Unverified

1. That a `-p` run with `--session-id` writes `<project-key>/<id>.jsonl` under the projects root.
2. That a session started after `claude plugin disable <plugin>` loads without the plugin.
3. That `claude plugin enable <plugin>` restores it for the next session started (the help says only "Enable a disabled plugin").
