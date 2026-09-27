---
name: github-pr-land
description: >
  Lands a GitHub PR only at a CI-tested head: refreshes a moved base, re-gates, waits on that exact SHA, merges pinned. Use to merge, land, or ff-promote a PR, or to watch CI on a pushed SHA.
---

# GitHub PR land

A PR is safe to merge only at a head whose own CI went green. This skill owns
that wait: it reads the required checks of **one exact SHA** and never a
roll-up. Do not hand-roll a `gh pr checks` loop, a `statusCheckRollup` query,
or a read of `commits/<sha>/status` — on these repos the combined state reads
`pending` with `total_count: 0` forever, so a watcher built on it never ends
or, worse, is read as green.

## Exit contract

| Exit | Meaning                                                                                                      |
| ---- | ------------------------------------------------------------------------------------------------------------ |
| `0`  | green — every required check is `completed:success` (check run) or `success` (status)                        |
| `1`  | red — `failure`, `cancelled`, `timed_out`, `action_required`, `startup_failure`, or status `failure`/`error` |
| `2`  | indeterminate — timeout, `neutral`/`skipped`/`stale`, unknown outcome, no required checks, or a refusal      |

Only `0` means go. Never read `2` as "probably fine".

## Shared conventions

- **Run inside a clone of the PR's repo.** The script resolves the repo with
  `gh repo view` and refuses (exit 2) unless `origin` names the same
  `owner/name`.
- **`-R` everywhere.** Every `gh` call is pinned: `gh api` endpoints start
  `repos/<owner>/<name>/`, every other subcommand carries `-R <owner>/<name>`.
- **SHAs from the API, full length.** An abbreviated SHA is expanded with
  `git rev-parse --verify <sha>^{commit}`; anything that is not a commit
  exits 2.

## `watch`

```bash
python3 "<skill base dir>/scripts/pr_land.py" watch <sha> --branch <base>
```

Run it with Bash `run_in_background: true` — foreground `sleep` is blocked,
and the watch produces exactly one completion notification. `<skill base dir>`
is the absolute path this skill's loader announces; expand it inline, it is
not a shell variable.

Flags: `--branch B` (read required checks and app pins from `B`'s
protection), `--require NAME` (repeatable; unioned with protection, never
replacing it), `--timeout 2700`, `--interval 15`.

How it decides:

- Required names are the union of `--require` and the base branch's
  `required_status_checks.contexts`. A branch that is not protected
  contributes none; any other protection read failure exits 2. An empty set
  exits 2 — nothing to wait on is not green.
- Check runs and statuses are read for that SHA, every page. When protection
  pins an `app_id` to a name, only that app's check runs count and statuses
  never do.
- Per name, the latest run of **each check suite** and the newest status
  count. A failed suite is not hidden by a green one elsewhere; a re-run in the
  same suite replaces its failure. It decides only once nothing is pending.

Output is one line per accepted item — `<name> suite=<id> run=<id>
<conclusion>` or `<context> status=<id> <state>` — so every verdict traces
back to the run it came from.

## `land`

Run it only when Charles has explicitly asked for that PR to be merged, and
with Bash `run_in_background: true`.

```bash
python3 "<skill base dir>/scripts/pr_land.py" land <pr> --method squash --gate "make test"
```

`--method {merge,squash,rebase}` and `--gate CMD` are required. Optional:
`--gate-evidence REGEX`, `--require NAME`, `--accept-delta-change`,
`--max-rounds 3`, `--trunk dev`, `--release main`, `--timeout 2700`,
`--interval 15`. Each round merges the live base into the head, runs the gate,
pushes, waits for `pulls/<pr>` to show that head, watches it, re-reads the base
from `git/ref/heads/<base>`, and merges with `--match-head-commit <tested>`
(never `--admin` or `--auto`). A base that moved starts another round.

It stops without merging — exit 2 unless noted — on: a fork or `dev`→`main`
PR, a conflict (resolve by hand), a changed patch-id, a red gate (1) or one
that did not run or lacks its evidence, a head never registered, a red (1) or
unfinished watch, `base moved <n> times`, or a failed merge (gh's stderr
echoed). After the merge it exits 2 if the PR is not `MERGED` or on
`LANDED TREE DIFFERS FROM TESTED TREE` (both tree ids printed) — investigate
the landed commit by hand.

Success prints exactly one ledger line and exits 0:
`landed pr=<n> tested=<sha> gate=<note> checks=<run ids> merge=<oid>`.

## `promote`

`python3 "<skill base dir>/scripts/pr_land.py" promote <pr> [--trunk dev] [--release main] [--timeout 2700] [--interval 15]`, with Bash `run_in_background: true`, for a `dev`→`main` PR: it refuses a non-fast-forward, watches the head SHA, pushes that literal SHA to `main` (never forced), and waits for the branch and a merged PR before printing `promoted pr=<n> sha=<sha>`. Exit 2 with `Bypassed rule violations` means the SHA landed but protection was bypassed, not satisfied — report it to Charles.
