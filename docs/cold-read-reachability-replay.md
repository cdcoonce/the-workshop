# Cold-read reachability replay

Ledger for the "Survivors and reachability" section of
`plugins/workbench/skills/vault-cold-read/references/command.md`. Re-run it
whenever that section changes.

## Subject

afk#1557 (cdcoonce/afk-agent-system), ten fresh read cycles on 2026-10-02.
Producers were read on `origin/main` at `2bc2280`. A subagent produced the
classification; the lead spot-checked two producer claims (`json.dumps(record)`
at `jsonl_io.py:56`; `run_id` built from `datetime.now(timezone.utc).isoformat()`
at `cli.py:1037`, `1499`, `1600`). The rest is the subagent's reading and has
not been independently re-derived.

## Producer facts the classification rests on

- Every telemetry record is a dict written by `json.dumps(record)`; a torn
  write yields invalid JSON, never a scalar line.
- `run_id` is always an ISO timestamp string.
- `status` is always a string from the `ExecutionResult.status` set.
- `cost` and `tokens` are not validated. A string or boolean cost is a
  documented case (afk#1049).
- Only `generation_attestation`, `orchestrator_cost` and `conductor_resume`
  carry a cost field.

## Result

About 25 rows, 21 of them input-edge findings: 9 REACHABLE, 9 UNREACHABLE,
3 undetermined (leaning unreachable), 4 not an input question.

UNREACHABLE (would be non-blocking under the rule):

- `"status": null`; a status-bearing `orchestrator_cost` or `conductor_resume`
- non-string, empty or absent `run_id`; the `unknown` drain
- non-object JSON lines; a directory in place of the telemetry file
- `endswith`/substring attestation and non-string `record_type`
- cost on the six record types that have no cost field

REACHABLE (the positive controls, which the rule must still block):

1. the float `==` cost-parity failure (336 of 1000 fixtures)
2. drain ordering, in-drain slice order, and the `conductor_resume` cost omission
3. event-only `run_id`s producing no drain
4. a `generation_attestation` cost wrongly counted
5. the verbatim copy of `category`, `pr_url`, `model_tier` and `tokens`
6. a string or boolean cost in the cost sum (afk#1049)
7. the non-empty trend capture (read 8)

## Close calls

- NaN/Infinity in cost or tokens: Python's `json.dumps` writes `NaN`; the Node
  CLI's `JSON.stringify` writes `null`. Undetermined; the cap decision treated
  it as outside the contract.
- Torn lines: the PRD names corruption (story 20), but a scalar line cannot be
  torn output, so the read-6 widening went past it.
- Read 9's nine event types with a nonzero cost: real producers never write a
  cost on six of them, but the mutant still guards a future writer.

## What the replay supports, and what it does not

It supports the rule's direction: the survivors that blocked reads 4 to 6 were
mostly UNREACHABLE, and every defect that was real stays REACHABLE. It does
not measure the rule's false-negative rate on other repos, and the producer
search is the reader's own, so a careless reader can still pick the wrong
writer. The "fail closed" clause is the guard.

## afk-app 30-read run (2026-10-03)

Source: the read-by-read comments on cdcoonce/afk-app#1-#4 (30 fresh reads under
workbench 8.31.0), classified for the evidence rule of
[the-workshop#1105](https://github.com/cdcoonce/the-workshop/issues/1105). The
rule must keep the positive controls blocking and turn the negative controls
advisory. Classes below are the issue's own; the producer lines are as cited by
the readers and have not been re-derived here.

Positive controls (blocking under the evidence rule):

| Finding | Basis | Source |
| --- | --- | --- |
| afk-app#4 read 8: null `merged_by` / `session_id` | REACHABLE | producers `quarantine.py:183`, `telemetry.py:508`, `issue_source.py:604-605` |
| afk-app#4 read 3: anti-scope forbids the Codable change the criterion needs | MEASURED | the read's probe build |
| afk-app#2 read 4: the volatile-key exemption collides with strict-nullable | MEASURED | the read's probe build |
| afk-app#4 read 2: `tokens: dict \| None` | MEASURED | `models.py` |
| afk-app#1 read 3: claims not paired with issue numbers | traced | the original body's rule |

Negative controls (advisory under the evidence rule; each targets a reader-born rule or boundary and has no basis):

| Finding | Why advisory |
| --- | --- |
| afk-app#3 read 6: fleet failure vs shown issues | REASONED, reader-born boundary |
| afk-app#2 read 6: `refresh()` fleet request | REASONED, reader-born boundary |
| afk-app#4 read 9: `git grep` empty-marker | REASONED, reader-born boundary |
| afk-app#1 read 5: missing sibling line | REASONED, reader-born boundary |
