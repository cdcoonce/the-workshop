# /debrief — Pipeline Retrospective and Skill Feedback

Measure how much of the afk pipeline's finished work needed Charles's hands, attribute each intervention to the stage that caused it, and turn the top one or two into evidence-backed edits to the **source** skills. This is the loop that keeps the pipeline from decaying: without it, the same spec defect gets rebuilt every week and nobody notices.

**Arguments:** `$ARGUMENTS` — optional `--since YYYY-MM-DD` (default: last debrief, else 14 days) and `--dry-run` (measure and report, write nothing).

## Boundary with the neighbours

Four skills read the same pipeline; they answer different questions. Do not merge them.

| Skill      | Question                                    | Writes                        |
| ---------- | ------------------------------------------- | ----------------------------- |
| `/pulse`   | Is Charles's attention and output trending? | `perf/metrics/pulse-*.csv`    |
| `/recall`  | What did the pipeline build?                | build stub notes in the graph |
| `/wrap-up` | Was this live session's vault work clean?   | note fixes, handoff           |
| `/debrief` | Did the pipeline need Charles?              | retro ledger + skill edits    |

`/pulse` counts `afk_merged` — a count of merges says nothing about whether they were any good. `/debrief` is the only one that measures **intervention** and the only one authorised to **edit skills**.

## When to run

- Weekly, after a drain has landed and `/recall` has run. Cheap model; this is arithmetic and attribution, not frontier judgment.
- After any run that quarantined 2+ slices — don't wait for the week.
- NOT after a single merged PR. The metric is a ratio and a ratio over a handful of PRs is noise (see the floor rule).

## The hands ratio

The number is only worth having if it is falsifiable, so the definition is mechanical, not a judgment call.

**A merged PR needed hands if any of these is true:**

1. A commit on its branch is not an `AFK: implement issue #N` commit — someone fixed it by hand.
2. It carries review comments requesting changes, not just approval.
3. Its issue was quarantined at least once before the run that merged it.

`hands_ratio = PRs needing hands / PRs merged in window`

**State the denominator every time.** Below 5 merged PRs, report the raw counts and explicitly refuse to state a trend — a 1-of-3 week and a 1-of-4 week are the same week.

**Known blind spot, always disclosed:** a defect Charles fixes forward on `dev` _after_ the merge is invisible to all three tests. The ratio is therefore a **floor** on intervention, not a total. Do not present it as a total, and do not silently patch the definition to chase a nicer number — changing the definition ends the series, same as `/pulse`'s `GAP_MINUTES`.

## Attribution — which stage failed

A ratio tells you something is wrong; this table tells you what to edit. Attribute every intervention to exactly one stage.

| Signal                                         | Failing stage       | Where the fix goes                                                         |
| ---------------------------------------------- | ------------------- | -------------------------------------------------------------------------- |
| Quarantine `question`, or `cold-read:rewrite`  | Specification       | `/dispatch` body shape, or a `/cold-read` detector                         |
| Quarantine `scope`                             | Sizing              | `/dispatch` step 2 (the `afk-sized` test)                                  |
| Quarantine `capability`                        | Environment         | target repo's `CLAUDE.md` conventions                                      |
| Hand fixup, no quarantine, criteria had passed | Acceptance criteria | `/cold-read` detectors 2 and 3 — the criteria were satisfiable while wrong |
| Review comments on style/structure only        | Nothing             | Not an intervention worth a skill edit; note and drop                      |

**The article's rule, kept:** a high hands ratio is a **spec** problem, not a review problem. The instinct is to make the morning review faster. Resist it — a faster review of work that shouldn't have been built that way is the wrong optimisation.

## Cold-read effectiveness — the self-falsifying check

`/cold-read` exists to lower this ratio. Test whether it does:

- `hands_ratio` for issues labelled `cold-read:pass`, versus
- `hands_ratio` for issues that skipped cold read entirely.

If the cold-read cohort is not meaningfully lower once both cohorts clear the 5-PR floor, **say so plainly**: cold read is costing a subagent per issue and buying nothing, and the detectors need rewriting or the gate needs removing. A skill that cannot be shown to work is theater, and this is the one place that gets checked. Report the comparison every run, including the runs where the cohorts are too small to conclude anything.

## Procedure

1. **Read logs before asking Charles anything.** He is the last source, not the first. Ask only what the logs cannot answer.
2. **Resolve the window.** `.brain/debrief-state.json` holds `last_run` and `repos`. Missing file = first run, 14-day window.
3. **Gather** — plain commands, no subagents:
   - `gh pr list --repo <repo> --state merged --search "merged:><last_run>" --json number,title,mergedAt,commits,reviews,closingIssuesReferences`
   - `gh issue list --repo <repo> --state all --search "closed:><last_run>" --json number,labels` for the `cold-read:*` and quarantine labels.
   - The afk telemetry report — use the exact pre-allowed invocation documented in `/recall` step 2; do not rephrase it or `cd` first, or it will hit a permission prompt an unattended run cannot answer. The path in that invocation is machine-specific; on a machine without the afk checkout, skip telemetry and say the quarantine signals are unavailable.
4. **Compute** the ratio, the denominator, and the two cohorts. Attribute every intervention to one stage.
5. **Find the repeats.** A single intervention is an anecdote. Only a stage that failed **twice or more in the window**, or once in each of the last two windows, earns an edit. Everything else is recorded and left alone.
6. **Propose at most two skill edits.** Each must cite the specific issue or PR numbers that motivated it. Show the diff and get approval before writing — never edit a skill unprompted.
7. **Append to the retro ledger** — `perf/metrics/debrief-<machine>.md`, machine from `.vault-context`, newest entry last, never rewritten. One entry per run: window, denominator, ratio, cohort comparison, attribution counts, edits proposed and whether they were accepted. This file is the permanent retro; patterns only become visible across entries, so nothing here is ever edited retroactively.
8. **Digest:** ratio with its denominator, the trend call (or a refusal to call one), cold-read effectiveness, the stage that failed most, the proposed edits, and what was left alone.

## Skill edits go to the source, never the vault copy

Skills are not vendored into the vault any more. They ship from `workbench@the-workshop` and run out of the installed plugin, so there is no vault-side copy to edit — and nothing in the vault to edit it in.

An accepted skill edit is therefore a change to `plugins/workbench/skills/<skill>/` in the the-workshop checkout, on a branch, into a PR against `dev` — then reinstall or upgrade the plugin to pick it up. Bump the plugin version; `make test` enforces the rule via `scripts/check_version_bumps.py`, and Plugin Versioning in `CLAUDE.md` is the spec. Instruction changes with an unchanged component inventory are a **patch**. If a debrief edit ever lands anywhere but the-workshop, that is the bug.

## Anti-theater

This skill's failure mode is a tidy weekly report that changes nothing.

- **A debrief that proposes no edits is a valid outcome** — say "nothing repeated; no edits" and stop. Manufacturing an edit to look productive is worse than the empty report.
- **Two edits is the ceiling.** A debrief that wants to rewrite four skills has diagnosed nothing; pick the one with the most evidence behind it.
- **No edit without a cited issue or PR number.** "It felt like the specs were vague" is not evidence.
- **Never move a target to make a number look good.** If the ratio is bad, the ratio is bad.
- Do not fix the underlying bugs here. `/debrief` edits **process**; the code fixes are `/dispatch` and the executor's job.

## Constraints

- **One window per run.** Do not re-debrief a window already in the ledger.
- **Read-only against target repos.** This skill never merges, promotes, or closes anything.
- **Cheap model.** If a step genuinely needs frontier judgment, leave a TODO in the digest rather than escalating.
