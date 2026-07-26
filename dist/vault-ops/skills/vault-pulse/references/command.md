# /pulse — weekly work-quantification ledger

Run the pulse engine and present the trend. The script does all the heavy lifting (scans local Claude transcripts + Codex rollouts for interactive attention hours, afk `telemetry.jsonl` across enrolled repos, the vault's git history, task snapshots, and the Brag Doc); this command runs it and interprets.

**Arguments:** $ARGUMENTS — optional `--weeks N`, `--backfill`, `--json`, `--machine work|personal`.

## Procedure

1. Run: `python3 .claude/scripts/pulse.py $ARGUMENTS` (add `--json` for structured numbers).
2. Present the weekly table as-is, then add interpretation:
   - **Trend rule:** compare the latest week to the rolling 4-week median. Flag a downtrend only on **2+ consecutive weeks below** the band — single bad weeks are noise.
   - **Attention vs output:** `attn_*` columns are the leading indicator (interactive hours move first when the schedule tightens); `afk_merged` is the autonomous pipeline and does **not** measure Charles's attention — never present blended totals.
   - **School watch:** Charles does coursework **in Claude and in the vault** (just not through afk), so `attn_school_h` is a real measured number, not a stub — read the tradeoff directly as `attn_school_h` rising against `attn_build_h` falling. Hours spent off-tool (lectures, reading) are still invisible, so treat `attn_school_h` as a floor on school time. Per [[asu-fall-2026-course-selection]] the load is gentle from Aug 20 and roughly doubles from Oct 14 — expect the real test in November, and compare against the Aug baseline rather than against October.
3. If the user gives energy/satisfaction ratings (1–5), write them into the manual `energy`/`satisfaction` columns of the current week's row in the ledger — the engine never overwrites them.

## What the attention number is, exactly

`attn_*` measures **hours an interactive session was active**, gap-clustered at 15 minutes — not hours of human focus. A session where Charles sets a task and an agent works for an hour counts that hour. Treat it as an upper bound on attention whose bias is roughly constant, which is what makes the week-over-week trend meaningful even though the level is generous.

Attribution follows the **path a session touches** (from its tool-call inputs), not the directory it was launched from — nearly every session starts in the vault and works cross-repo, so launch-dir attribution booked ~100% of hours to `vault`. It resolves to a _scope_ (`repo/dir/subdir`, two directories deep), not just a repo, because coursework lives **inside** the vault: a repo-level key would book school hours to `vault` and inflate the very number whose decline this tool exists to detect.

**Keep coursework in a directory whose name the rules match** — `school/`, `coursework/`, `asu/`, or a course code (`cse511`, `hse542`). The rules key off **directories, not filenames**, so `the-vault/school/cse511/hw1.md` reads as school while a stray `personal/cse511-notes.md` reads as vault. Add patterns to `pulse_config.py` if the naming changes.

Domain columns are each a union and **overlap**: two scopes worked in parallel share wall clock, so they need not sum to `attn_total_h`.

## Notes

- The ledger is **per-machine**: `perf/metrics/pulse-<machine>.csv` (machine from `.vault-context`). Attention/tokens/afk columns reflect **this machine only**; the `vault_sessions_*` and `deliberate_commits_*` columns come from vault git history and see **both** machines. Union the two CSVs when charting.
- Rows older than the recompute window are **frozen** — Claude transcripts get pruned, so old weeks can't be recomputed. Don't "fix" old rows by re-running with a huge window unless you know the sources still cover them.
- `tasks_done` is a **level** (checked boxes in that week's snapshot), not a flow — tasks archive out between weeks; treat deltas as directional.
- Known bias, by design: attention counts only Claude + Codex on this machine. Cortex (work machine) and non-agent work (meetings, Excel, reading) are invisible — the trend is valid while the tool mix is stable; revisit the collectors if it shifts.
- Config lives in scaffold-owned `pulse_config.py` (domain rules, gap threshold, automation patterns); shipped defaults in `pulse_defaults.py`. Don't change `GAP_MINUTES` mid-series — old and new rows stop being comparable.
- Related: [[deduped-logs-fake-a-trend]] (why `auto_promote_decision` records are never counted), the /budget skill (same transcript scan, spend-only).
