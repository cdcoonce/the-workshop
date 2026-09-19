---
name: detector-teeth-check
description: >
  Prove tests catch the defect they claim to prevent: re-inject it, check the
  suite goes red. Use for any teeth check, mutation run or vacuous-test doubt,
  and in place of hand-rolling a mutate/revert script, which loses work and
  runs stale bytecode.
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
  "runner": "pytest",
  "test_command": ["uv", "run", "pytest", "-q", "tests/test_thing.py"],
  "collect_command": ["uv", "run", "pytest", "--collect-only", "-q", "tests/test_thing.py"],
  "mutants": [
    {
      "label": "no upper bound on k",
      "file": "engine/thing.py",
      "oracle": "real",
      "find": "k = min(k, MAX_RESULTS)",
      "replace": "k = k"
    },
    {
      "label": "[control] reorder two independent writes",
      "file": "engine/thing.py",
      "oracle": "real",
      "expect": "survived",
      "why": "Distinct keys, neither reads the other's write; inert on every path the suite reaches.",
      "find": "save(A)\n    save(B)",
      "replace": "save(B)\n    save(A)"
    }
  ]
}
```

```bash
python3 "<skill base directory>/scripts/teeth_check.py" spec.json
```

Commit the spec next to the tests, and check its anchors are still live:

```bash
python3 "<skill base directory>/scripts/teeth_check.py" --check-anchors spec.json
```

`--check-anchors` resolves every anchor and runs nothing — no baseline, no
test command, no write — in about the time a linter takes. It exists because
the anchors are exact source strings, so any refactor of the code under test
rots all of them at once, silently, until someone re-runs the matrix and
rebuilds the table by hand. Run it wherever the repo already runs something
fast, and the spec breaks while its author still has the context.

Re-running the mutants after a genuine restructure is **not** waste: the old
mutants described defects in code that no longer exists, so those verdicts
really did expire. The waste is re-deriving the table from a shell history,
which is what happens whenever the spec was never a file.

The absolute path matters. `cwd` is the target repository, which does not
contain this skill, so a bare `scripts/teeth_check.py` fails on a missing file
— and in a repo that has its own `scripts/` it fails on a directory that
exists, which reads like a broken tool rather than a wrong path. Do not fall
back to writing your own loop when the path is wrong: fix the path. A
hand-rolled mutate/revert script is how uncommitted work gets destroyed by
`git checkout --` and how a same-size mutation runs stale bytecode; this script
already closes both (see **Safety** and **Traps that fake a survivor**), and
its spec is a committable artifact, so the count in the pull-request body stays
re-runnable instead of becoming prose.

Exit code is non-zero when any mutant survives unexpectedly, any row fails to
score, or a declared control gets caught, so it can gate CI. `--json` emits the
machine-readable form. `collect_command` is optional; without it the
caught-no-mutant list reads _not computed_, not an empty all-clear. `oracle` is
required per mutant — see **Traps that fake a kill**.

## Runners

`runner` names the suite's output shape: `pytest` (the default) or `vitest`.

It is defaulted rather than required, unlike `oracle`, and the asymmetry is the
reason. A wrong `oracle` manufactures a guarantee nobody checked. A wrong
`runner` makes every row `unscored` — a refusal, never a false kill — so a
default here cannot certify anything it did not measure.

That refusal used to be a dead end. A vitest suite scored `unscored` on every
row, with advice pointing at the mutant and the test command, neither of which
could possibly help; the tool read as broken and the loop got hand-rolled
instead. So an `unscored` row now tests its output against every other
registered runner and names the one that matches, putting the fix in the
message.

A vitest run that fails to _transform_ the mutated file prints a `FAIL` line
naming the file with no test after it. That is not a kill — nothing was
collected and no assertion ran — so it scores `unscored`, exactly as a Python
mutant that will not compile does.

## Declare a control

A matrix where everything dies cannot be told apart from a rig that reports red
for everything: a broken test command, a mutant that kills the import, a
baseline that was never green. One row per spec should be a mutation you can
argue is semantically inert, declared `"expect": "survived"`. It holds green and
proves the rig discriminates.

`why` is required on that row, and the report prints it verbatim instead of a
count, because the argument _is_ the artifact. A control justified by "I ran it
and nothing broke" is empirical, not structural, and is indistinguishable from a
survivor someone talked themselves out of.

State the scope the inertness holds over, and name where it does not. Two
`localStorage` writes on independent keys are inert on every path a suite
reaches — and are not atomic, so a quota throw between them persists different
state by order. Saying so is what separates a control from a rationalisation.

A control that gets **killed** is a hard failure, not a curiosity: either the
inertness argument is wrong and it is a real mutant, or a test is asserting
incidental form rather than behaviour. Both need a person.

A run whose only green row is the control has proved the harness executes, and
nothing whatever about teeth.

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
- **"It turned out to be a no-op" can itself be the finding.** Discarding it as
  a bad mutant is the reflex, and it is wrong whenever the code _claims_ that
  line is load-bearing. A clamp documented as protecting a second code path
  survived its mutation because the clamp did not protect it: the comment was
  false, and the test pinning that comment asserted nothing. The defect was the
  claim, not the mutant. Read what the code says about a line before concluding
  the line does not matter.

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

## Traps that fake a kill

Everything above is about a test that will not go red when it should. The
opposite failure is quieter and costs more: **a mutant that dies while proving
nothing.** The matrix reports teeth, the gate signs, and the property is
unguarded.

**The mirror.** A recording double is built from the shape the code under test
emits. Mutate that code and the recording changes, so the assertion fails and
the mutant dies — guaranteed, before the suite ever runs. Mutation testing
perturbs our source; a recording double's oracle *is* our source. They share an
oracle, so stacking them adds no coverage while presenting as two independent
gates.

This is the failure mode of the fix prescribed for **unpinned claim** above: "a
recording double that asserts the request shape" is the right remedy for a
double that ignores its arguments, and it is still blind to whether the real
collaborator accepts them. A dlt landing converted from `replace` to a
year-scoped `merge`; both named teeth for the schema-freeze contract scored
against recording doubles, both mutants died, and dlt rejected the combination
on **every** run for seven days. Re-run afterwards, the pre-fix suite went
_green_ for the defect that broke 100% of materializations and _red_ for the
one-line change that would have fixed it.

So each mutant declares what executed the assertion:

- `real` — the actual dependency ran. The kill bounds behaviour.
- `double` — a stand-in recorded the call. The kill bounds the argument that
  was passed, and nothing further.

The harness refuses a spec that omits it, and keeps the two apart in the tally
(`5 killed — 2 against the real dependency, 3 against doubles`) instead of
summing them into one reassuring number. A `double` row is not a failure; it is
a scoped claim that has to be _written_ at that scope. Judge by the assertion's
subject, not by whether a fixture exists somewhere — a stand-in sitting upstream
of the property under test still leaves that property really executed.

**Mutations you cannot spell in source.** Find/replace says "the code is
wrong". It cannot say "the destination was built by the previous version of
this code" — and a conversion defect lives exactly there. Every fixture-building
integration test is born *after* the change, so the first run after deploy is
unreachable by construction: dlt grants a brand-new table a one-time schema
grace, so the real-dlt round-trip test above executed the genuine dependency and
*still* could not see it. For any change to a write disposition, schema
contract, primary or merge key, partition scheme, or file layout, the tooth is a
test that runs the **old** contract first and the new one second against the
same destination. Nothing else reaches that state, and it is reachable exactly
once per environment.

## What it refuses to score

Absence of a failure signal is never evidence of a pass. Three cases refuse:

- **A red baseline** — every mutant would look killed. Exits 2.
- **An anchor matching zero or more than one place** — ambiguous means the spec
  never said which site it meant.
- **A run that named no failing test.** A mutant that will not compile, or a
  command aborting before collection (unrecognised flag, missing plugin), exits
  non-zero with no `FAILED` line — the harness broke, no assertion caught
  anything. Python mutants are compile-checked first, catching it at the source.
- **A mutant that declares no `oracle`.** Only the author knows whether the
  predicted test drives the real dependency or a stand-in; guessing `real` on
  their behalf would manufacture a guarantee nobody checked. Exits 2.

## Safety

Files are edited in place and restored from saved bytes in a `finally` — never
by `git checkout`, which would destroy uncommitted work. The only files it
deletes are `__pycache__` entries for the modules it mutates: regenerable
bytecode, never source. Commit before running
anyway: `git status` is then an independent check that everything was restored.

## Related

- `adversarial-review` — where blind teeth actually surface. A green matrix
  never reports one, so point a hostile pass at the tests, not just the code.
- `warehouse-sql-test-harness` — the same mirror, one domain over: asserting on
  SQL text rather than executing it. Reach for it when the dependency is a
  warehouse.
- `drain-queue` — gates the spec before a build; this gates the tests after.
