# Cost ledger JSON schema

Reference for the file `cost_ledger.py --json PATH` writes, and for the object `build_ledger` returns. See [command.md](command.md) for how to run it. Current `schema_version`: 5.

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
| `fixed_weight` | object or null | The fixed-weight estimate; `null` unless `--fixed-weight` was given, and then no estimation work is done. An uncalibrated estimate of what the fixed context (system prompt, tool schemas, injected setup text) cost the window. Not a measurement: see "Fixed weight and how it is costed". |
| `fixed_weight.calibrated` | boolean | `true` when a calibration file supplied the factor; `false` when none was found (the report then says `UNCALIBRATED ESTIMATE`). |
| `fixed_weight.calibration` | object or null | Where the factor came from; `null` when no calibration file was used. Provenance only: it changes no figure. |
| `fixed_weight.calibration.claude_code_version` | text or null | The Claude Code version the calibration was measured on, as the file states it; `null` when the file has none or it is not a plain version string. |
| `fixed_weight.calibration.date` | text or null | The day (YYYY-MM-DD) the calibration was made, from the file; `null` when absent or malformed. |
| `fixed_weight.calibration.runs_per_arm` | count or null | How many matched session pairs the factor was measured from, from the file; `null` when absent or not a positive whole number. |
| `fixed_weight.calibration_factor` | number | The factor applied to every token estimate: from the calibration file, else `1.0`. |
| `fixed_weight.capped_calls` | count | Calls on which the fixed charge was scaled down because it exceeded the call's own dollars. |
| `fixed_weight.chars_per_token` | number | Characters per token used to turn sizes into tokens: `3.7`. |
| `fixed_weight.comparison` | object or null | The estimate re-run at other factors, so the effect of calibration is visible; `null` when no calibration file was used. Each run is the whole costing rule again at that factor, not a rescaling, because the write threshold and the cap depend on the factor. The fields outside `comparison` are the estimate at the file's `factor`. |
| `fixed_weight.comparison.high` | object or null | The estimate at the file's `high`; `null` when the file has no bounds. |
| `fixed_weight.comparison.high.calibration_factor` | number | The factor this run used: `1.0` for `uncalibrated`, the file's `low` or `high` for those two. |
| `fixed_weight.comparison.high.mcp_share_of_total` | fraction or null | The MCP subtotal as a fraction of `totals.usd`; same rule as `fixed_weight.mcp.share_of_total`. |
| `fixed_weight.comparison.high.mcp_usd` | USD | Dollars charged to the three MCP components in this run. |
| `fixed_weight.comparison.high.setup_share_of_total` | fraction or null | The `setup` group as a fraction of `totals.usd`; same rule as `fixed_weight.groups.setup.share_of_total`. |
| `fixed_weight.comparison.high.setup_usd` | USD | Dollars charged to the `setup` group in this run. |
| `fixed_weight.comparison.high.share_of_total` | fraction or null | `total_usd` as a fraction of `totals.usd`; same rule as `fixed_weight.share_of_total`. |
| `fixed_weight.comparison.high.total_usd` | USD | Fixed-weight dollars in this run. |
| `fixed_weight.comparison.low` | object or null | The estimate at the file's `low`; `null` when the file has no bounds. |
| `fixed_weight.comparison.low.calibration_factor` | number | The factor this run used: `1.0` for `uncalibrated`, the file's `low` or `high` for those two. |
| `fixed_weight.comparison.low.mcp_share_of_total` | fraction or null | The MCP subtotal as a fraction of `totals.usd`; same rule as `fixed_weight.mcp.share_of_total`. |
| `fixed_weight.comparison.low.mcp_usd` | USD | Dollars charged to the three MCP components in this run. |
| `fixed_weight.comparison.low.setup_share_of_total` | fraction or null | The `setup` group as a fraction of `totals.usd`; same rule as `fixed_weight.groups.setup.share_of_total`. |
| `fixed_weight.comparison.low.setup_usd` | USD | Dollars charged to the `setup` group in this run. |
| `fixed_weight.comparison.low.share_of_total` | fraction or null | `total_usd` as a fraction of `totals.usd`; same rule as `fixed_weight.share_of_total`. |
| `fixed_weight.comparison.low.total_usd` | USD | Fixed-weight dollars in this run. |
| `fixed_weight.comparison.uncalibrated` | object or null | The estimate at factor `1.0`. |
| `fixed_weight.comparison.uncalibrated.calibration_factor` | number | The factor this run used: `1.0` for `uncalibrated`, the file's `low` or `high` for those two. |
| `fixed_weight.comparison.uncalibrated.mcp_share_of_total` | fraction or null | The MCP subtotal as a fraction of `totals.usd`; same rule as `fixed_weight.mcp.share_of_total`. |
| `fixed_weight.comparison.uncalibrated.mcp_usd` | USD | Dollars charged to the three MCP components in this run. |
| `fixed_weight.comparison.uncalibrated.setup_share_of_total` | fraction or null | The `setup` group as a fraction of `totals.usd`; same rule as `fixed_weight.groups.setup.share_of_total`. |
| `fixed_weight.comparison.uncalibrated.setup_usd` | USD | Dollars charged to the `setup` group in this run. |
| `fixed_weight.comparison.uncalibrated.share_of_total` | fraction or null | `total_usd` as a fraction of `totals.usd`; same rule as `fixed_weight.share_of_total`. |
| `fixed_weight.comparison.uncalibrated.total_usd` | USD | Fixed-weight dollars in this run. |
| `fixed_weight.components` | list | One entry per fixed component, always all eleven, in the fixed order: `skill_listing`, `instructions`, `hook_context`, `agent_listing`, `mcp_instructions`, `mcp_tool_schemas`, `mcp_tool_listing` (group `setup`), then `system_prompt`, `builtin_tool_schemas`, `builtin_tool_listing`, `other` (group `claude_code`). |
| `fixed_weight.components[]` | object | One component. |
| `fixed_weight.components[].component` | text | Component name. |
| `fixed_weight.components[].files` | count | Transcript files where the component's size is more than 0 and at least one call was charged. |
| `fixed_weight.components[].group` | text | `setup` or `claude_code`. |
| `fixed_weight.components[].read_usd` | USD | Dollars charged to the component on calls that read the fixed context from the cache. |
| `fixed_weight.components[].tokens_per_file` | object | Estimated tokens of the component per transcript file, over the files counted in `files`; the three values are rounded to three decimal places, and are `null` when there are none. |
| `fixed_weight.components[].tokens_per_file.max` | tokens | Largest per-file estimate. |
| `fixed_weight.components[].tokens_per_file.median` | tokens | Median per-file estimate. |
| `fixed_weight.components[].tokens_per_file.min` | tokens | Smallest per-file estimate. |
| `fixed_weight.components[].usd` | USD | Dollars charged to the component over the window; `write_usd` plus `read_usd`, rounded to six places. |
| `fixed_weight.components[].write_usd` | USD | Dollars charged to the component on calls that wrote the fixed context to the cache. |
| `fixed_weight.files_estimated` | count | Transcript files with at least one charged call. A subagent file counts on its own. |
| `fixed_weight.files_without_snapshot` | count | Transcript files with an in-window dated call and no `prompt_snapshot` record: their system prompt and tool schemas are counted as 0. |
| `fixed_weight.groups` | object | Dollars by group, holding `setup` and `claude_code`; the two `usd` values sum to `fixed_weight.total_usd`. |
| `fixed_weight.groups.claude_code` | object | The group present regardless of the user's setup: system prompt, built-in tool schemas and listing, other attachments. |
| `fixed_weight.groups.claude_code.share_of_total` | fraction or null | The group's dollars as a fraction of `totals.usd`, taken from the unrounded dollars and then rounded to six places, so never more than 1; `null` when `totals.usd` is 0. |
| `fixed_weight.groups.claude_code.usd` | USD | Dollars charged to the group. |
| `fixed_weight.groups.setup` | object | What the user's setup adds: skill and agent listings, instructions, hook context, MCP instructions, MCP tool schemas and listing. Its dollars are an upper bound on what removing all of it would save. |
| `fixed_weight.groups.setup.share_of_total` | fraction or null | The group's dollars as a fraction of `totals.usd`, taken from the unrounded dollars and then rounded to six places, so never more than 1; `null` when `totals.usd` is 0. |
| `fixed_weight.groups.setup.usd` | USD | Dollars charged to the group. |
| `fixed_weight.mcp` | object | The MCP subtotal: `mcp_instructions`, `mcp_tool_schemas` and `mcp_tool_listing`, all inside the `setup` group. |
| `fixed_weight.mcp.share_of_total` | fraction or null | The subtotal as a fraction of `totals.usd`, taken from the unrounded dollars and then rounded to six places, so never more than 1; `null` when `totals.usd` is 0. |
| `fixed_weight.mcp.usd` | USD | Dollars charged to the three MCP components. |
| `fixed_weight.read_calls` | count | Charged calls on which the fixed context was costed as a cache read. |
| `fixed_weight.share_of_total` | fraction or null | `total_usd` as a fraction of `totals.usd`, taken from the unrounded dollars and then rounded to six places, so never more than 1; `null` when `totals.usd` is 0. |
| `fixed_weight.subagent_share` | fraction or null | `subagent_usd` as a fraction of `total_usd`, taken from the unrounded dollars and then rounded to six places; `0.0` when fixed-weight dollars exist but none were charged in subagent files, and `null` only when `total_usd` is 0. |
| `fixed_weight.subagent_usd` | USD | Fixed-weight dollars charged in subagent files. |
| `fixed_weight.total_usd` | USD | Fixed-weight dollars over the window: the sum of the component dollars, rounded to six places. Never more than `totals.usd`. |
| `fixed_weight.unpriced_calls` | count | Calls that would have been charged but have no price; charged nothing. |
| `fixed_weight.write_calls` | count | Charged calls on which the fixed context was costed as a cache write. |
| `meter` | object or null | The meter check; `null` unless `--meter-usd` was given. Compares the window total with a dollar figure read by hand from Claude Code's usage view. |
| `meter.difference_usd` | USD | `ledger_usd` minus `meter_usd`, signed: positive when the ledger is above the meter. |
| `meter.gap_flag` | boolean | `true` when the gap percent, rounded to six decimal places, is strictly more than 10; exactly 10 percent does not set it, so 0.33 against a 0.3 meter does not flag. |
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
| `schema_version` | count | Schema version of this file: `4`. See the version history below. |
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
- Fixed weight: the `fixed_weight.components[].usd` values sum to `fixed_weight.total_usd`, the two `fixed_weight.groups` values sum to it too, and it is never more than `totals.usd`, because the estimate is capped on every call.
- An unpriced call counts in `calls`, `unpriced_calls` and `tokens` and adds no dollars.

## Attribution and its limits

A call's skill is the `attributionSkill` on its own record, when that is a non-empty string, and nothing else: it is not inferred from Skill tool calls, neighbouring calls or the plugin name. Subagent calls follow the same rule from their own records. Names are as observed: `commit` and `workbench:commit` are two skills, and names are not trimmed or case-folded, so a name that is only whitespace stays its own row.

Skill rows are a lower bound. The invoking call and later-turn work are not counted: a call whose own record has no `attributionSkill` lands in `unattributed` whatever happened around it. Read `unattributed` as "not attributed on its own record", not as "no skill involved".

## Meter and recorded cost

`meter` is a check against a figure you read by hand; it is `null` unless `--meter-usd N` was given. `recorded_cost` is automatic.

Claude Code writes `cost-state` records into main session files with a cumulative `totalCostUSD` and a `hasUnknownModelCost` flag. They carry no timestamp and cover the whole session, subagents included. For each session the recorded figure is the largest `totalCostUSD` among the records of its main file (a value that is not a finite non-negative number, or is a boolean, is ignored; records in subagent files are ignored). When several records tie on the largest figure, the session counts as unknown unless every tied record has `hasUnknownModelCost` literally `false`.

## Recorded cost and when it is comparable

A session is comparable when all of these hold: it has a recorded figure; `hasUnknownModelCost` is literally false on the record that supplied the figure, and on every record tied with it for the largest figure; it has no unpriced call; and every dated call of the session, main and subagents, inside or outside the window, falls inside the window. The comparison is the whole-session ledger dollars against the recorded figure. A session that meets every condition except the `hasUnknownModelCost` one is flagged: counted in `flagged_unknown_sessions` with its dollars in `flagged_ledger_usd` and `flagged_recorded_usd`, and never added to the comparable sums.

## Fixed weight and how it is costed

`fixed_weight` estimates what the fixed context cost: the text every call of a session sends again. It is an estimate from character counts, not a measurement, and it is `null` unless `--fixed-weight` was given.

**What is sized.** Each transcript file, the main session or one subagent, is estimated on its own, because a subagent pays for its own copy. A file's fixed context is its injected attachments up to its first assistant record with usable usage, the system prompt, and the tool schemas. Attachments after that first call are ignored, and so is an attachment with no `rendered` text, because it was not sent. The system prompt is the `systemPrompt` of the file's first `prompt_snapshot` that has one. Tool schemas come from the first `prompt_snapshot` in the file that lists tools; each tool's size is the compact JSON length of its `schema`, and a tool with no schema object or no name is ignored. A `deferred_tools_delta` is split between `mcp_tool_listing` and `builtin_tool_listing` by the share of its `addedNames` that start with `mcp__`. A file with no `prompt_snapshot` still has its attachments estimated, with system prompt and tool schemas counted as 0, and is counted in `fixed_weight.files_without_snapshot`.

**Tokens.** Component tokens are characters divided by `chars_per_token` (3.7) times `calibration_factor`, kept as a fraction. The factor comes from `--calibration PATH` (a path that does not exist stops the run with exit code 2), else from `~/.workshop/cost-ledger/cost_ledger_calibration.json` (no other directory is consulted). The file is a JSON object whose `factor` is a finite number greater than 0; other keys are ignored. With no `--calibration` flag and no file at the default path the factor is 1.0 and `calibrated` is `false`. A file that exists but is unreadable, is not an object, or has a missing or invalid `factor` stops the run with exit code 2.

**The costing rule, per call.** Let T be the file's total fixed tokens. For each in-window, dated, priced call of the file, when T is more than 0:

- if the call's total cache-write tokens are at least T, the fixed context is taken to have been written on that call, and every component is charged its tokens times the write rate, the call's 1-hour write rate when its 1-hour write tokens alone are at least T, else its 5-minute write rate;
- otherwise it is taken to have been read, and every component is charged its tokens times the cache-read rate.

The rates are the ones that call paid, so its own model, long-prompt row and fast multiplier apply. The first call gets no special treatment. A call with no price is charged nothing and counted in `unpriced_calls`; a call with no tokens is neither charged nor counted.

**The cap.** If the fixed charge on a call is more than that call's own dollars, every component's charge on that call is scaled by the same ratio so they sum to the call's dollars, and the call is counted in `capped_calls`. So `fixed_weight.total_usd` can never exceed `totals.usd`: every share is taken from the unrounded dollars and rounded afterwards, so none can be above 1, and a sum that float noise leaves a hair above the window's own sum is pulled back to it.

**Groups.** `setup` is what the user's setup adds and its dollars are the upper bound on what removing all of it would save. `claude_code` is present regardless. `mcp` is a subtotal of three `setup` components.

## Calibration and its range

A calibration file holds `factor`, and may hold `low` and `high`, the smallest and largest per-pair ratio the calibration measured. Both or neither: a file with only one, a bound that is not a finite number greater than 0, or a factor outside `low` to `high` is refused (exit 2). A file with only `factor` is valid and shows no range. `date`, `claude_code_version` and `runs_per_arm` are read when well formed and shown in the report and in `fixed_weight.calibration`. How a file is made, and what the factor covers, is in [cost-ledger-calibration.md](cost-ledger-calibration.md).

## Version history

- 1: sessions and agents.
- 2: skills and unattributed added; `schema_version` is 2.
- 3: `meter` and `recorded_cost` added; `schema_version` is 3.
- 4: `fixed_weight` added (the fixed-weight estimate, `null` without `--fixed-weight`); `schema_version` is 4.
- 5: `fixed_weight.calibration` and `fixed_weight.comparison` added (the calibration file's provenance, and the estimate re-run at factor 1.0 and at the file's `low` and `high`; both `null` when uncalibrated); `schema_version` is 5.
