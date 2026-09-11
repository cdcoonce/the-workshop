# Agent Laws

Operational rules every dispatched agent in this fleet follows, regardless of role or plugin. Domain checklists — what a builder or reviewer actually does — stay in each agent's own `AGENT.md`; this file holds only the rules of conduct that apply across all of them. Append-mostly: add a law once here and every future agent inherits it, instead of re-teaching the same correction at every dispatch site by hand.

- Write the failing test first; a guard the suite survives when its defect is re-injected is vacuous.
- Pass `model` explicitly on any nested dispatch (omitting it does not pick a tier).
- Conventional commits; stage explicitly; never `git add .`; no attribution trailers.
- Branch from freshly fetched `origin/main`, never from a stale local ref.
- Report status honestly: failing tests are reported with output, skipped steps named as skipped.
