---
name: eval-suite
description: >
  Conducts one named skill's eval-suite run end to end: prepares each
  fixture, dispatches it, retries it per the harness's counted/reserve rule,
  scores it, and writes the run file. Use when hand-running a skill's eval
  suite (starting with the calibration issue #989) — never invoked by an afk
  child, and never triggered automatically by CI or a hook.
---

# Eval Suite Conductor

This skill documents how to run one named skill's eval suite. It executes nothing on its own.
It is loaded and followed by hand, in a conversation where a human explicitly runs it.
It is never invoked by an afk child; it is exercised for the first time by the hand-run
calibration issue #989.

Every fixture it drives lives in a case directory, `evals/<skill>/<case>/`,
that already satisfies the case-directory contract (`case.toml`,
`prompt.md`, `acceptance.md`, a fixture source, `predicates.py`, and
`provenance.toml` when content is copied — see issue #995 for the contract
in full). This skill never scaffolds a case directory and never edits
`checks.manifest`, `gaps.md`, `retired.md`, or `deps` — those are populated
by #996 (per-skill scaffolding) and #998–#1002 (case directories).

The steps below apply to one named skill at a time. The worked examples use
`adversarial-review`, since it is the only skill whose fixture list includes
an inline lens-mode case (`A2`) — every step applies identically to any
other rostered skill.

## Case-directory contract (summary)

`evals/<skill>/<case>/` holds, per issue #995's contract:

- `case.toml`: `mode = "subagent" | "inline"` and `prompt = "prompt.md"`
  (both required); optional `envelope = "findings"` (set only by a case whose
  scorers read `evidence.findings`; every other case is never a parse-error
  miss on a prose reply); one or more `[[items]]` tables, each with `id`
  (unique within the skill), `kind = "gate-candidate" | "trend" |
  "triggering"`, `scorer = "<function in predicates.py>"`, and an optional
  `params` table.
- `prompt.md`: the story sent to the case-agent (or to each lens agent).
- `acceptance.md`: private acceptance criteria. Scorer-only; never sent to
  any dispatched agent.
- a fixture source: `fixture/`, a builder (a case-local `build_fixture.py` or
  a `builder = "<repo-relative path>"` key), or both.
- `predicates.py`: every scorer the items name, each
  `scorer(evidence, **params) -> bool`; it may also define
  `end_state(workdir, case_dir, transcripts) -> dict[str, str]`. A scorer for
  an end-state item reads `evidence.end_state`, never `evidence.workdir`.
- `provenance.toml`, whenever prompt or fixture content is copied.
- `calibration.json` is written later, by the hand-run issue #989.

## 1. Enumerate and prepare the skill's fixtures

Every case directory directly under `evals/<skill>/` is one fixture. For each:

1. Read `case.toml` to find its dispatch mode (`subagent` or `inline`) and
   its fixture source.
2. Prepare a fresh, **not-yet-existing** temporary `<dest>` directory:
   - A case with only a committed `fixture/` tree: copy `fixture/` into
     `<dest>`.
   - A case with a builder (a case-local `build_fixture.py`, or a `builder =
     "<repo-relative path>"` key in `case.toml`): run
     `python <builder> <dest>` into the not-yet-existing `<dest>` (the
     builder reads the case's `fixture/` itself when both are present).
3. Before the fixture's *first* attempt, fingerprint it with
   `evals._harness.calibration.fixture_fingerprint(case_dir)`, and record the
   result as the run file's `cases[].fixture_fingerprint`.

## 2. Derive which items are gated

Read `evals/<skill>/checks.manifest`: one `<id> <one-line description>` per
line, `#` comments and blank lines ignored (scaffolded by #996). An item is
gated iff its id appears there; every item whose id is absent is a trend
item. The conductor is the only reader of this file — the scorer
(`evals._harness.scorer`) never reads it itself.

This gated/trend split is used in three places once derived:

- passed as `score_attempt`'s `gated_ids` argument;
- passed as each item's `gated` flag inside `compute_verdict`'s `items`
  mapping;
- recorded verbatim as the case's `gated_items` field in the run file.

## 3. Dispatch each fixture

- `mode = "subagent"` (every fixture whose `case.toml` says so): dispatch a case-agent as a
  subagent. Its sole turn is the text
  `evals._harness.dispatch.build_dispatch_prompt(case_dir)` returns (or
  `build_no_skill_prompt(case_dir)`'s output, for a no-skill calibration arm
  run by #989). The case-agent runs inside the fresh `<dest>` built in step
  1 — never inside the-workshop checkout.
- `mode = "inline"` (adversarial-review's lens-mode `A2` fixture): run
  inline. The conductor plays adversarial-review's own conductor role
  itself — it does not dispatch a subagent that then dispatches lens
  agents. It dispatches each lens agent directly, from the same running
  conversation, and collects one transcript per lens agent.

Every case is a single prompt with zero user turns, regardless of mode.

## 4. Snapshot end-state evidence, then score

After every attempt (subagent or inline), before scoring it:

1. Snapshot end-state evidence with
   `evals._harness.dispatch.snapshot_end_state(case_dir, workdir, transcript_paths, dest)`,
   writing into the attempt's own `end_state/` directory inside its
   collected raw directory. This lets the attempt be re-scored later from
   raws alone, with no live repo state.
2. Score the attempt with
   `evals._harness.dispatch.score_attempt(case_dir, transcript_paths, workdir, gated_ids, transcript_status=None, end_state_dir=<the end_state/ directory just snapshotted>)`.
   This parses every transcript, builds an `Evidence` object, runs every
   item's `predicates.py` scorer, and returns
   `evals._harness.scorer.classify_attempt(...)`'s result (an `Attempt`)
   plus the trend unmatched-finding count. `envelope_parsed` is computed (via
   `extract_findings`) only for a case that sets `envelope = "findings"`;
   every other case passes it as `True`. Pass
   `transcript_status="dispatch_error"` only when the attempt never
   produced a transcript at all (dispatch itself failed) — otherwise leave
   it `None` so `score_attempt` derives the status from the transcripts.

## 5. The retry loop

A fixture is re-executed while any of its gated items is still unmet. The
loop is driven by
`evals._harness.scorer.should_retry(item_states, counted_attempts, reserve_used) -> bool`,
stated here exactly as #991 implements it: counted_attempts counts only
non-indeterminate (non-harness-breakage) attempts, and reserve_used counts
how many of the fixture's indeterminate reserve of 2 have been drawn;
`item_states` maps each *gated* item id to whether any counted attempt has hit
it so far. An
indeterminate attempt — harness breakage: a dispatch error, a missing or
truncated transcript, or an API-error transcript entry — never increments
counted_attempts; it is replaced from the reserve instead. `should_retry`
returns `False` once counted_attempts reaches 3, or once
counted_attempts + reserve_used reaches 5 — whichever comes first. 5 is
therefore the hard execution cap per fixture (3 counted plus, at most, 2
reserve draws).

Once the loop ends (every gated item met, or `should_retry` returned
`False`), compute the fixture's verdict with
`evals._harness.scorer.compute_verdict(items)`, where `items` maps each
item id to `(gated, outcomes)` — `outcomes` being one
`"hit"`/`"miss"`/`"indeterminate"` per execution, accumulated by the
conductor across every attempt of that fixture.

## 6. Write the run file and, on red, the report

- Write the run file, plus every attempt's raws (including its `end_state/`
  snapshot), with `evals._harness.ledger.write_run(runs_dir, run, raw_sources)`.
- If the run's verdict is `"red"`, write the report with
  `evals._harness.report.write_report(run_file)`.

This skill documents calling these entry points; it does not reimplement
any of them, and it never edits `scorer.py`, `ledger.py`, `report.py`, or
`calibration.py`.

## 7. Land the run

The run lands as its own `test(evals):` PR into `dev`, or riding along with
the skill PR that triggered it. A red run's report is the entry input for
an `improve-skill` campaign — started by hand, never automatically from
inside this skill.

## Harness entry points, by module and function

| Entry point | Owner | What it does |
| --- | --- | --- |
| `dispatch.snapshot_end_state` | #995 | Snapshots an attempt's end-state evidence before scoring. |
| `dispatch.score_attempt` | #995 | Parses transcripts, scores every item, returns an `Attempt` plus the unmatched-finding count. |
| `scorer.classify_attempt` | #991 | Classifies one attempt (`score_attempt` calls it). |
| `scorer.should_retry` | #991 | Decides whether to run another attempt (the retry loop in step 5). |
| `scorer.compute_verdict` | #991 | Reduces a fixture's accumulated item outcomes to green/red/void. |
| `calibration.fixture_fingerprint` | #994 | Fingerprints a case's fixture before its first attempt. |
| `ledger.write_run` | #993 | Writes the run file and every attempt's raws. |
| `report.write_report` | #993 | Writes the red-run report. |
