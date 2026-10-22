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

A `skipped` run is no evidence either way: it is ignored when another suite (or a
status) reports the same name, and a name with only skipped runs pends to the
timeout. One workflow triggered on both `push` and `pull_request` puts two suites
on the same SHA, and a job whose `if:` matches only one event reports `skipped`
in the other (#1283).

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
`--interval 15`. Each round, when the head is behind the live base, merges the
base into the head, runs the gate, and pushes; a head that already contains the
base skips all three (see below). Either way it then waits for `pulls/<pr>` to
show that head, watches it, re-reads the base from `git/ref/heads/<base>`, and
merges with `--match-head-commit <tested>` (never `--admin` or `--auto`). A base
that moved starts another round.

**The gate is conditional.** `--gate` tests the refreshed merge of head and a
moved base, a tree no CI has seen, and fails it before the push. When the head
already contains the base there is no such tree: the head is what its own CI
runs on, so the gate is not run and the watch of that exact SHA is the evidence.
That is the common case under a `strict` protection on a quiet base, and it is
not a skipped control. `--gate` is still required because a behind head needs it.
The skip assumes the required check covers what `--gate` runs; `land` does not
compare them, so check that once per repo.

It stops without merging — exit 2 unless noted — on: a fork or `dev`→`main` PR, a conflict
(resolve by hand; stacked PRs: `references/stacked-prs.md`), a changed patch-id, a red gate
(1) or one that did not run or lacks its evidence, a head never registered, a red (1) or
unfinished watch, `base moved <n> times`, or a failed merge: gh's stderr echoed; a
moved-base `OPEN` view re-reads 3 times before a round, `MERGED` lands, never retried. After
the merge it exits 2 if the PR is not `MERGED`, a tree is unreadable, or on `LANDED TREE
DIFFERS FROM TESTED TREE` (both ids printed) — check by hand.

Success prints exactly one ledger line and exits 0:
`landed pr=<n> tested=<sha> gate=<note> checks=<run ids>[,status:<status ids>] merge=<oid>`.
`<note>` is `exit 0` (plus the evidence match) when the gate ran, or `not run (head contained
base; CI on the tested head is the evidence)` when it did not; the `checks=` ids are that
evidence.

## `promote`

`python3 "<skill base dir>/scripts/pr_land.py" promote <pr> [--trunk dev] [--release main] [--require NAME ...] [--timeout 2700] [--interval 15]`, with Bash `run_in_background: true`, for a `dev`→`main` PR: it refuses a PR whose head lives in another repository (a fork), refuses a non-fast-forward, watches the head SHA, pushes that literal SHA to `main` (never forced), and waits for the branch and a merged PR before printing `promoted pr=<n> sha=<sha>`. Exit 2 with `Bypassed rule violations` means the SHA landed but protection was bypassed, not satisfied — report it to Charles.

The watch takes its required names from `main`'s protection, unioned with
`--require` exactly as in `watch`. When `main` is unprotected (graphmark),
protection supplies none, so pass every gate job by name with `--require`;
without it `promote` exits 2 before pushing, the same as `watch`. Name the
checks the trunk's CI runs on the head SHA, not a guess: a name that never
reports holds the watch to its timeout. A red from a flake (a runner DNS
failure, say) needs the job re-run and `promote` run again; the watch reads
each name's latest run.

Name a gate that only runs on the promotion PR with `--require` (or make it
required on the release branch). Its push-event suite on the same SHA reports
the job `skipped`, which the watch ignores beside the PR suite's verdict and
never counts as green on its own: the-workshop uses
`promote <pr> --require release-gate`.
