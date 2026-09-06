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

## How a tooth goes blind

A blind tooth is a test that cannot go red for the defect it was written to
catch. Every one reads as a completely reasonable test — which is why review
finds these and a green suite never does. In one nine-slice review, five of
six confirmed findings were blind teeth; only one was a defect in the code.

Four mechanisms, each with the instance that produced it:

- **Prefix collision.** A partial-config builder dropped lines matching
  `line.startswith("flamingo_decided")`, which also removed
  `flamingo_decided_note` — two keys gone, not one. The assertion
  `pytest.raises(..., match="flamingo_decided")` could not tell which of the
  pair the error named, because one name is a literal prefix of the other.
  Proven blind by reordering validation to report the _wrong_ key: all four
  parametrized cases stayed green. Fix: drop by exact key, and match the
  repr-quoted key (`match=f"'{key}'"`) so a longer sibling cannot satisfy it.
- **Right name, wrong module.** A class named
  `TestBalancesMessageWordingChangesToAmount` exercised the _actuals_ code
  path, so `assert "amount must be…" in msg` and
  `assert "balance must be" not in msg` were both tautologically true against
  a message that never said "balance". The wording change the class claimed to
  pin had zero coverage. Fix: assert against the module the name claims — a
  test class name is not a call site.
- **Vacuous fixture.** An `abs()`-drop tooth aimed at a field-for-field test
  survived because the fixture's only negative value belonged to an account
  the code filters out, so every surviving row made `abs()` a no-op. Fix: make
  a _surviving_ row carry the property under test.
- **Unpinned claim.** The spec pinned a request shape
  (`startMonth = endMonth = month`), and both test doubles ignored their
  arguments — so hardcoding a wrong month passed all 49 tests. Fix: a
  recording double that asserts the request shape.

Two questions catch most of these before the harness runs:

- **What input or fixture would make this mutation a no-op?** If one exists,
  the fixture is doing the guarding, not the assertion.
- **Can the assertion distinguish this defect from any other failure?** A
  generic "raises and exits 1" passes for the wrong reason as readily as the
  right one.

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

## Traps that fake a survivor

The semantic no-op above is one of four ways a mutation reports "no teeth"
when the test was never given a chance to fail. Each makes a sound test look
toothless, and the wrong conclusion is expensive: you rewrite a test that was
already correct.

- **Precedence in a disabling mutation.** `and` binds tighter than `or`, so
  prefixing a multi-clause condition with `False and` neuters only the first
  clause — `False and a or b` still evaluates `b`, and the guard stays live.
  The test stays green and you conclude "no teeth" about a guard that never
  stopped running. Mutate the _whole_ condition: parenthesize it, or replace
  it outright with `False`.
- **A mutation the test never reaches.** A re-added local finiteness check
  placed _after_ a shared parser that already rejected the value never
  executed, so the suite stayed green and the tooth measured nothing. An
  earlier guard that raises makes everything below it dead code. Before
  believing a survivor, confirm the mutated line is on the path the test
  actually drives.
- **Stale bytecode after an equal-length mutation.** CPython validates a cached
  `.pyc` against the source's byte size and its mtime truncated to whole
  seconds. A same-length replacement (`>=` for `<=`) written inside that same
  second passes both checks: the interpreter loads the old bytecode and the
  mutant never runs. Compile-checking the mutated _text_ does not catch this —
  it proves the mutant is valid Python, not that it executed. Worse in
  reverse: a restore landing in the same second can leave the previous
  mutant's bytecode live, so a _later_ row scores the wrong mutation.
  `teeth_check.py` closes both by purging the mutated module's cache around
  every run and running with bytecode writing disabled. Mutating by hand, do
  the same — and delete the `.pyc` rather than relying on
  `PYTHONDONTWRITEBYTECODE=1`, which stops the cache being written, not read,
  so the stale one already on disk still wins.
- **Confirm red, don't assume it.** Read the pytest summary line. A grep for
  assertion text can match an unrelated test's output, or a collection error
  that scored nothing at all.

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
by `git checkout`, which would destroy uncommitted work. The only files it
deletes are `__pycache__` entries for the modules it mutates: regenerable
bytecode, never source. Commit before running
anyway: `git status` is then an independent check that everything was restored.

## Related

- `adversarial-review` — where blind teeth actually surface. A green matrix
  never reports one, so point a hostile pass at the tests, not just the code.
- `drain-queue` — gates the spec before a build; this gates the tests after.
