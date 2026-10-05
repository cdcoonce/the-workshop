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

The steps below apply to one named skill at a time. Only `adversarial-review`
has an inline lens-mode fixture (`A2`); every step otherwise applies
identically to any other rostered skill.

Run every harness call from the checkout root with
`uv run --with pytest --with jsonschema python` (the way `make test-evals`
runs the harness): `evals/` is imported as the `evals._harness` package from
the root, `ledger` needs `jsonschema`, and a case's `end_state` snapshot runs
the fixture's pytest through the harness interpreter, so that interpreter
needs `pytest` too (without it every attempt silently records a miss).
Run a conductor script with `python -c` or
`python -m`, or with `PYTHONPATH=.`, from the checkout root: a script saved
outside the checkout root fails with `No module named 'evals'`.

## Case-directory contract (summary)

`evals/<skill>/<case>/` holds, per issue #995's contract:

- `case.toml`: `mode = "subagent" | "inline"` and `prompt = "prompt.md"`
  (both required); optional `envelope = "findings"` (set only by a case whose
  scorers read `evidence.findings`; every other case is never a parse-error
  miss on a prose reply); optional `invoke_skill = true` (explicit
  invocation: the skill arm's prompt starts with `Use the workbench:<skill>
  skill for this task.` and a blank line; the no-skill arm never carries it;
  refused on a case with a `triggering` item, which it would hand its answer;
  default off, so every other case's prompt is unchanged); one or more
  `[[items]]` tables, each with `id`
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

Every directory under `evals/<skill>/` that contains a `case.toml` is one
fixture (`evals/<skill>/<case>/`). Nothing else there is a fixture: `runs/`,
`deps`, `checks.manifest`, `gaps.md`, and `retired.md` also live in
`evals/<skill>/`, so list fixtures by the presence of `case.toml`, never by
listing every entry. For each fixture:

1. Read `case.toml` to find its dispatch mode (`subagent` or `inline`) and
   its fixture source.
2. Prepare a fresh, **not-yet-existing** temporary `<dest>` directory:
   - A case with only a committed `fixture/` tree: run
     `python -m evals._harness.fixture_copy <case_dir> <dest>`, which copies
     `fixture/` into `<dest>` without the files the case lists under
     `fixture_private` in `case.toml` (an answer key, such as A2's
     `defects.json`). Never copy `fixture/` by hand: a whole-tree copy hands
     the answer key to every dispatched agent. Before dispatching, run
     `python -m evals._harness.fixture_copy --check <case_dir> <dest>`; it
     fails if `<dest>` holds a private file.
   - A case with a builder (a case-local `build_fixture.py`, or a `builder =
     "<repo-relative path>"` key in `case.toml`): run
     `python <builder> <dest>` into the not-yet-existing `<dest>` (the
     builder reads the case's `fixture/` itself when both are present). When
     a case has both a `builder` key and a case-local `build_fixture.py`, the
     `builder` key wins over a case-local `build_fixture.py`
     (`calibration.fixture_fingerprint` resolves them the same way).
3. Before the fixture's *first* attempt, fingerprint it with
   `evals._harness.calibration.fixture_fingerprint(case_dir)`, and record the
   result as the run file's `cases[].fixture_fingerprint`.

## 2. Derive which items are gated

Read `evals/<skill>/checks.manifest`: one `<id> <one-line description>` per
line, `#` comments and blank lines ignored (scaffolded by #996). An item is
gated iff its id appears there; every item whose id is absent is a trend
item. The conductor is the only reader of this file — the scorer
(`evals._harness.scorer`) never reads it itself.

Parse the file with `evals._harness.activation.parse_checks_manifest(text)`
(it takes the file's text and returns the gated ids in file order), rather
than hand-parsing it: it owns the comment, blank-line, and id-grammar rules.
Every case of the skill shares this one gated set, because item ids are one
namespace per skill; `score_attempt` ignores ids that belong to a sibling
case. For the same reason, a manifest id that names no item in any case of
the skill is a conductor error: check every id against the items of all the
skill's cases, surface it and stop. `score_attempt` would otherwise ignore the
typo and the item would silently never gate.

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
  conversation, giving each the prompt text
  `evals._harness.dispatch.build_dispatch_prompt(case_dir)` returns, and
  collects one transcript per lens agent.

Every case is a single prompt with zero user turns, regardless of mode.

## 4. Snapshot end-state evidence, then score

After every attempt (subagent or inline), before scoring it:

1. Snapshot end-state evidence with
   `evals._harness.dispatch.snapshot_end_state(case_dir, workdir, transcript_paths, dest)`,
   writing into the attempt's own `end_state/` directory inside its
   collected raw directory. This lets the attempt be re-scored later from
   raws alone, with no live repo state. `dest` must be a fresh, empty
   `end_state/` directory: a populated one is refused, so stale files from an
   earlier snapshot can never pass for this attempt's evidence. `transcript_paths`
   are the attempt's transcript JSONL files, one per case-agent (one per lens
   agent, inline): a subagent's transcript is
   `<session>/subagents/agent-<id>.jsonl`, as `evals._harness.transcript`
   documents. Use a new `end_state/` directory for every attempt;
   re-snapshotting an attempt (after fixing `end_state()`, say) needs a new
   path, or the old `end_state/` deleted first. Skip this step for an attempt
   that ended in `dispatch_error`: it has no transcripts and may have no
   workdir, so there is nothing to snapshot, and `score_attempt` runs no
   scorers for it.
2. Score the attempt with
   `evals._harness.dispatch.score_attempt(case_dir, transcript_paths, workdir, gated_ids, transcript_status=None, end_state_dir=<the end_state/ directory just snapshotted>)`.
   This parses every transcript, builds an `Evidence` object, runs every
   item's `predicates.py` scorer, and returns
   `evals._harness.scorer.classify_attempt(...)`'s result (an `Attempt`)
   plus the trend unmatched-finding count. `envelope_parsed` is computed (via
   `extract_findings`) only for a case that sets `envelope = "findings"`;
   every other case passes it as `True`. Pass
   `transcript_status="dispatch_error"` only when the attempt never
   produced a transcript at all (dispatch itself failed); it accepts no other
   value, and with `None` it derives the status from the transcripts.

## 5. The retry loop

A fixture is re-executed while any of its gated items is still unmet. The
loop is driven by
`evals._harness.scorer.should_retry(item_states, counted_attempts, reserve_used) -> bool`,
stated here exactly as #991 implements it: counted_attempts counts only
non-indeterminate (non-harness-breakage) attempts, and `reserve_used` counts
how many of the fixture's indeterminate reserve of 2 have been drawn;
`item_states` maps each *gated* item id to whether any counted attempt has hit
it so far. An
indeterminate attempt — harness breakage: a dispatch error, a missing or
truncated transcript, or an API-error transcript entry — never increments
counted_attempts; it is replaced from the reserve instead. `should_retry`
returns `False` once counted_attempts reaches 3, or once
counted_attempts + reserve_used reaches 5 — whichever comes first. 5 is
therefore the hard execution cap per fixture (3 counted plus, at most, 2
reserve draws — the conductor enforces the 2, see below).

A case with no gated items makes `should_retry` return `False` at once
(`should_retry({}, 0, 0)` is `False`), so an indeterminate first attempt of
such a case is not replaced.

`should_retry` does not enforce the reserve size: it bounds only
`counted_attempts + reserve_used` (at 5), never `reserve_used` itself
(`should_retry({"a": False}, 0, 4)` is `True`). The
conductor must stop drawing reserve attempts itself once `reserve_used`
reaches 2: a third indeterminate attempt is not replaced, and the fixture's
unresolved gated items end void. Increment `reserve_used` each time an
indeterminate attempt is replaced, and never call `should_retry` with a
`reserve_used` above 2. Record an attempt's `reserve_used` after that step:
an indeterminate attempt's own record carries the count including the draw
that replaces it (a lone indeterminate attempt that is replaced records
`reserve_used` 1), and a counted attempt carries the running count
unchanged.

Once every fixture's loop has ended (every gated item met, or `should_retry`
returned `False`), compute the run's verdict with
`evals._harness.scorer.compute_verdict(items)`, called once with every case's
items merged into one mapping (ids are unique per skill, so they cannot
collide; this is the same as taking each case's verdict and letting red beat
void beat green). `items` maps each item id to `(gated, outcomes)` —
`gated` from step 2, and `outcomes` being one
`"hit"`/`"miss"`/`"indeterminate"` per execution, accumulated by the
conductor across every attempt of that item's fixture (each attempt's
`Attempt.item_hits[item_id]`, in execution order). The result is the run's
`verdict` (see step 6).

## 6. Write the run file and, on red, the report

Build one `run` dict for the whole run, then write it. Its shape is the one
`evals/_harness/schemas/run-file.schema.json` validates:

- `run` has the keys `skill` (the skill name), `verdict`, `fingerprint`,
  `tokens` (an integer: the total tokens the run spent, summed over every
  execution's token usage as the dispatch tool reports it, replacements and
  indeterminate attempts included), `wall_time_s` (a number: the run's
  wall-clock seconds, from the first dispatch to the last), and `cases`.
- `run["verdict"]` is the result of `compute_verdict` (step 5): `"green"`,
  `"red"`, or `"void"`.
- `run["fingerprint"]` is
  `evals._harness.fingerprint.compute_fingerprint(direct_paths=...,
  injection_paths=..., plugin_version=..., claude_code_version=...,
  run_date=...)`, where `direct_paths` and `injection_paths` are the
  `"direct"` and `"injection"` lists that
  `evals._harness.deps.parse_deps(<text of evals/<skill>/deps>)` returns,
  `plugin_version` is the `version` in
  `plugins/<plugin>/.claude-plugin/plugin.json` of the plugin that ships the
  skill under test, `claude_code_version` is the output of
  `claude --version` for the session that ran the dispatches, and `run_date`
  is `YYYY-MM-DD`. The schema has no defaults: all five fingerprint keys are
  required, so look the two versions up rather than guessing.
- `run["cases"]` has one entry per fixture, with the keys `case` (the case
  directory's name), `fixture_fingerprint` (from step 1), `gated_items` (the
  list of that case's gated item ids from step 2, recorded verbatim), and
  `attempts`. The schema also requires `model_ids`, but it is computed by
  `write_run` from the case's raw transcripts, so leave it out.
- `attempts` has one entry per execution, counted or not, in order: `attempt`
  (the 1-based execution number within the case), `classification` (from
  `Attempt.classification`), `items` (from `Attempt.item_hits`: every item
  id of the case mapped to `"hit"`, `"miss"`, or `"indeterminate"`),
  `parse_error` (from `Attempt.parse_error`), `unmatched_findings` (the
  second member of the tuple `score_attempt` returned), `reserve_used` (the
  running count of reserve draws once this attempt is recorded, the same
  value you hand `should_retry`), and `raw` (any string you choose; it is
  only the key into `raw_sources`).

A complete example of the `run` dict, as `write_run` takes it (a case with one
indeterminate attempt, replaced from the reserve, then one counted attempt;
`model_ids` is absent because `write_run` fills it in):

```json
{
  "skill": "adversarial-review",
  "verdict": "green",
  "fingerprint": {
    "direct_tier_hash": "<sha256 from compute_fingerprint>",
    "injection_tier_hash": "<sha256 from compute_fingerprint>",
    "plugin_version": "8.27.0",
    "claude_code_version": "2.1.0",
    "run_date": "2026-09-30"
  },
  "tokens": 123456,
  "wall_time_s": 412.5,
  "cases": [
    {
      "case": "A1",
      "fixture_fingerprint": "0000000000000000000000000000000000000000000000000000000000000000",
      "gated_items": ["item-a"],
      "attempts": [
        {
          "attempt": 1,
          "classification": "indeterminate",
          "items": {"item-a": "indeterminate", "item-t": "indeterminate"},
          "parse_error": false,
          "unmatched_findings": 0,
          "reserve_used": 1,
          "raw": "A1/attempt-1"
        },
        {
          "attempt": 2,
          "classification": "counted",
          "items": {"item-a": "hit", "item-t": "miss"},
          "parse_error": false,
          "unmatched_findings": 2,
          "reserve_used": 1,
          "raw": "A1/attempt-2"
        }
      ]
    }
  ]
}
```

Collect each attempt's raws in one directory: its transcripts as `*.jsonl`
files at that directory's root, beside the `end_state/` snapshot directory
from step 4. `ledger.write_run` globs `*.jsonl` at that root to compute
`model_ids`, so a transcript placed in a subdirectory is never seen.

Then write the run file, plus every attempt's raws (including its
`end_state/` snapshot), with
`evals._harness.ledger.write_run(runs_dir, run, raw_sources)`, where
`runs_dir` is `evals/<skill>/runs/` and `raw_sources` maps each attempt's
`raw` key to that attempt's raw directory. `write_run` overwrites each `raw`
with its own `<stem>/<case>/attempt-<n>/` path, refuses to overwrite an
existing run file, and returns the written run file's path.

- If the run's verdict is `"red"`, write the report with
  `evals._harness.report.write_report(run_file)`, where `run_file` is the
  path `write_run` returned.

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
| `activation.parse_checks_manifest` | harness | Parses `checks.manifest` text into the gated ids (step 2). |
| `deps.parse_deps` | harness | Parses a skill's `deps` file into the direct and injection path lists (step 6). |
| `fingerprint.compute_fingerprint` | harness | Builds `run["fingerprint"]` (step 6). |
