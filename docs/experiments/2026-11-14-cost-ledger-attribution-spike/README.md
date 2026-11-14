# Cost ledger attribution spike

Run 2026-11-14 on one machine, reproduced on a second run.

## Purpose

Slice 1 of the cost ledger, `#1328`, under the parent PRD `#1327`. The ledger will attribute Claude Code spend per session, per agent and per skill, from transcripts. This spike records how the transcript attribution fields behave. The rules below are what later slices build on. It also ships synthetic fixtures and structural tests that pin those rules. It does not build the ledger.

## Method

- **Population:** about 15,440 main transcript files and 3,728 subagent transcript files.
- **Exclusions:** files modified in the last 30 minutes, and the investigating session itself.
- **Main sample:** 76 sessions containing 162 Skill tool calls, all on Claude Code 2.1.293 or later (versions 2.1.293, 2.1.299, 2.1.308, 2.1.309, 2.1.321).
- **Subagent sample:** 169 of 1,011 eligible subagent files, every Nth file by modification time.
- **Version family:** attribution fields exist from 2.1.209; the samples are 2.1.293 and later.
- **Detection:** by parsed JSON key, never by substring.
- **Rerun:** `python3 -I attribution_probe.py <projects_dir> --max-main 80 --max-sub 150 --exclude-session SESSION_ID` reproduces this run's sampling (`--min-version` defaults to 2.1.293; `--fixtures` also prints redacted skeletons), where `<projects_dir>` is Claude Code's projects directory. `--exclude-session` may be repeated; pass the id of the session that runs the probe. The probe is read-only and prints counts only, with no prompt text, paths, project names or session ids.

## Rules

Each rule is one sentence, followed by the counts behind it.

### 1. Skill rule

**A call's skill is the value of its own top-level `attributionSkill`, taken as-is; a call without the key is unattributed, and the ledger does not infer skill windows from Skill tool calls.**

- `attributionSkill` appears only on `type == "assistant"` records, as a top-level key (not under `message`), always a string.
- All records of one API call agreed: 10,324 of 10,324 calls.
- It is absent from the call that invokes the skill: 148 of 162 invoking calls were unattributed, and the other 14 carried the previous skill's value.
- It starts on the first API call after the Skill tool_result and covers every following call in the turn. 162 of 162 Skill calls were immediately followed by a call attributed to that skill, and the value equalled the Skill call's `skill` input exactly in 162 of 162.
- Run length in API calls: min 1, median 9, max 45, mean 10.3.
- What ended the 162 runs: next real user prompt 120; end of file 19; turn boundary (a `stop_hook_summary` system record and/or a queued meta user record) 12; next Skill call 11. Zero runs spanned a real user prompt.
- Second skill: replaced, never stacked. 64 transitions replaced the first skill with the second; 11 of those happened within one turn, where the invoking call still carried the first skill and the next call carried the second. 22 transitions re-invoked the same skill.
- 41 of 181 attributed runs had no preceding Skill tool call. All 41 were slash-command invocations: a user record carrying a command-name tag, then a user record with `isMeta: true`, then a `command_permissions` attachment. The Skill tool path produces the same meta record and attachment.
- Compaction: only 7 `compact_boundary` records in this version family, too few to conclude anything.

### 2. Lower bound

**The call that invokes a skill is not counted toward it, and attribution ends at the next real user prompt, so work a skill's instructions cause in later turns is unattributed; skill rows are therefore a lower bound on what a skill costs.**

The counts are the same as rule 1: 148 of 162 invoking calls unattributed, 14 carrying the previous skill, 120 of 162 runs ended by the next real user prompt, zero spanning one.

### 3. Skill naming

**Bare and plugin-qualified forms of one skill are reported as observed and are not merged in this slice; merging is a later decision.**

- Plugin-qualified (for example `workbench:commit`) in 159 of 162, bare in 3.
- Bare names exist because some skills have no plugin, and the same skill can appear both bare and qualified.
- `attributionPlugin` (plugin name only) accompanies the skill except on bare skills.

### 4. Agent rule

**A subagent transcript is tied to its spawning call by `meta.json` `toolUseId` equal to the parent `Agent` tool_use `id`; its type is `meta.agentType`; its model is `message.model` on its own records.**

- Resolved 169 of 169 by `toolUseId` against the `id` of an `Agent` tool_use in the parent session.
- Second link: the parent tool_result record's `toolUseResult.agentId` equals the `agentId` on the subagent's records (169 of 169), and that record's `sourceToolAssistantUUID` equals the `uuid` of the assistant record holding the Agent tool_use (169 of 169).
- `meta.json` keys: `agentType` (str), `description` (str), `toolUseId` (str), `spawnDepth` (int, always 1), `requestShape` (str), `requestNonInteractive` (bool). Optional: `model` (str alias), `finished` (bool), `isBuiltIn` (bool), `pickedEffortModel` (str).
- Agent type: `meta.agentType` equals `attributionAgent` in 169 of 169, and equals the call's `subagent_type` input in 160 of 160 where that input was present (absent in 9).
- Model: `meta.model` is an alias (sonnet 160, haiku 4, opus 3). The real model id is `message.model` on the subagent's assistant records. The alias was a substring of the real id in 167 of 167 where a model was requested (none requested in 2). No subagent file mixed models.
- Subagent records: the first record has `parentUuid: null`; all carry `agentId` and `isSidechain: true`. A `.prefix.json` sits beside 166 of 169.

### 5. Subagent skill rule

**Calls in a subagent file follow rule 1 using their own records.**

19 of 169 subagent files carried `attributionSkill` with no Skill tool call in the file. Why is not established, which is a further reason not to infer skills from tool calls.

### 6. Dedup rule

**Deduplicate by `(message.id, requestId)` across all files, keeping the record with the largest `output_tokens`.**

- One API call spans several records (one per content block). Usage was identical across the records in 8,479 of 9,971 multi-record calls. In the other 1,492 the last record had the largest `output_tokens`.
- Resumed or forked sessions copy history into a new file: 201 of 10,123 distinct calls (2%) appeared in two or more sampled main files. Deduplication must work across files, not only within one.

### Other attribution fields

Assistant records only. Corpus-wide record counts:

| Field | Main files | Subagent files |
| --- | --- | --- |
| `attributionSkill` | 26,129 | 27,342 |
| `attributionPlugin` | 24,171 | 27,731 |
| `attributionMcpServer` and `attributionMcpTool` (always paired; tool name without the `mcp__` prefix) | 8,478 | 1,479 |
| `attributionAgent` (holds the agent type) | 0 | 190,954 |

## Consequences for the ledger design

- Read skill attribution from each call's own `attributionSkill`. Do not build skill windows from Skill tool calls: slash-command runs have no Skill call (41 of 181 runs), and some subagent files carry attribution with no Skill call (19 of 169).
- Label skill rows as a lower bound. The invoking call and any later-turn work the skill causes are not in them.
- Report bare and qualified skill names as they appear. Do not merge them yet.
- Take agent and model from the subagent's own `meta.json` and records, and link it to its spawning call through `toolUseId`. The `meta.model` alias is not the model id to price against; use `message.model`.
- Deduplicate across files and across a call's records before summing anything, keeping the largest `output_tokens`. Summing records overcounts, and so does summing resumed or forked files.
- Each subagent pays for its own copy of the fixed context. Attachments appear in subagent transcripts too (`skill_listing`, `prompt_snapshot`, `instructions` among them). Median characters: `prompt_snapshot` 56,234 (keys `systemPrompt`, `tools`); `skill_listing` 32,936 (`content`); `instructions` 22,999 (`files`); `invoked_skills` 10,692 (`skills`). The attachment subtype is `attachment.type` (35 subtypes seen); content sits in sibling keys.
- `api-request`, `api-request-blob` and `api-request-shape` records exist in main and subagent files. The shape record holds the system prompt blocks and full tool schemas with no size fields; serialized, the system prompt had a median of 37.7k characters and the tool schemas 133k. No field linking an `api-request` record to an assistant call was found: `api-request.id` matched no `requestId`, `message.id` or `uuid` in 3,154 of 3,154. Assistant records carry an untested `requestRef` field.
- Markers: compaction is a `system` record with subtype `compact_boundary` followed by a user record with `isCompactSummary: true`. A turn boundary is a `system` record with subtype `stop_hook_summary`.
- `cost-state` records exist (110 in 196 files scanned), carrying a cumulative `totalCostUSD` and per-model `modelUsage`. They are a possible in-transcript check on the ledger's dollar figures, not yet examined.

## Fixtures and tests

Three synthetic transcript sets live in `plugins/workbench/machinery/tests/fixtures/cost_ledger/`, laid out as Claude Code lays them out on disk (`<project-key>/<session-id>.jsonl`, and `<session-id>/subagents/agent-<agentId>.jsonl` with its `.meta.json`). Content is invented placeholder text and ids.

- `skill_then_unattributed`: a Skill call, attributed calls, then an unattributed call after a real prompt.
- `two_skills`: skill one, a prompt, skill two replacing it, and a same-turn replacement where the invoking call still carries the previous skill.
- `two_subagents`: a parent spawning two subagents of different types and models, with every linking field. One subagent carries `attributionSkill` with no Skill call.

`EXPECTED.json` beside them is the oracle: per fixture, the number of distinct API calls and, per `requestId`, its session, agent, skill and kept `output_tokens`. It was written from the rules before the fixtures were built. `test_cost_ledger_fixtures.py` asserts the structural facts the rules rely on and that deduplication reproduces `EXPECTED.json`. `cost-ledger-fixtures.teeth.json` holds the three mutants below in the repo's teeth-spec format.

## Teeth

Each mutation was applied by hand to a committed fixture, the named test went red, the fixture was restored with `git checkout`, and the suite returned to 25 passed. The same three mutants, run through `teeth_check.py` with the spec above, all report killed.

| Mutation | Result |
| --- | --- |
| Add `attributionSkill` to the record in `skill_then_unattributed` whose call invokes the Skill | `test_a_invoking_call_is_unattributed_next_call_is_attributed_prompt_resets` red (and `test_records_of_one_call_agree_on_attribution`, since the call's two records now disagree) |
| Change `toolUseId` in one subagent's `meta.json` to a value no parent `Agent` tool_use has | `test_c_subagents_link_to_exactly_one_parent_agent_tool_use` red |
| Give one record of a two-record call in `two_subagents` a different `requestId`, splitting one call into two | `test_dedup_matches_expected_json[two_subagents]` red (call count 7, expected 6) |

## Not verified

- Compaction's effect on attribution.
- Behavior before 2.1.293.
- Whether a resumed subagent appends to its file (2 of 169 files had a second real user prompt).
- What links `api-request` records to calls.
- Whether subagent filenames always equal `agent-<agentId>`, and whether their `sessionId` equals the parent's. The fixtures assume both.
- Why some subagent files carry skill attribution without a Skill call.
- The `cost-state` records.
