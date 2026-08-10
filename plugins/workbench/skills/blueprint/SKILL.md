---
name: blueprint
description: >
  Charts an effort too big for one agent session as a shared map of decision
  tickets on the repo's issue tracker, worked one at a time until the way to
  the destination is clear. Use when the user explicitly invokes /blueprint,
  says "chart a map" or "work the map", names an existing map issue to
  continue, or asks to plan something too large and foggy to spec in one
  sitting. Planning only — it produces decisions, not build slices.
---

# Blueprint

A loose idea has arrived — too big for one session, wrapped in fog: the way
from here to the **destination** isn't visible yet. Blueprinting charts that
way as a shared map on the repo's issue tracker, then resolves its **decision
tickets** — questions whose resolution is a decision, not slices of a build —
until nothing is left to decide before someone goes and does the thing.

## The law

> PRODUCE DECISIONS, NOT DELIVERABLES.

The pull to just do the work is the signal you've reached the map's edge:
hand off, don't build. An effort may override this in its map Notes; absent
that, the law holds under every deadline and every "just ship it".

## Contracts (every session)

- **Map is an index.** Decisions live in tickets; the map gists and links.
  Load it low-res once; zoom into ticket bodies on demand.
- **Refer by name.** Titles wrapping links, never bare issue numbers.
- **Claim first.** Assign the ticket to the driving dev before any work —
  the assignee is the claim; concurrent sessions skip claimed tickets.
- **One ticket per session** — research tickets excepted (they run as
  parallel background subagents). Tickets are sized to one session. The
  user may direct continuation past one; checkpoint the session handoff
  between tickets when they do.
- **Create, then wire.** Tickets need ids before blocking edges can point at
  them; wiring is a second pass, idempotent, re-run on any resumed chart.
- **Fog or ticket?** Ticket when the question can be stated precisely now —
  even if blocked. Fog ("Not yet specified") when it can't. Out of scope
  never graduates.

Templates, ticket types, and the HITL/AFK contract:
[references/map-and-tickets.md](references/map-and-tickets.md). Tracker
operations: [references/tracker-github.md](references/tracker-github.md) when
the remote is GitHub,
[references/tracker-gitlab.md](references/tracker-gitlab.md) on GitLab,
[references/tracker-local.md](references/tracker-local.md) when no remote
tracker exists.

## Chart the map (user brings a loose idea)

1. **Name the destination** — grill until the end state is one or two lines.
   The destination fixes the scope, so it settles first.
2. **Map the frontier breadth-first** — grill across the whole space for the
   open decisions and the first takeable steps. **No fog surfaced? Stop** —
   the journey fits one session and needs no map; ask how to proceed.
3. Create the map (fog sketched into Not-yet-specified), create the tickets
   you can specify now, wire blocking edges in the second pass.
4. Fire the research subagents in parallel; review findings before any
   ticket resolves.
5. Apply the vault-linkage step from map-and-tickets.md where it applies.
6. Stop. Charting hand-resolves nothing.

## Work the map (user brings a map)

1. Load the map body — not every ticket.
2. Query the frontier. Four outcomes:
   - A takeable ticket → claim it, then resolve it.
   - **Zero open tickets** → the way is clear; run the dispatch handoff
     ([references/dispatch-handoff.md](references/dispatch-handoff.md)).
     This is success, not an error.
   - Open but **all blocked** → a wiring defect or dependency cycle — say
     so and show the cycle; never report the map as done.
   - Open but **all claimed** → report who holds the claims; reclaim only
     on the user's explicit say-so.
3. Resolve the one ticket — zoom into related tickets as needed; HITL types
   resolve only through live exchange with the user.
4. Record: answer as a resolution comment, close the ticket, append the gist
   to Decisions-so-far (re-read the map body first).
5. Graduate fog the answer sharpened into new tickets (create, then wire);
   close what it revealed as out of scope; update what it invalidated.

## Not this skill

- brainstorm — single-session shaping of a fuzzy idea into a committed
  direction; no persistent map, no frontier.
- grill-me — one interrogation; blueprint _invokes_ it inside tickets.
- write-a-prd / prd-to-plan — the way is already clear enough to spec or
  slice; blueprint is what runs while it isn't.
- Dispatch and slicing flows — consume the map's resolved decisions at its
  edge; blueprint never files build issues itself.
