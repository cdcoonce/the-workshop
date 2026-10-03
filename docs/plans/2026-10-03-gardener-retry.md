# Gardener failure and retry correctness

Date: 2026-10-03

Preserve the difference between failed Lane B work and a successful empty
review. Failure leaves the prior queue and durable progress watermarks alone,
releases only the current session's reservation from freshly read state, and
permits a later Stop to try again. Failed worker launch uses the same cleanup.
No automatic retry loop, new state fields, CLI changes, or lock system.

Use red/green tests for failed/malformed model results, failed Lane B state
handling, and failed launch cleanup. Verify successful-empty and deliberate
skip behavior remains completed. Tests use temporary state and mocked model,
process-launch, and machine-local inspection boundaries. Keep any Lane A repairs
already made; retry must not roll back note content or another session's state.

Existing cross-process state-write races, hard-kill recovery, successful queue
replacement, and the difference between Lane B's note cap and full-scope hash
recording remain outside this slice.

## Verification

Observed red-to-green regressions for timeout/malformed or structurally invalid
model output, failed Lane B queue/progress preservation, and failed launch
reservation cleanup. Tests introduce another session's state update during the
failure and prove only the failed session's reservation is removed. Positive
controls cover successful empty output, deliberate Lane B skip, retained Lane A
repairs, and retry only after a subsequent call.

The complete existing gardener test file passes: **91 passed**. Model calls and
worker launches in the new tests are mocked; Vault state is temporary, and
temporary Git fixtures disable hooks and signing. No live Vault state, caches,
model sessions, or external services were changed. The root agent owns the full
combined machinery/project gate after this slice is frozen.
