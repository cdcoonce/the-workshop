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

**Tuned 2026-07-10.** The original "every main-merge is stub-worthy" rule assumed main-merges were rare and aggregate. They aren't: afk merges per-slice and small integration drains straight to `main` at high volume — one month left **166** unstubbed main-merges (a ~17-run backlog at 10/run). Measured against that month, the vast majority are substantive-but-*maintenance* `fix(...)` PRs whose detail already lives in the issue they close and in the synthesized narrative in `personal/projects/afk-agent-system.md` (the resume note is the real digest; builds/ stubs are only durable per-*capability* graph nodes + brag evidence). So the bar is now **new capability + aggregate landmark, not every substantive merge.** Same tuning measured **45** stub-worthy (a ~5-run catch-up, then ~1–2 runs/week going forward). A skipped PR is not lost — its work lives in its closed issue, and brag-spotter still sees the full merged-PR stream, so a landmark `fix` can still become a Brag entry without a per-PR stub.

Decide with the fields already gathered in step 2 (`title`, `baseRefName`, `closingIssuesReferences`) — no extra API calls.

- **Stub-worthy — epic MRs:** a PR from an `afk/epic-*` branch to `main`, or whose title contains "epic". Large feature sets, human-gated by construction.
- **Stub-worthy — substantial integration MRs:** a `staging → main` integration MR closing **≥ 4 issues** (`closingIssuesReferences | length >= 4`). A real batch worth one node; the per-slice detail lives in the closed issues.
- **Stub-worthy — new-capability direct-to-main PRs:** a PR merged straight to `main` whose title is **`feat(...)` / `feat:`** — a new capability or subsystem (the genuine landmark: a new substrate, gate, conductor phase, mailbox, egress control, backend, module). These are the afk-building-afk milestones worth a durable graph node.
- **Skip — per-slice churn:** individual `AFK: afk/issue-N` slice PRs (and `AFK recovery:` PRs) merged to `main` (F1), and every slice PR into `afk/staging` / an epic branch. Aggregated elsewhere or captured by the issue; a per-slice stub is noise.
- **Skip — routine integration MRs:** a `staging → main` MR closing **< 4 issues**. Low marginal signal.
- **Skip — maintenance direct-to-main PRs:** `fix` / `test` / `docs` / `chore` / `refactor` / `ci` / `build` / `style` / `perf`-prefixed (and unprefixed) direct merges. Substantive but not new-capability — their detail lives in the closed issue + the resume note. (If one is a genuine milestone, brag-spotter surfaces it from the PR stream, and you can hand-write a stub for it — the filter is the default, not a cage.)
- **Brag-candidate signal** (pass to brag-spotter as a hint, not a verdict): epic MRs, multi-slice MRs with 0 quarantined, and self-improvement PRs (afk building afk).
- **Backlog awareness:** after applying this filter, if **> 20** stub-worthy PRs still remain past the 10-cap, note the count and the oldest-unprocessed date in the run digest and recommend a short catch-up loop (repeat `/recall` runs) rather than silently trickling one batch and looking caught-up.

## Constraints

- **Cheap model, bounded scope.** Commands over subagents; agents run only on this run's delta; never read PR diffs or raw telemetry; never crawl the vault.
- **Stubs are stubs.** 2–4 sentences + links. If a build deserves a real note, leave a TODO in the digest — don't write essays on a haiku budget.
- **Never delete or rewrite existing notes** (handoff and indexes excepted — those are digests by contract).
- **Fail loud.** If `gh` or `afk-driver` errors, report and stop — don't write a partial consolidation or advance `last_run`.
