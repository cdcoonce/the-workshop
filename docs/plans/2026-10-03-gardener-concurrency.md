# Gardener concurrency and killed-worker recovery

Date: 2026-10-03

Use one nonblocking OS advisory mutex per Vault to serialize producer scope
selection, Lane A/B work, queue publication, and completion state. The lock file
has a stable inode and is never unlinked. Busy work remains eligible for a later
Stop; the OS releases ownership when a process is killed.

Stop dispatch no longer writes an in-flight session into completion history.
Workers recheck completion under the mutex. A private completion-protocol marker
migrates existing state once by clearing only ambiguous debounce IDs; existing
queues, hashes, cursors, timestamps, and other history remain intact. Queue
publication precedes completion publication, with atomic replacement per file.

Apply-lease acquisition and release/state stamping use the same mutex. Failed
acquisition must stop `/garden` before queue editing, and must not release an
unacquired lease. No new CLI flags or model/permission policy changes.

Real-process tests use temporary Vaults and stub model/inspection boundaries to
cover competing workers, killed holders, publication kill windows, migration,
and producer/apply interoperability. Each scenario failed against the previous
implementation before the fix. Both gardener test files pass together (97 tests),
including launch failures and successful-empty Lane B responses. No live Vault,
model, hook, or installed runtime changes were used for verification.

The new process regressions are in
`plugins/workbench/machinery/tests/test_graph_gardener_concurrency.py`; existing
behavior and dispatch checks remain in `test_graph_gardener.py`. Run both with
the machinery environment's `python -B -m pytest -q`. Process locking was verified
on macOS; the Windows byte-lock branch has not been executed here.

Activation must allow older workers to finish first: older code does not honor
the new mutex. This does not isolate direct note edits, revise successful queue
replacement policy, solve Lane B's coverage cap, or alter existing apply-lease
expiry/ownership semantics. Two-file publication is retry-safe, not a database
transaction; process-kill recovery does not claim machine power-loss durability.
Kills before atomic replacement can leave harmless temporary files. No automatic
retry loop or expiry-based worker reservation is introduced: a later Stop retries
unfinished work. Serialized successful producers still replace the pending queue;
merging proposals from different runs remains a separate queue-policy decision.
