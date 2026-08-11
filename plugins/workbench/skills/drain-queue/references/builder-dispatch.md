# Worker dispatch prompt

One worker, one issue, one worktree. Fill every `<slot>`. The worker's final message is the
deliverable; it opens a pull request and stops.

The prompt is issue-specific throughout. A generic dispatch produces a generic diff — the
slots below are where the conductor's knowledge of the spec gets transferred, and skipping
one is how a worker "helpfully" edits a file the spec forbade.

## Slots

| Slot                | What makes it correct                                                                                                                                                                          |
| ------------------- | ---------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------- |
| `<N>` / `<repo>`    | Issue number and `owner/name`. The body is the spec; nothing is restated.                                                                                                                      |
| `<normative docs>`  | Design docs the builder must read in full before writing code. Omit if none.                                                                                                                   |
| `<pins>`            | The decisions the gate already settled: exact literal strings, field names, function signatures, ordering. Anything the cold read had to pin belongs here or the worker re-derives it wrongly. |
| `<allowed files>`   | Every file the worker may create or modify. Be exhaustive.                                                                                                                                     |
| `<forbidden files>` | The adjacent files an over-eager builder would improve. Name the specific temptation — a stale "until #N lands" comment is an invitation the worker must decline.                              |
| `<teeth mutations>` | One mutation per behavior the tests claim to protect, each with the test that must go red. Two to three is typical.                                                                            |
| `<gate command>`    | The repository's real lint and test commands, quoted exactly.                                                                                                                                  |
| `<freshness note>`  | If the integration branch moved since the spec was written, name what changed and which function is safe to build on. Omit if the branch is unchanged.                                         |
| `<count assertion>` | When the spec claims a specific number of call sites, state it and require the worker to stop and report on a mismatch rather than guess. Omit if not applicable.                              |

## Template

```text
You are implementing GitHub issue #<N> in <repo>. The issue body is your complete spec —
fetch it with `gh issue view <N> --repo <repo>` and build exactly what it says. It has passed
an adversarial cold-read gate; do not re-litigate the design. Before writing any code, read
<normative docs> IN FULL — it is normative for this build.

<freshness note>

Workspace setup (isolated worktree — the main checkout is shared, do not touch it):

    cd <main checkout>
    git fetch origin
    git worktree add <worktree path> -b <type>/<slug> origin/<integration-branch>
    cd <worktree path>
    <dependency sync command>

Do ALL work inside that worktree.

Method — test-driven, red first:
1. Write the tests first, covering every acceptance criterion in the issue. Run them and
   confirm they are red FOR THE RIGHT REASON (the module or behavior is absent, not a typo).
2. Implement per the issue's proposed behavior. Critical pins from the gate: <pins>
3. Full gate: <gate command> — all green.
4. Teeth checks, run separately with a restore between each: <teeth mutations>. Report the red
   output for every one.
   CAUTION: a mutation that is byte-for-byte the same length as the original may reuse stale
   bytecode. Either change the line length or clear the interpreter's cache before each run.
5. Re-run the full gate after any formatting.

Constraints:
- Touch ONLY: <allowed files>. Explicitly forbidden: <forbidden files>.
- Existing tests must stay green UNTOUCHED. Do not edit a test to make your build pass — if an
  existing test blocks you, stop and report it.
- <count assertion>
- Conventional commit, staged explicitly (never `git add .`). No co-author or generated-by
  attribution footers of any kind.
- Open a pull request against <integration-branch>. Body: two or three sentences plus
  `Closes #<N>`, and the teeth evidence from step 4.
- Do NOT merge the pull request. Do not comment on issues. Do not use artifact,
  task-spawning, or memory tools. Do not remove the worktree.

Return: pull request URL, files changed with line counts, full-gate result, and the red
evidence for every teeth check (test name plus assertion-error snippet each).
```

## Notes on the invariant lines

Four lines above are not adjustable and carry a scar each.

- **The worktree block.** An agent-level isolation flag is not a guarantee that two workers
  get separate trees. Scripting `git worktree add` into the prompt is what actually isolates.
- **The stale-bytecode caution.** An equal-length mutation can leave the interpreter running
  the pre-mutation bytecode, which reads either as a suite with no teeth or as a red baseline
  that was never real.
- **`git add .`.** A worker that stages everything sweeps in whatever else the tree picked up,
  and the allowlist stops being enforceable at review time.
- **Do NOT merge.** The independent review is the only check between a worker's own opinion of
  its work and the integration branch.
