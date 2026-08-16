---
name: detector-teeth-check
description: Verify a test suite would actually catch the bug it claims to prevent, by re-injecting the defect and checking the suite goes red. Use after writing tests for a security boundary, a validator, a detector, or any guard whose failure mode is silent — and before trusting a green suite as evidence.
---

# Detector teeth check

A green suite proves the tests ran, not that they would notice if the code were
wrong. This skill breaks the code on purpose and reports which tests go red.

- **A surviving mutant** names a property nothing tests. That is a gap.
- **A test that catches no mutant** either duplicates another or covers
  something the spec forgot to mutate. A question, not a verdict.

## When to run it

After writing tests for anything whose failure is silent: a path/access check,
a validator, a classifier, a retry or fail-closed guard, a permission rule.
Especially when they pass first try — the case where a test asserting nothing
looks identical to one asserting the right thing.

## How to run it

Write a JSON spec next to the code, then run from the directory where the test
command works:

```json
{
  "test_command": ["uv", "run", "pytest", "-q", "tests/test_thing.py"],
  "collect_command": ["uv", "run", "pytest", "--collect-only", "-q", "tests/test_thing.py"],
  "mutants": [
    {
      "label": "no upper bound on k",
      "file": "engine/thing.py",
      "find": "k = min(k, MAX_RESULTS)",
      "replace": "k = k"
    }
  ]
}
```

```bash
python scripts/teeth_check.py spec.json
```

Exit code is non-zero when any mutant survives or any row fails to score, so it
can gate CI. `--json` emits the machine-readable form. `collect_command` is
optional; without it the caught-no-mutant list reads _not computed_, not an
empty all-clear.

## Choosing mutants

Mutate the _decision_, not the syntax. A good mutant is the plausible wrong
implementation — the one a competent person would write if they had not
thought about the edge case:

- reorder two checks (validate before normalize instead of after)
- widen a default (`frozenset()` → `frozenset({"a", "b"})`)
- drop a clamp, a guard clause, or one branch of an `and`
- make a fail-closed default fail open

Mutating a constant to a different constant usually proves nothing. Ask what
the code is _for_, and break that.

**A surviving reordering mutant is often a test problem, not a coverage gap.**
When the two orders differ only by a race, a test asserting the _consequence_
passes under both nearly every time. Assert the ordering itself — was the
worker stopped when the unlink ran? — not a symptom whose visibility is timing.

## Reading the output

The matrix maps each mutant to the tests that killed it.

- **One killer** means that test carries the property alone; weaken it and the
  property goes unguarded silently.
- **Many killers** may mean good coverage, or a mutant too broad to inform.
- **`not-applied` and `unscored` are harness errors, not test weaknesses.**
  Neither is a kill or a survivor. Fix and re-run — reading one as a survivor
  sends you hunting for a test that already exists.
- **Before chasing a survivor, check the mutant actually changes behaviour.** A
  semantic no-op survives everything and looks exactly like a real gap. Adding
  `except BaseException: raise` above a `finally:` changes nothing.

## What it refuses to score

Absence of a failure signal is never evidence of a pass. Three cases refuse:

- **A red baseline** — every mutant would look killed. Exits 2.
- **An anchor matching zero or more than one place** — ambiguous means the spec
  never said which site it meant.
- **A run that named no failing test.** A mutant that will not compile, or a
  command aborting before collection (unrecognised flag, missing plugin), exits
  non-zero with no `FAILED` line — the harness broke, no assertion caught
  anything. Python mutants are compile-checked first, catching it at the source.

## Safety

Files are edited in place and restored from saved bytes in a `finally` — never
by `git checkout`, which would destroy uncommitted work. Commit before running
anyway: `git status` is then an independent check that everything was restored.
