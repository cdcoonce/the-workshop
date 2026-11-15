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

For "where did it go" rather than "how much", run `python3 "<engine>/cost_ledger.py" [--since YYYY-MM-DD] [--until YYYY-MM-DD] [--json PATH] [--projects-root DIR]`. Both dates are inclusive and judged on the UTC date of each call's own timestamp (a `Z` or numeric-offset ISO-8601 string; one that cannot be parsed is undated and counted, not windowed); with neither flag the window is the current calendar month. A malformed date, `--since` after `--until`, a `--projects-root` that is not an existing directory, or a `--json` path that cannot be written exits 2 with one stderr line; a bad window or root writes nothing.

It prints the window, the window total, the main-versus-subagent split in dollars and percent, subagent dollars by agent type and by model, the ten most expensive sessions, a skills table (the fifteen skills with the most dollars, ties by name, then one `N more skills` line (`1 more skill` for one) summing the rest, then an always-present `(unattributed)` row (parenthesised so a skill literally named `unattributed` cannot print the same label) with its percent of the window total, then a line saying skill rows are a lower bound because the invoking call and later-turn work are not counted), one coverage line (files found, read and skipped, malformed lines, undated calls), and, only when there are any, the models it could not price. Undated calls are excluded from every figure and counted on the coverage line. `--json PATH` also writes one row per session with one row per agent inside it (the main session and each subagent, typed from its `meta.json`, else its attribution, else `unknown`); it also writes one row per skill with `sessions`, and an `unattributed` object, which together sum to the totals (a call's skill is its own record's `attributionSkill`, taken exactly as written); two runs over the same files and window write byte-identical files. Prices come from the same table `budget_burn.py` uses, so totals agree. Every field of the JSON is documented in [cost-ledger-schema.md](cost-ledger-schema.md) (schema version 2).

## Notes

- The number is **machine-local** — it reflects this machine's Claude Code usage only. The work/enterprise $350 gate only means something on the work machine; on personal it's a value meter.
- Rates and the dedup-by-`requestId` fix live in the script. If the number looks implausible, suspect a rate change or a transcript-format change — verify against Claude Code's own `/cost` for a single session before trusting a big swing.
- Related: [[2026-06-16-conductor-workers-operating-model]], [[Key Decisions]] (Conductor + Workers).
