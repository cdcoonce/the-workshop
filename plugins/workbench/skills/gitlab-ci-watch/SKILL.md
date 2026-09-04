---
name: gitlab-ci-watch
description: >
  Watch GitLab CI in the background until a pushed commit, a merging MR, or an
  integration branch head reaches a terminal state, reporting every job's
  status — roll-up success is never the report. Use after any push to a work
  GitLab repo (the verify-ci-green rule), after `glab mr merge` returns 405 or
  flips to auto-merge, or when post-merge CI on dev must be confirmed green.
  For browsing pipelines, jobs, or logs interactively, use gitlab-cli.
---

# GitLab CI watch

**Scope:** watch-until-terminal only. This skill owns the poll loop that was
previously hand-rolled per session; do not compose your own `while`/`sleep`
watcher. Interactive inspection and retries (`glab ci list | get | trace |
retry`) stay with `gitlab-cli`.

## Invocation

Run the script with Bash `run_in_background: true` — foreground `sleep` is
blocked in the harness, and the watch produces exactly one completion
notification. `cwd` must be the target repository: the script reads the
remote URL and resolves SHAs there.

```bash
python3 "<skill base directory>/scripts/ci_watch.py" sha
```

`<skill base directory>` is the absolute path this skill's loader announces
(the line reading `Base directory for this skill: /…/skills/gitlab-ci-watch`).
Expand it inline while composing the command — it is **not** a shell variable,
and `$CLAUDE_PLUGIN_ROOT` exists only in the hook environment (#686). A bare
`scripts/ci_watch.py` fails for the mirror-image reason: `cwd` is the target
repository, which does not contain this skill.

## Modes

| Mode                       | When                                                               | Behavior                                                                                                                                               |
| -------------------------- | ------------------------------------------------------------------ | ------------------------------------------------------------------------------------------------------------------------------------------------------ |
| `sha [COMMIT] [--ref REF]` | after any push                                                     | Watches **every** pipeline for the commit (default `HEAD`, expanded to the full 40-char SHA) — newest per ref — and is green only when all of them are |
| `mr IID`                   | after `glab mr merge` did not provably merge (405, auto-merge)     | Polls the MR state, bails loudly if it is closed, then watches the merge commit on the target branch                                                   |
| `branch NAME`              | post-merge integration check                                       | Resolves the **remote** head via `git ls-remote` (the local clone may be behind) and watches it on that ref                                            |
| `pipeline ID`              | one specific pipeline is the question (e.g. a SHA carries several) | Watches that pipeline id until terminal, with the same per-job report and exit contract                                                                |

Common flags — placed **after** the mode, not before it: `--remote NAME`
(default `origin`), `--project GROUP/PROJECT` (override when the remote URL
should not be trusted — e.g. multiple gitlab.com remotes), `--interval
SECONDS` (default 20), `--timeout SECONDS` (default 2700).

## Exit contract

The verdict is the exit code, never the report's tone:

- **exit 0** — pipeline succeeded and every job is green. Report and move on.
- **exit 1** — red: the pipeline failed or was canceled, or any job failed —
  including a failed `allow_failure` job under a green roll-up. Do not declare
  the work done; investigate the failing job.
- **exit 2** — indeterminate: the watch could not start (wrong cwd, missing
  remote) or crashed, timeout, the MR was closed, the pipeline is blocked on
  a manual job, repeated API failures, or per-job status could not be fetched
  (the report says `re-query needed`). Treat as "not verified", never as a
  pass — and never as a red pipeline.

## What the script already handles

Do not wrap the invocation in extra defenses — these are built in and tested:
transient `glab` failures (stderr noise, empty stdout, nonzero exits) skip a
tick instead of killing the watcher; abbreviated SHAs are expanded before
querying (an abbreviated `pipelines?sha=` matches nothing and reads as pending
forever); the project path is derived from the remote URL and passed
explicitly, so glab's alphabetical multi-remote inference is never consulted;
job listings paginate past 100 jobs and include trigger jobs (bridges), so a
red downstream pipeline cannot pass as green; a pipeline stuck on a manual
job terminates the watch instead of holding it for the full timeout; on a
merged MR the merge commit is watched (the squash commit only when the merge
fast-forwarded), with a fresh timeout budget for the post-merge watch; a SHA
carrying both an MR-head pipeline and a branch pipeline is judged across every
ref's newest pipeline, with `--ref` enforced on the response as well as the
query — a green MR pipeline cannot mask a red branch pipeline on the same
commit (a retried run on the same ref still supersedes the old one).

## Relaying the result

When the background task completes, relay the per-job lines to the user and
state the verdict from the exit code. On exit 1 or 2, the next step is
investigation (`gitlab-cli` — job logs, retry), not a re-run of the watcher.
