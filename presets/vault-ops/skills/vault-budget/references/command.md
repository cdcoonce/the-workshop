# /budget — Claude API spend / subscription-value meter

Run the budget engine and present it. The script does all the heavy lifting (scans every local Claude Code transcript, dedups by API call, computes cost by model × published rates); this command just runs it and interprets.

**Arguments:** $ARGUMENTS — optional `--month YYYY-MM`, `--budget N`, `--context work|personal`.

## Procedure

1. Run: `python3 .claude/scripts/budget_burn.py $ARGUMENTS` (add `--json` if you need the structured numbers).
2. Present the output as-is, then add one line of interpretation:
   - **Personal (subscription, value-meter):** this is API-equivalent value the flat subscription delivered — no per-token cap. Frame it as "what your subscription is worth," not a budget to fear.
   - **Work (enterprise, gate):** spend against the ~$350 enterprise cap. If projected month-end is over cap, flag it and point at the lever (below).
3. **Always surface the Opus %** — it's the conductor-health metric (see the Operating Model in root `CLAUDE.md`). High Opus % = lots of judgment-and-retrieval still bundled on the expensive model; the lever is delegating bulk reads to Sonnet/Haiku workers. Low Opus % = the conductor discipline is working.

## Notes

- The number is **machine-local** — it reflects this machine's Claude Code usage only. The work/enterprise $350 gate only means something on the work machine; on personal it's a value meter.
- Rates and the dedup-by-`requestId` fix live in the script. If the number looks implausible, suspect a rate change or a transcript-format change — verify against Claude Code's own `/cost` for a single session before trusting a big swing.
- Related: [[2026-06-16-conductor-workers-operating-model]], [[Key Decisions]] (Conductor + Workers).
