---
name: tdd
description: Test-driven development with red-green-refactor loop. Use when user wants to build features or fix bugs using TDD, mentions "red-green-refactor", wants integration tests, or asks for test-first development.
---

# Test-Driven Development

## The Iron Law

```
NO PRODUCTION CODE WITHOUT A FAILING TEST FIRST
```

Wrote code before the test existed and failed? **Delete it.** Not comment it out, not stash it "as reference", not keep it in a scratch file to peek at later — delete it, then write the test and let it fail before rewriting the implementation. No exceptions.

Satisfying the letter of this law while missing its spirit is still a violation — a test that can't fail, a test written after the code but narrated as if it came first, or a test so loose it would pass against any implementation all count as **not having done TDD**, even if a test file technically exists.

### Red Flags — Stop and Restart

Any of these means the Iron Law has already been broken:

- The test passed the first time you ran it — you never watched it fail
- "I'll add tests after this works" / "tests can come once the feature is done"
- Hedging language in your own reasoning — "this should work", "this will probably pass"
- Keeping the untested code around "just in case" instead of deleting it

See [discipline.md](discipline.md) for the excuse-to-reality table and the delete-means-delete loopholes it closes, and [core/docs/tdd.md](../../docs/tdd.md) for the full narrative walkthrough. This skill is the enforcement layer; that doc is the deep dive — they should never disagree.

## Philosophy

**Core principle**: Tests should verify behavior through public interfaces, not implementation details. Code can change entirely; tests shouldn't.

**Good tests** are integration-style: they exercise real code paths through public APIs and describe _what_ the system does, not _how_ it does it. **Bad tests** are coupled to implementation — they mock internal collaborators, test private methods, or verify through external means. The warning sign: your test breaks when you refactor, but behavior hasn't changed.

See [tests.md](tests.md) for examples and [mocking.md](mocking.md) for mocking guidelines.

## Anti-Pattern: Horizontal Slices

**DO NOT write all tests first, then all implementation.** Treating RED as "write all tests" and GREEN as "write all code" produces crap tests that test imagined behavior and go insensitive to real changes. Write vertical slices instead: one test → one implementation → repeat. See [discipline.md](discipline.md) for the full rationale and a worked example.

## Workflow

### 1. Planning

Before writing any code:

- [ ] Confirm with user what interface changes are needed
- [ ] Confirm with user which behaviors to test (prioritize)
- [ ] Identify opportunities for [deep modules](deep-modules.md) (small interface, deep implementation)
- [ ] Design interfaces for [testability](interface-design.md)
- [ ] List the behaviors to test (not implementation steps)
- [ ] Get user approval on the plan

**You can't test everything.** Confirm with the user exactly which behaviors matter most. Focus testing effort on critical paths and complex logic, not every possible edge case.

### 2. Tracer Bullet, Then Incremental Loop

Write ONE test that confirms ONE behavior, then repeat for each remaining behavior:

```
RED:   Write next test → fails
GREEN: Minimal code to pass → passes
```

The first cycle is your tracer bullet - it proves the path works end-to-end.

Rules:

- One test at a time
- Only enough code to pass current test
- Don't anticipate future tests
- Keep tests focused on observable behavior

### 3. Refactor

After all tests pass, look for [refactor candidates](refactoring.md):

- [ ] Extract duplication
- [ ] Deepen modules (move complexity behind simple interfaces)
- [ ] Apply SOLID principles where natural
- [ ] Consider what new code reveals about existing code
- [ ] Run tests after each refactor step

**Never refactor while RED.** Get to GREEN first.

## Checklist Per Cycle

```
[ ] Test describes behavior, not implementation
[ ] Test uses public interface only
[ ] Test would survive internal refactor
[ ] Code is minimal for this test
[ ] No speculative features added
```
