# /budget — Claude API spend / subscription-value meter

Run the budget engine and present it. The script does all the heavy lifting (scans every local Claude Code transcript, dedups by API call, computes cost by model × published rates); this command just runs it and interprets.

**Arguments:** $ARGUMENTS — optional `--month YYYY-MM`, `--budget N`, `--context work|personal`.

## Procedure

1. Run: `python3 "<engine>/budget_burn.py" $ARGUMENTS` (add `--json` if you need the structured numbers).
2. Present the output as-is, then add one line of interpretation:
   - **Personal (subscription, value-meter):** this is API-equivalent value the flat subscription delivered — no per-token cap. Frame it as "what your subscription is worth," not a budget to fear.
   - **Work (enterprise, gate):** spend against the ~$350 enterprise cap. If projected month-end is over cap, flag it and point at the lever (below).
3. **Always surface the Opus %** — it's the conductor-health metric (see the Operating Model in root `CLAUDE.md`). High Opus % = lots of judgment-and-retrieval still bundled on the expensive model; the lever is delegating bulk reads to Sonnet/Haiku workers. Low Opus % = the conductor discipline is working.

## Ledger by session and agent

For "where did it go" rather than "how much", run `python3 "<engine>/cost_ledger.py" [--since YYYY-MM-DD] [--until YYYY-MM-DD] [--json PATH] [--meter-usd N] [--export-aggregates PATH] [--fixed-weight] [--calibration PATH] [--projects-root DIR]`. Both dates are inclusive and judged on the UTC date of each call's own timestamp (a `Z` or numeric-offset ISO-8601 string; one that cannot be parsed is undated and counted, not windowed); with neither flag the window is the current calendar month. A malformed date, `--since` after `--until`, a `--projects-root` that is not an existing directory, or a `--json` path that cannot be written exits 2 with one stderr line; a bad window or root writes nothing.

It prints the window, the window total, the main-versus-subagent split in dollars and percent, subagent dollars by agent type and by model, the ten most expensive sessions, a skills table (the fifteen skills with the most dollars, ties by name, then one `N more skills` line (`1 more skill` for one) summing the rest, then an always-present `(unattributed)` row (parenthesised so a skill literally named `unattributed` cannot print the same label) with its percent of the window total, then a line saying skill rows are a lower bound because the invoking call and later-turn work are not counted), one coverage line (files found, read and skipped, malformed lines, undated calls), and, only when there are any, the models it could not price. Undated calls are excluded from every figure and counted on the coverage line. `--json PATH` also writes one row per session with one row per agent inside it (the main session and each subagent, typed from its `meta.json`, else its attribution, else `unknown`); it also writes one row per skill with `sessions`, and an `unattributed` object, which together sum to the totals (a call's skill is its own record's `attributionSkill`, taken exactly as written); two runs over the same files and window write byte-identical files. Prices come from the same table `budget_burn.py` uses, so totals agree. Every field of the JSON is documented in [cost-ledger-schema.md](cost-ledger-schema.md) (schema version 4).

### Meter check and recorded cost

`--meter-usd N` takes the dollar figure you read by hand from Claude Code's usage view for the same window. N must be a finite number greater than 0, else the command exits 2 with one stderr line and writes nothing. The report then starts with a meter block (ledger total, meter figure, signed difference as ledger minus meter, gap percent), and when the gap percent, rounded to six decimal places, is strictly more than 10, in either direction, a `METER GAP` line above it; exactly 10 percent does not flag. The JSON gains a top-level `meter` (`null` without the flag).

The recorded-cost check runs on every report with no flag: it compares whole-session ledger dollars with the cumulative cost Claude Code records in the session file, for the sessions where the two cover the same calls, and prints one line for those sessions and, when there are any, one line for sessions whose recorded cost includes a model Claude Code could not price (reported, not compared). It never prints a warning and never changes the exit code. The comparability conditions are in [cost-ledger-schema.md](cost-ledger-schema.md).

### Aggregates-only export

`--export-aggregates PATH` writes a second JSON file meant to be shared: totals, per-model and per-agent-type dollars, skills, the unattributed bucket, the spread of per-session dollars (min, quartiles, max), coverage counts, unpriced models, the meter block and the recorded-cost check. Sorted keys, 2-space indent, trailing newline, dollars rounded to six places, byte-identical across runs; an unwritable path exits 2 with one stderr line, and when both `--json` and `--export-aggregates` are given and either cannot be written, neither file is written or changed. It is built from an allow-list and holds no project key, path, session id, agent id or call timestamp, and no text from any record except model names, skill names and agent type names, which it carries as written. Read those names before sharing the file: a skill or agent type name chosen by you or a plugin appears verbatim.

### Fixed weight

`--fixed-weight` adds an estimate of what the fixed context cost: the system prompt, the tool schemas and what your setup injects (skill and agent listings, instructions, hook context, MCP servers), which every call of a session sends again. The report gains a `FIXED WEIGHT` section, and the JSON gains a filled `fixed_weight` object (`null` without the flag, in which case no estimation work is done). Each transcript file, main session or subagent, is sized in characters from its own records, converted to tokens at 3.7 characters per token times a calibration factor, and charged per call at the rate that call paid: the cache-write rate when the call wrote at least that much to the cache, else the cache-read rate, never more than the call's own dollars. The costing rule, the two groups (`setup`, the upper bound on what removing your setup would save, and `claude_code`, present regardless) and every field are in [cost-ledger-schema.md](cost-ledger-schema.md). The section opens with the line `UNCALIBRATED ESTIMATE` until a calibration file supplies a factor; it states no verdict.

`--calibration PATH` names a JSON file with a finite `factor` greater than 0 (other keys are ignored). Without the flag the file is `cost_ledger_calibration.json` in the directory the `budget_burn` per-machine config is loaded from. No file means factor 1.0, uncalibrated; a file that exists but is unreadable, is not an object, or has a missing or invalid `factor` exits 2 with one stderr line and writes nothing. `--calibration` does nothing without `--fixed-weight`. The aggregates export carries `fixed_weight` unchanged; it holds only fixed component names and numbers.

## Notes

- The number is **machine-local** — it reflects this machine's Claude Code usage only. The work/enterprise $350 gate only means something on the work machine; on personal it's a value meter.
- Rates and the dedup-by-`requestId` fix live in the script. If the number looks implausible, suspect a rate change or a transcript-format change — verify against Claude Code's own `/cost` for a single session before trusting a big swing.
- Related: [[2026-06-16-conductor-workers-operating-model]], [[Key Decisions]] (Conductor + Workers).
