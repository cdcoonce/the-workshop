---
name: gitlab-ci-watch
description: >
  Watch GitLab CI in the background until a pushed commit, a merging MR, or an
  integration branch head reaches a terminal state, reporting every job's
  status — roll-up success is never the report. Use after any push to a work
  GitLab repo (the verify-ci-green rule), after `glab mr merge` returns 405 or
  flips to auto-merge, or when post-merge CI on dev must be confirmed green —
  even when it parks on a manual promotion job. For browsing pipelines, jobs,
  or logs interactively, use gitlab-cli.
---

# GitLab CI watch

**Scope:** watch-until-terminal only. This skill owns the poll loop that was
previously hand-rolled per session; do not compose your own `while`/`sleep`
watcher, nor a pipeline query of your own when its verdict is not the one you
need — GitLab's `pipelines?ref=` also returns MR pipelines whose source branch
is that ref, listed first. Interactive inspection and retries (`glab ci list |
get | trace | retry`) stay with `gitlab-cli`.

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
SECONDS` (default 20), `--timeout SECONDS` (default 2700), and `--manual-gate
JOB`, repeatable: a manual job the pipeline is expected to rest on, such as a
`dev` pipeline's promote-to-prod button.

On a branch a release bot pushes `ci.skip` commits to, the head never gets a
pipeline, so `branch` would wait out its timeout there — watch the merged MR
with `mr IID` instead. `gitlab-promotion-flow` has the whole landing sequence.

## Exit contract

The verdict is the exit code, never the report's tone:

- **exit 0** — pipeline succeeded and every job is green; or, with
  `--manual-gate`, all that is left is a named gate and the jobs queued behind
  it, and every job that ran is green. Report and move on.
- **exit 1** — red: the pipeline failed or was canceled, or any job failed —
  including a failed `allow_failure` job under a green roll-up. Do not declare
  the work done; investigate the failing job.
- **exit 2** — indeterminate: the watch could not start (wrong cwd, missing
  remote) or crashed, timeout, the MR was closed, the pipeline is blocked on
  a manual job `--manual-gate` did not name (the verdict names it), repeated
  API failures, per-job status could not be fetched (the report says
  `re-query needed`), or **the ref cannot produce a pipeline at all** —
  `.gitlab-ci.yml`'s `workflow.rules` excludes a plain push to it, so there is
  nothing to wait for and opening a merge request is what runs CI there. Treat
  as "not verified", never as a pass — and never as a red pipeline.

## What the script already handles

Do not wrap the invocation in extra defenses: transient `glab` failures,
abbreviated SHAs, multi-remote inference, job pagination and trigger jobs,
manual and unreachable pipelines, merge-commit resolution, and SHAs that carry
several pipelines are all built in and tested — see
[references/built-in-defenses.md](references/built-in-defenses.md).

## Relaying the result

When the background task completes, relay the per-job lines to the user and
state the verdict from the exit code. On exit 1 or 2, the next step is
investigation (`gitlab-cli` — job logs, retry), not a re-run of the watcher —
unless an exit 2 verdict names a manual job you expect the pipeline to rest
on; then re-watch with `--manual-gate` for it.
