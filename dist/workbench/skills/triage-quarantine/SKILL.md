---
name: triage-quarantine
description: Diagnose why an autonomous agent run failed, quarantined, or was rejected before re-running anything. Use when an unattended agent slice quarantines, a nightly agent run exits nonzero, a background agent's work was rejected by a gate or reviewer, or the user asks why an automated run failed.
---

# Triage Quarantine

Diagnose a failed or quarantined autonomous-agent run from its artifacts before touching code or re-running anything. The reported failure category is a **hypothesis, not a fact** — machines mislabel their own failures constantly.

## Iron rule

**Read the log first.** Never re-run the failed step, re-run the test gate, or start editing code until you have read the run's own record of what happened. Re-running before reading destroys evidence and burns budget reproducing a symptom you could have read in ten seconds.

## Order of evidence

1. **The quarantine/failure log entry** — the system's own record for this run (e.g. a quarantine log, run journal, or driver log). Read the whole entry.
2. **Reviewer or gate notes, to the LAST line** — verdicts often come after the rationale; a note that reads as approval for nine lines can reject in the tenth. Never stop reading at the first judgment-shaped sentence.
3. **The target repo's state at run time** — dirty tree, wrong branch, missing remote, stale lockfile. Unattended runs usually die in preflight, in the _target_ repo, not in the orchestrator's code.
4. **The orchestrator's code** — last. Only suspect the harness after the run's own evidence is exhausted.

## Known lies

Failure categories that routinely mislabel the true cause — treat each label as the _starting_ hypothesis and verify:

| Reported category  | Frequently actually is                                    |
| ------------------ | --------------------------------------------------------- |
| no-op / empty diff | expired or broken credentials (agent couldn't even start) |
| gate failure       | a flaky test unrelated to the change                      |
| scope violation    | a file the acceptance criteria legitimately required      |
| review rejection   | a transport/network error dressed up as a verdict         |

Also: never trust a recorded `tests_passed`-style flag without the log lines of the actual test run behind it.

## Environment-specific checks

- **Nonzero exit from a scheduled run**: check the fleet/scheduler log for the _target repo_ before reading any orchestrator code — preflight aborts (dirty tree, wrong branch) dominate.
- **Headless auth**: probe the agent CLI's credentials in a clean environment (`env -i` the minimal invocation) before draining a queue manually — a session-inherited credential can mask a broken fleet credential, and vice versa.
- **Caught tracebacks**: a scary traceback that the runner caught and logged is often non-fatal residue; confirm it altered the outcome before chasing it.

## Output

State: the reported category, the verified actual cause, the evidence line(s) that proved it, and the smallest fix. If the cause is a lie-pattern above, say so explicitly — each confirmed mislabel is a candidate fix in the orchestrator's categorizer.
