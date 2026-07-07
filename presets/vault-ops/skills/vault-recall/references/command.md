# /recall — Post-Build Consolidation (Sleep-Time Recall)

Close the recall seam: distill afk build outcomes (merged PRs, telemetry) into the vault — stub notes in the graph, brag candidates, fresh handoff — so the next live session starts pre-digested instead of doing batch recall work on frontier tokens. This is the vault's sleep-time consolidation pass (see [[2026-06-11-unified-dev-system-design]]).

## Launch contract

Human-launched only — never put this on cron. Run it on a **cheap model**; consolidation is batch distillation, not frontier judgment:

```bash
claude --model haiku -p "/recall"           # real run: writes, commits, pushes
claude --model haiku -p "/recall dry-run"   # gathers + prints the plan, writes nothing
```

If a step genuinely needs deep judgment, do NOT escalate the model — leave a one-line TODO in the run digest for the next live session.

## When to run

- After an afk drain / merge lands (on your way out is the canonical moment).
- Before `/standup` if the vault feels behind the build reality.
- NOT as a `/wrap-up` replacement — `/wrap-up` audits the live session; `/recall` digests the build pipeline. They overlap only at the handoff refresh.

## Procedure

1. **Read state.** `.brain/recall-state.json` holds `last_run` (ISO date) and a `repos` list (default: `["cdcoonce/afk-agent-system"]`). Missing file = first run: window is the last 14 days. The state file rides git like the handoff.
2. **Gather — commands only, no subagents, no diffs.** For each repo in `repos`:
   - `gh pr list --repo <repo> --state merged --search "merged:><last_run>" --json number,title,mergedAt,baseRefName,body,closingIssuesReferences`
   - For the afk repo also run exactly: `uv run --directory /Users/cdcoonce/Developer/GitHub/afk-agent-system afk-driver --project . --repo cdcoonce/afk-agent-system --telemetry-report` (this exact invocation is pre-allowed in `.claude/settings.json` — don't `cd` or rephrase it, a different form will hit a permission prompt headless runs can't answer; read the report, never raw `telemetry.jsonl`).
3. **Apply the salience filter** (see below). Cap at **10 stub-worthy PRs per run** — if more, take the most recent 10 and note the remainder in the digest; the next run picks them up (set `last_run` to the oldest unprocessed PR's merge date).
4. **Write one stub note per salient PR** → `personal/projects/builds/<repo-short>-pr-<N>.md` (e.g. `afk-pr-318.md` — the `pr` segment is required so PR stubs never collide with issue-numbered notes):

   ```markdown
   ---
   date: <merge date YYYY-MM-DD>
   description: "<one-line: what this PR changed and why it mattered>"
   tags:
     - build
     - <repo-short>
   ---

   # <repo-short> PR #<N> — <title>

   <2–4 sentences distilled from the PR body: what changed, why, outcome.
   Telemetry line if available: slices, cost, quarantine count.>

   Closes: <issue refs as links>. Part of [[afk-agent-system]].
   Related: [[<project note>]] · <competency wikilinks if obvious, e.g. [[Data Modeling]]>
   ```

   Frontmatter and ≥1 wikilink are mandatory (validate-write enforces this).

5. **Update `personal/Index.md`** — add stubs under a `### Builds` subsection of projects. One line each.
6. **Run the `brag-spotter` agent** over only the stubs created this run (skip if zero). Let it propose Brag Doc entries; write the ones that meet its own bar — autonomous vault writes are approved, git is the undo.
7. **Run the `cross-linker` agent** over only the files created/modified this run (skip if zero).
8. **Refresh the handoff** per `/handoff` — fold in what landed (one line per stub, linked) and clear anything the merges resolved.
9. **Write state + sync.** Update `.brain/recall-state.json` (`last_run` = now). Commit everything: `vault: /recall consolidation YYYY-MM-DD` and push per `/sync`.
10. **Print the run digest:** stubs written, brag entries added, links fixed, TODOs left for the live session, PRs deferred by the cap.

**Dry-run mode:** steps 1–3 in full — including the telemetry report; dry-run skips _writes_, never _gathering_ — then print what steps 4–9 _would_ do and stop. No writes, no commits.

## Salience filter (Charles's dial — edit this section freely)

Default rules until tuned:

- **Stub-worthy:** PRs merged to `main` or an epic branch (these are human-gated, therefore significant by construction).
- **Skip:** slice PRs into `afk/staging` or epic branches — their epic MR aggregates them; a stub per slice is noise.
- **Brag-candidate signal** (pass to brag-spotter as a hint, not a verdict): epic MRs, multi-slice PRs with 0 quarantined, and self-improvement PRs (afk building afk).

## Constraints

- **Cheap model, bounded scope.** Commands over subagents; agents run only on this run's delta; never read PR diffs or raw telemetry; never crawl the vault.
- **Stubs are stubs.** 2–4 sentences + links. If a build deserves a real note, leave a TODO in the digest — don't write essays on a haiku budget.
- **Never delete or rewrite existing notes** (handoff and indexes excepted — those are digests by contract).
- **Fail loud.** If `gh` or `afk-driver` errors, report and stop — don't write a partial consolidation or advance `last_run`.
