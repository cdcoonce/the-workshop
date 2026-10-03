# Order and preserve session notebook updates

The October 3 memory audit demonstrated concurrent distillation exposure and
age-only deletion. It did not establish that a historical fact was lost.
This local slice is authorized by the request to work through the audit fixes.

Bounded implementation:

- Serialize each session's workers with an OS-released advisory lock, using
  stdlib facilities on POSIX and Windows. Read notebook and transcript after
  acquiring the lock; coalesce successfully processed identical snapshots.
- Replace completed notebook output atomically, rejecting results when an
  external writer changed the base content during model execution.
- Retain other sessions' old notebooks and log that promotion/archive remains
  necessary. Age alone does not establish durable capture.
- Create stubs exclusively and validate session identities with the same
  shared predicate used by the startup reader.

Tests use isolated temporary Vaults, real worker processes for contention, and
fake distillation only. Cover out-of-order workers, duplicate snapshots,
external edits, replacement failure, retained old notes, and safe stub creation.
No live hook, model, sync, commit, plugin-cache edit, or registration change.

Activation remains a source release/plugin update after review. The root agent
owns version/stamp changes. Explicit promotion/archive policy is outside this
slice; retained notes can accumulate until that policy is implemented.

Implemented and verified locally:

- A controlled two-process test first reproduced the later turn being
  overwritten by a slow earlier worker; it passes with per-session locking.
- Duplicate-snapshot, replace-failure/retry, external-edit/retry, old-note
  retention, concurrent stub creation, and invalid identity tests each failed
  before their corresponding fix and now pass.
- The focused notebook/startup group passes **51 tests**. Model boundaries are
  mocked; process contention is real. The root agent owns the full repository
  gate and independent review.

Limitations: POSIX locking was exercised on macOS; the Windows `msvcrt` branch
requires Windows execution. Advisory locks serialize cooperating distillers;
the immediate base-content check protects edits made during model execution,
but is not an atomic compare-and-swap against arbitrary outside writers. A
crash after notebook replacement but before the success marker may repeat the
merge; it cannot falsely mark an unwritten snapshot successful. Sudden process
death may leave a hidden temporary file, while the existing notebook remains
whole. The existing latest-turn-only extraction does not become a full event
log, and no claim is made that historical loss was proven or recovered.
