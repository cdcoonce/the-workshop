# Add The Workshop Hook — Open Questions

Deferred design questions from building the existing core hooks
(`verify-tests-before-stop`, the `snapshot-subagent-start`/
`verify-subagent-evidence` pair, `audit-config-change`). Revisit these when
they stop being hypothetical.

## Shared helper extraction

Worth extracting the duplicated `git_dir()`/`working_tree_signature()`/
`head_sha()` helpers (identical across `verify-tests-before-stop.py`,
`snapshot-subagent-start.py`, `verify-subagent-evidence.py`) into a shared
module once a 4th hook needs them? Currently duplicated on purpose to keep
each hook file self-contained per the repo's existing convention (SKILL.md
step 2) — revisit if that convention itself changes.

## Cross-tool portability is unverified

No CoCo/Codex test harness exists in this repo yet — portability is
currently an inference from a prior bug fix (`aaf2229`), not something
re-verified per new hook.
