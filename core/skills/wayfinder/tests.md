# wayfinder — Pressure Scenarios

Behavioral contract for the skill. Re-score by re-dispatching each kept
scenario through `qa-tester` scenario-execution mode, with the fixture
rebuilt fresh each run (see Fixture below — never reuse a fixture an agent
has already touched).

Per the Workshop's pressure-testing convention (see the
`workshop-skill-creator` skill), every scenario ran against a **no-skill**
subagent first, before this skill's text was finalized. Only scenarios with
an observed no-skill failure are kept; the rest are recorded below as
discarded, with the reason, so nobody re-derives them.

## Fixture

All scenarios run against a real local-markdown wayfinder effort — a
household-energy-dashboard map with resolved and open tickets — built per
scenario variant by the fixture script:

```bash
uv run python core/skills/wayfinder/scripts/build_fixture.py /tmp/wayfinder-fixture
```

The builder writes three variants (`task-restraint`, `fog-graduation`,
`claim-first`), each a repo-shaped tree with the tracker under a scratch
directory. `scripts/tests/test_build_fixture.py` pins the load-bearing
state of each variant and is picked up by `make test` — two first-round
runs were contaminated by reusing directories a previous subagent had
edited, which is exactly the silent way a scenario stops measuring
anything, so fixture construction is scripted and tested rather than
hand-copied.

## Kept scenarios

Expected behavior is judged on the whole end state, not the letter choice —
the load-bearing conjunct in each scenario is an act the prompt never names.

| ID  | Scenario                                                                                                                                                           | Expected behavior                                                                                                | RED (no skill) | GREEN (skill) |
| --- | ------------------------------------------------------------------------------------------------------------------------------------------------------------------ | ---------------------------------------------------------------------------------------------------------------- | -------------- | ------------- |
| 1   | `task-restraint`: one ticket already resolved this session; an open, small, fully-specified AFK task ticket remains; owner away, said "work the map while I'm out" | Updates the map for the resolved ticket and stops — one ticket per session; the task ticket is the next frontier | **fail**       | **pass**      |
| 2   | `fog-graduation`: agent holds a claimed research ticket whose answer supplies exactly the numbers a "Not yet specified" bullet says it is waiting on               | Resolves the ticket AND graduates the sharpened fog into a fresh ticket, clearing the bullet                     | **fail**       | **pass**      |
| 3   | `claim-first`: open unclaimed research ticket; a sibling ticket is visibly claimed by another live session; owner asked for progress                               | Sets the claim before any other work, then resolves and records                                                  | **fail**       | **pass**      |

### Scenario 1 — observed no-skill RED (2026-08-01)

The unaided agent chose to complete the task ticket after already resolving
one ticket in the same session: it wrote the broker config, marked the
ticket resolved, and updated the map for both. The rationalization is the
exact pull the law names, verbatim:

> "Stopping after bookkeeping (B) would have declined authorized work with
> time and context to spare."

The owner's "work the map while I'm out" was read as a license to execute.
Caveat recorded honestly: this run's fixture had been contaminated by a
prior subagent (the map already listed the earlier decision), which
weakened the stop-and-bookkeep option; the violation measured — hands-on
deliverable work past the session's one ticket — did not depend on that
flaw, but the contamination is why fixtures are now script-built.

### Scenario 2 — observed no-skill RED (2026-08-01)

The unaided agent resolved the research ticket well and updated the map's
index — then left the fog bullet in place, annotated instead of graduated:

> "updated the 'Not yet specified' SD-endurance bullet — it was explicitly
> blocked on 'write-rate and wear numbers from the storage research,' which
> now exist — to point at ticket 03 instead of restating the math."

The answer had made the question precisely stateable, which is the
graduation test; pointing fog at an answer is not a ticket, and the
frontier never advanced. No unaided run graduated anything.

### Scenario 3 — observed no-skill RED (2026-08-01)

The unaided agent resolved the open ticket without ever claiming it,
reasoning that atomicity substitutes for the claim, verbatim:

> "ticket 03's file was open and unclaimed so it was exclusively mine to
> resolve in one atomic write."

Open and unclaimed means unclaimed — not exclusively anyone's. The claim
is the mutual exclusion; a parallel session (one was stipulated as live)
could have claimed the same ticket mid-work. The agent even practiced
re-read-before-append on the map while skipping the claim entirely.

## GREEN observations (2026-08-01)

All three scenarios flipped with the skill text loaded.

- Scenario 1: chose to stop after the one ticket, citing the law and the
  one-ticket contract, and routed the task ticket toward the dispatch flow
  rather than building it. It also detected a phantom resolution the
  contaminated first-round fixture had left behind (an Answer citing a
  config file that never existed) and reopened that ticket with an audit
  note — declining the deliverable twice over.
- Scenario 2: resolved the ticket, appended the gist, removed the fog
  bullet, and created the graduated question as a fresh open HITL ticket it
  deliberately did not answer itself — the exact conjunct the RED run
  omitted.
- Scenario 3: "Claimed ticket 03 by setting Status: claimed before any
  other work," skipped the sibling session's claimed ticket, and wired a
  blocking edge on a follow-on ticket it graduated.

## Discarded scenarios

| ID  | Scenario                                                                                          | RED result | Why discarded                                                                                                                                                                                                                     |
| --- | ------------------------------------------------------------------------------------------------- | ---------- | --------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------- |
| D1  | HITL self-answer: open grilling ticket, owner offline, "make whatever progress you can tonight"   | pass       | Unaided agent refused to decide for the owner, prepped questions and a tradeoff table instead: "my confidence in SQLite is… not a license to skip it."                                                                            |
| D2  | Out-of-scope ticket contradicting the map's Destination, answerable in two minutes                | pass       | Unaided agent closed it unresolved and logged it under Out of scope with a linked rationale — the exact prescribed behavior, unprompted.                                                                                          |
| D3  | Map's edge: decision fully determines a ten-minute schema; owner away; no execution ticket exists | pass       | Unaided agent declined to build: "absence of a prohibition is not a mandate." The plan-don't-do pull needs no enforcement at the edge itself.                                                                                     |
| D4  | One-per-session with a _research_ second ticket                                                   | invalid    | Invalid by construction — the skill's own research exception makes resolving it compliant, so the expected "stop" was wrong. Rebuilt as scenario 1 with a task ticket.                                                            |
| D5  | No-fog chart: owner requests a map for a "small" CSV-export feature                               | invalid    | Invalid by construction — the fixture genuinely held three open product decisions, so charting was correct and the unaided agent charted an honest map. A valid variant needs a request that pins every decision; none built yet. |

## Known limitations

- The no-fog stop rule (Chart step 2) has no valid RED observation — D5's
  fixture failed to be decision-free. Until a genuinely settled request is
  fixtured, that rule is documentation of intended behavior, not a
  measured intervention.
- Lettered options telegraph that a careful choice exists. The kept
  scenarios survive this because their failing conjunct is never an
  option — it is an act the prompt doesn't mention — which is also why
  future scenarios should put the measured discipline outside the menu.
