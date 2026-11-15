# Cost ledger JSON schema

Reference for the file `cost_ledger.py --json PATH` writes, and for the object `build_ledger` returns. See [command.md](command.md) for how to run it. Current `schema_version`: 3.

Every figure covers in-window calls with a usable timestamp; undated calls are counted in `coverage.undated_calls` and in nothing else. Dollars are rounded to six places when a row is built, so a sum of rows can differ from the rounded total by a rounding step per row. Units: count, tokens, USD, ISO timestamp string, text.

## Fields

Paths are dotted, `[]` marks list elements, and `<model>` stands for a model name used as a map key.

| Path | Unit | Meaning |
| --- | --- | --- |
| `coverage` | object | How much of the transcript tree was read. |
| `coverage.files_found` | count | Transcript files found under the projects root. |
| `coverage.files_read` | count | Transcript files read. |
| `coverage.files_skipped` | count | Transcript files found but not read. |
| `coverage.malformed_lines` | count | Lines that were not valid JSON records. |
| `coverage.undated_calls` | count | Calls with no usable timestamp; in no row and in no total. |
| `meter` | object or null | The meter check; `null` unless `--meter-usd` was given. Compares the window total with a dollar figure read by hand from Claude Code's usage view. |
| `meter.difference_usd` | USD | `ledger_usd` minus `meter_usd`, signed: positive when the ledger is above the meter. |
| `meter.gap_flag` | boolean | `true` when the absolute difference is strictly more than 10 percent of `meter_usd`; exactly 10 percent does not set it. |
| `meter.gap_percent` | percent | The absolute difference as a percent of `meter_usd`. |
| `meter.ledger_usd` | USD | The window total, `totals.usd`. |
| `meter.meter_usd` | USD | The figure given with `--meter-usd`; finite and greater than 0. |
| `recorded_cost` | object | The recorded-cost check, always present: ledger dollars against the cumulative `totalCostUSD` Claude Code records in `cost-state` records of main session files. |
| `recorded_cost.difference_usd` | USD | `ledger_usd` minus `recorded_usd`, signed. |
| `recorded_cost.flagged_ledger_usd` | USD | Ledger dollars of the flagged sessions. Reported only, never in the comparable sums. |
| `recorded_cost.flagged_recorded_usd` | USD | Recorded dollars of the flagged sessions. Reported only. |
| `recorded_cost.flagged_unknown_sessions` | count | In-window sessions whose supplying record has `hasUnknownModelCost` true and that meet the other comparability conditions. |
| `recorded_cost.gap_percent` | percent or null | The absolute difference as a percent of `recorded_usd`; `null` when `recorded_usd` is 0. |
| `recorded_cost.ledger_usd` | USD | Whole-session ledger dollars (main plus subagents) of the comparable sessions. |
| `recorded_cost.recorded_usd` | USD | Recorded dollars of the comparable sessions. |
| `recorded_cost.sessions_comparable` | count | In-window sessions that meet every condition in "Recorded cost and when it is comparable". |
| `recorded_cost.sessions_in_window` | count | Session rows, that is sessions with an in-window call. |
| `schema_version` | count | Schema version of this file: `3`. See the version history below. |
| `sessions` | list | One row per (project, session id) with an in-window call, sorted by project then session id. |
| `sessions[]` | object | One session row. |
| `sessions[].agents` | list | One row per agent in the session: `main` first, then subagents by agent id. |
| `sessions[].agents[]` | object | One agent row. |
| `sessions[].agents[].agent_id` | text | `main`, or the subagent's id. |
| `sessions[].agents[].agent_type` | text | `main`; for a subagent its `meta.json` type, else its attribution, else `unknown`. |
| `sessions[].agents[].by_model` | object | Calls and dollars per model; keys are model names. |
| `sessions[].agents[].by_model.<model>` | object | One model's share of the agent. |
| `sessions[].agents[].by_model.<model>.calls` | count | Calls of the agent on that model. |
| `sessions[].agents[].by_model.<model>.usd` | USD | Dollars of those calls; an unpriced model adds none. |
| `sessions[].agents[].calls` | count | In-window calls of the agent. |
| `sessions[].agents[].model` | text | The agent's single model, `mixed` when it used several, `unknown` when none was recorded. |
| `sessions[].agents[].tokens` | object | Tokens of the agent, by kind. |
| `sessions[].agents[].tokens.cache_read` | tokens | Cache-read tokens of the agent. |
| `sessions[].agents[].tokens.input` | tokens | Fresh input tokens of the agent. |
| `sessions[].agents[].tokens.output` | tokens | Output tokens of the agent. |
| `sessions[].agents[].tokens.write_1h` | tokens | 1-hour cache-write tokens of the agent. |
| `sessions[].agents[].tokens.write_5m` | tokens | 5-minute cache-write tokens of the agent. |
| `sessions[].agents[].unpriced_calls` | count | Calls of the agent on a model with no price; counted in `calls` and `tokens`, adding no dollars. |
| `sessions[].agents[].usd` | USD | Dollars of the agent, rounded to six places. |
| `sessions[].agents[].usd_breakdown` | object | Dollars of the agent, by kind; sums to `sessions[].agents[].usd` up to rounding. |
| `sessions[].agents[].usd_breakdown.cache_read` | USD | Cache-read dollars of the agent. |
| `sessions[].agents[].usd_breakdown.input` | USD | Fresh input dollars of the agent. |
| `sessions[].agents[].usd_breakdown.output` | USD | Output dollars of the agent. |
| `sessions[].agents[].usd_breakdown.write_1h` | USD | 1-hour cache-write dollars of the agent. |
| `sessions[].agents[].usd_breakdown.write_5m` | USD | 5-minute cache-write dollars of the agent. |
| `sessions[].calls` | count | In-window calls of the session. |
| `sessions[].first_timestamp` | ISO timestamp string | Earliest in-window call, by instant, as written in the transcript. |
| `sessions[].last_timestamp` | ISO timestamp string | Latest in-window call, by instant, as written in the transcript. |
| `sessions[].project` | text | Project directory name, as observed. |
| `sessions[].session_id` | text | Session id, as observed. |
| `sessions[].tokens` | object | Tokens of the session, by kind. |
| `sessions[].tokens.cache_read` | tokens | Cache-read tokens of the session. |
| `sessions[].tokens.input` | tokens | Fresh input tokens of the session. |
| `sessions[].tokens.output` | tokens | Output tokens of the session. |
| `sessions[].tokens.write_1h` | tokens | 1-hour cache-write tokens of the session. |
| `sessions[].tokens.write_5m` | tokens | 5-minute cache-write tokens of the session. |
| `sessions[].unpriced_calls` | count | Calls of the session on a model with no price; counted in `calls` and `tokens`, adding no dollars. |
| `sessions[].usd` | USD | Dollars of the session, rounded to six places. |
| `sessions[].usd_breakdown` | object | Dollars of the session, by kind; sums to `sessions[].usd` up to rounding. |
| `sessions[].usd_breakdown.cache_read` | USD | Cache-read dollars of the session. |
| `sessions[].usd_breakdown.input` | USD | Fresh input dollars of the session. |
| `sessions[].usd_breakdown.output` | USD | Output dollars of the session. |
| `sessions[].usd_breakdown.write_1h` | USD | 1-hour cache-write dollars of the session. |
| `sessions[].usd_breakdown.write_5m` | USD | 5-minute cache-write dollars of the session. |
| `skills` | list | One row per distinct skill with at least one in-window call, sorted by skill. |
| `skills[]` | object | One skill row. |
| `skills[].calls` | count | In-window calls of the skill. |
| `skills[].sessions` | count | Distinct (project, session id) pairs with a call in the row. |
| `skills[].skill` | text | Skill name exactly as observed in the call's `attributionSkill`: no case change, no trimming, bare and plugin-qualified names stay separate. |
| `skills[].tokens` | object | Tokens of the skill, by kind. |
| `skills[].tokens.cache_read` | tokens | Cache-read tokens of the skill. |
| `skills[].tokens.input` | tokens | Fresh input tokens of the skill. |
| `skills[].tokens.output` | tokens | Output tokens of the skill. |
| `skills[].tokens.write_1h` | tokens | 1-hour cache-write tokens of the skill. |
| `skills[].tokens.write_5m` | tokens | 5-minute cache-write tokens of the skill. |
| `skills[].unpriced_calls` | count | Calls of the skill on a model with no price; counted in `calls` and `tokens`, adding no dollars. |
| `skills[].usd` | USD | Dollars of the skill, rounded to six places. |
| `skills[].usd_breakdown` | object | Dollars of the skill, by kind; sums to `skills[].usd` up to rounding. |
| `skills[].usd_breakdown.cache_read` | USD | Cache-read dollars of the skill. |
| `skills[].usd_breakdown.input` | USD | Fresh input dollars of the skill. |
| `skills[].usd_breakdown.output` | USD | Output dollars of the skill. |
| `skills[].usd_breakdown.write_1h` | USD | 1-hour cache-write dollars of the skill. |
| `skills[].usd_breakdown.write_5m` | USD | 5-minute cache-write dollars of the skill. |
| `totals` | object | Measures of every in-window dated call. |
| `totals.calls` | count | In-window calls of the whole window. |
| `totals.main_usd` | USD | Dollars of calls made by the main session (not a subagent). |
| `totals.subagent_usd` | USD | Dollars of subagent calls. `totals.main_usd` + `totals.subagent_usd` = `totals.usd`. |
| `totals.tokens` | object | Tokens of the whole window, by kind. |
| `totals.tokens.cache_read` | tokens | Cache-read tokens of the whole window. |
| `totals.tokens.input` | tokens | Fresh input tokens of the whole window. |
| `totals.tokens.output` | tokens | Output tokens of the whole window. |
| `totals.tokens.write_1h` | tokens | 1-hour cache-write tokens of the whole window. |
| `totals.tokens.write_5m` | tokens | 5-minute cache-write tokens of the whole window. |
| `totals.unpriced_calls` | count | Calls of the whole window on a model with no price; counted in `calls` and `tokens`, adding no dollars. |
| `totals.usd` | USD | Dollars of the whole window, rounded to six places. |
| `totals.usd_breakdown` | object | Dollars of the whole window, by kind; sums to `totals.usd` up to rounding. |
| `totals.usd_breakdown.cache_read` | USD | Cache-read dollars of the whole window. |
| `totals.usd_breakdown.input` | USD | Fresh input dollars of the whole window. |
| `totals.usd_breakdown.output` | USD | Output dollars of the whole window. |
| `totals.usd_breakdown.write_1h` | USD | 1-hour cache-write dollars of the whole window. |
| `totals.usd_breakdown.write_5m` | USD | 5-minute cache-write dollars of the whole window. |
| `unattributed` | object | Calls whose own record carries no non-empty text `attributionSkill`; always present, zeros when there are none. |
| `unattributed.calls` | count | In-window calls that carry no skill. |
| `unattributed.sessions` | count | Distinct (project, session id) pairs with an unattributed call. |
| `unattributed.tokens` | object | Tokens of the unattributed calls, by kind. |
| `unattributed.tokens.cache_read` | tokens | Cache-read tokens of the unattributed calls. |
| `unattributed.tokens.input` | tokens | Fresh input tokens of the unattributed calls. |
| `unattributed.tokens.output` | tokens | Output tokens of the unattributed calls. |
| `unattributed.tokens.write_1h` | tokens | 1-hour cache-write tokens of the unattributed calls. |
| `unattributed.tokens.write_5m` | tokens | 5-minute cache-write tokens of the unattributed calls. |
| `unattributed.unpriced_calls` | count | Calls of the unattributed calls on a model with no price; counted in `calls` and `tokens`, adding no dollars. |
| `unattributed.usd` | USD | Dollars of the unattributed calls, rounded to six places. |
| `unattributed.usd_breakdown` | object | Dollars of the unattributed calls, by kind; sums to `unattributed.usd` up to rounding. |
| `unattributed.usd_breakdown.cache_read` | USD | Cache-read dollars of the unattributed calls. |
| `unattributed.usd_breakdown.input` | USD | Fresh input dollars of the unattributed calls. |
| `unattributed.usd_breakdown.output` | USD | Output dollars of the unattributed calls. |
| `unattributed.usd_breakdown.write_1h` | USD | 1-hour cache-write dollars of the unattributed calls. |
| `unattributed.usd_breakdown.write_5m` | USD | 5-minute cache-write dollars of the unattributed calls. |
| `unpriced` | list | One entry per model and reason that could not be priced; empty when every call was priced. |
| `unpriced[]` | object | One unpriced model and reason. |
| `unpriced[].calls` | count | In-window calls with that model and reason. |
| `unpriced[].model` | text | Model name as recorded; `null` when none was recorded. |
| `unpriced[].reason` | text | Why the call has no price. |
| `unpriced[].tokens` | object | Tokens of those calls, by kind. |
| `unpriced[].tokens.cache_read` | tokens | Cache-read tokens of the unpriced calls. |
| `unpriced[].tokens.input` | tokens | Fresh input tokens of the unpriced calls. |
| `unpriced[].tokens.output` | tokens | Output tokens of the unpriced calls. |
| `unpriced[].tokens.write_1h` | tokens | 1-hour cache-write tokens of the unpriced calls. |
| `unpriced[].tokens.write_5m` | tokens | 5-minute cache-write tokens of the unpriced calls. |
| `window` | object | The window the figures cover, holding `since` and `until`. |
| `window.since` | text | First day of the window, `YYYY-MM-DD`, inclusive, judged on each call's UTC date; `null` when open. |
| `window.until` | text | Last day of the window, `YYYY-MM-DD`, inclusive; `null` when open. |

## What sums to what

- Agents to session: the rows in `sessions[].agents` sum to their session row in `calls`, `unpriced_calls`, `usd`, each `tokens` kind and each `usd_breakdown` kind.
- Sessions to totals: the session rows sum to `totals` in the same measures.
- Skills plus unattributed to totals: every in-window dated call is in exactly one skill row or in `unattributed`, so the skill rows plus `unattributed` sum to `totals` in `calls`, `unpriced_calls`, each `tokens` kind and each `usd_breakdown` kind, and to `totals.usd`.
- Main plus subagent: `totals.main_usd` + `totals.subagent_usd` = `totals.usd`.
- An unpriced call counts in `calls`, `unpriced_calls` and `tokens` and adds no dollars.

## Attribution and its limits

A call's skill is the `attributionSkill` on its own record, when that is a non-empty string, and nothing else: it is not inferred from Skill tool calls, neighbouring calls or the plugin name. Subagent calls follow the same rule from their own records. Names are as observed: `commit` and `workbench:commit` are two skills, and names are not trimmed or case-folded, so a name that is only whitespace stays its own row.

Skill rows are a lower bound. The invoking call and later-turn work are not counted: a call whose own record has no `attributionSkill` lands in `unattributed` whatever happened around it. Read `unattributed` as "not attributed on its own record", not as "no skill involved".

## Meter and recorded cost

`meter` is a check against a figure you read by hand; it is `null` unless `--meter-usd N` was given. `recorded_cost` is automatic.

Claude Code writes `cost-state` records into main session files with a cumulative `totalCostUSD` and a `hasUnknownModelCost` flag. They carry no timestamp and cover the whole session, subagents included. For each session the recorded figure is the largest `totalCostUSD` among the records of its main file (a value that is not a finite non-negative number, or is a boolean, is ignored; records in subagent files are ignored).

## Recorded cost and when it is comparable

A session is comparable when all of these hold: it has a recorded figure; `hasUnknownModelCost` is false on the record that supplied the figure; it has no unpriced call; and every dated call of the session, main and subagents, inside or outside the window, falls inside the window. The comparison is the whole-session ledger dollars against the recorded figure. A session that meets every condition except the `hasUnknownModelCost` one is flagged: counted in `flagged_unknown_sessions` with its dollars in `flagged_ledger_usd` and `flagged_recorded_usd`, and never added to the comparable sums.

## Version history

- 1: sessions and agents.
- 2: skills and unattributed added; `schema_version` is 2.
- 3: `meter` and `recorded_cost` added; `schema_version` is 3.
