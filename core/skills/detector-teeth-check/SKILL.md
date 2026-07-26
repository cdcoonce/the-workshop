---
name: detector-teeth-check
description: Verify a test suite would actually catch the bug it claims to prevent, by re-injecting the defect and checking the suite goes red. Use after writing tests for a security boundary, a validator, a detector, or any guard whose failure mode is silent — and before trusting a green suite as evidence.
---

# Detector teeth check

A green suite proves the tests ran. It does not prove they would notice if the
code were wrong. This skill breaks the code on purpose and reports which tests
— if any — go red.

Two findings come out of it:

- **A surviving mutant** names a property nothing tests. That is a gap.
- **A test that catches no mutant** either duplicates another test or covers
  something the spec forgot to mutate. That is a question, not a verdict.

## When to run it

After writing tests for anything whose failure is silent: a path/access check,
a validator, a classifier, a retry or fail-closed guard, a permission rule.
Especially when the tests pass on the first try — that is the case where a
test asserting nothing looks identical to a test asserting the right thing.

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

Exit code is non-zero when any mutant survives or any anchor fails to match,
so it can gate CI. `--json` emits the machine-readable form.

`collect_command` is optional; without it the caught-no-mutant list is
reported as _not computed_ rather than as an empty all-clear.

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

## Reading the output

The matrix maps each mutant to the tests that killed it.

- **One killer** is worth noticing. That single test is carrying the property
  alone; if it is deleted or weakened, the property goes unguarded silently.
- **Many killers** may mean the property is well covered, or that the mutant
  was too broad to be informative.
- **A `not-applied` row is a spec error, not a test weakness.** The anchor no
  longer matches the source. Fix the spec and re-run — never read it as a
  survivor, or you will hunt for a test that already exists.

## Why it refuses a red baseline

Against an already-failing suite every mutant looks killed, and the run would
report reassuring nonsense. The script checks the suite is green before it
mutates anything and exits 2 if it is not.

## Safety

The script edits source files in place and restores them in a `finally`, so an
exploding test command cannot leave mutated code on disk. Even so, run it on a
clean working tree: that way `git status` is an independent check that
everything was put back.
