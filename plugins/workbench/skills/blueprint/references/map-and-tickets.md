# The Map and Its Tickets

Templates and rules for the shared map. First-party implementation of the
wayfinder pattern from Matt Pocock's skills repository
(`github.com/mattpocock/skills`, MIT) — rewritten for this ecosystem.

## The map body

The map is a single tracker issue labelled `blueprint:map` — the canonical
artifact. It is an **index, not a store**: a decision lives in exactly one
place (its ticket); the map only gists and links, never restates. Open tickets
are **not** listed in the body — they are open child issues, found by query.

```markdown
## Destination

<what reaching the end of this map looks like — the spec, decision, or change
this effort is finding its way to. One or two lines; every session orients to
it before choosing a ticket.>

## Notes

<domain; skills every session should consult; standing preferences for this
effort. The "Vault linkage: pending" marker lives here when set.>

## Decisions so far

- [<closed ticket title>](link) — <one-line gist of the answer>

## Not yet specified

<in-scope fog you cannot ticket yet; graduates as the frontier advances>

## Out of scope

<work consciously ruled beyond the destination; closed, never graduates>
```

**Append discipline.** Appending to Decisions-so-far is a read-modify-write on
the whole issue body. Re-read the body immediately before every append —
another session may have appended since the map was loaded.

**Refer by name.** In everything the human reads — narration, Decisions so
far — refer to maps and tickets by their _titles_, with the link wrapped
inside the name. A wall of bare issue numbers is illegible.

## Tickets

Each ticket is a child issue of the map. Its body is one question, sized to a
single agent session:

```markdown
## Question

<the decision or investigation this ticket resolves>
```

Each ticket carries one `blueprint:<type>` label. A session **claims** a
ticket by assigning it to the driving dev before any other work; an open,
unassigned ticket is unclaimed. Blocking uses the tracker's native dependency
edges (see the tracker doc), wired in a second pass after creation — issues
need ids before they can reference each other. The **frontier** is the open,
unblocked, unclaimed children.

The answer is not part of the body — it is recorded on resolution as a
comment. Assets created while resolving are linked from the ticket, never
pasted in.

## Ticket types — the HITL/AFK contract

Every ticket is either **HITL** — worked _with_ a human who speaks for
themselves — or **AFK**, driven by the agent alone. A HITL ticket only
resolves through that live exchange: the agent never answers its **own**
grilling questions or otherwise stands in for the human's side. An agent that
does has broken the contract, and the resolution is void.

- **Research** (AFK): surface a fact a decision waits on — documentation,
  third-party APIs, local knowledge bases. Resolved by background subagents
  fired in parallel at charting time. The charting session **reviews the
  findings before posting the resolution comment and closing** — never
  auto-close a research ticket on subagent completion; garbage findings must
  not become recorded decisions. Findings land in the resolution comment (and
  a vault reference note where the vault linkage below applies) — no
  throwaway research branches.
- **Prototype** (HITL): raise the fidelity of the discussion with a cheap,
  rough, concrete artifact to react to — an outline, a stub, disposable UI or
  logic built with normal tools. Link the artifact from the ticket. Use when
  "how should it look / behave" is the question.
- **Grilling** (HITL): the default. Interrogate via the grill-me skill (or
  the environment's grilling equivalent), one question at a time, until the
  decision is made.
- **Task** (HITL or AFK): real-world work that must happen before a
  _decision_ can be made — provisioning access, signing up for a service,
  moving data so its shape can be seen. The one type that _does_ rather than
  decides; it earns its place by unblocking a decision, not by delivering the
  destination. A task that turns out to be buildable repo work is not
  resolved in-map — hand it to the ecosystem's dispatch flow and record the
  filed issue's link in the resolution comment. Task resolutions record
  credential _locations_ and resulting facts, never secret values.

## Fog of war

The map is deliberately incomplete: don't chart what you can't yet see.
**Not yet specified** holds the dim view — suspected questions, areas to
revisit — everything in scope but not sharp enough to ticket.

**Fog or ticket?** The test is whether you can state the question precisely
_now_ — not whether you can answer it now. Ticket when the question is sharp
(even if blocked); fog when you can't phrase it that sharply yet. Don't
pre-slice fog into ticket-sized pieces — one patch may graduate into several
tickets, or none, once the frontier reaches it.

## Out of scope

The destination fixes the scope; work beyond it is out of scope — not fog.
It never graduates: it returns only if the destination is redrawn, and then
as a fresh effort. When an existing ticket turns out to sit past the
destination, **close it** and leave one line in Out of scope (gist, why,
link). It stays out of Decisions so far, which records only the route walked.

## Resolution completeness — the dispatch seam

The map's edge produces material, not filed build issues. A resolved
ticket's comment must be complete enough that the ecosystem's dispatch flow
can write a self-contained build issue — problem, evidence, proposed
behavior, acceptance criteria — from the comment alone, with the map and
ticket links as the evidence trail. If acceptance criteria can't be written
without reading more code, the decision isn't actually made — the ticket
isn't resolved.

## Vault linkage

Some machines carry a personal-knowledge vault: a directory with an
operating file and signature `brain/` and `perf/` workspaces, found by
walking up from the session's working directory. When present, a map gets a
vault-side anchor so daily workflows surface it:

- **Charting from inside the vault** (the common case — sessions launch there
  and work cross-repo): create a **map stub note** in the owning area
  (`personal/projects/` or `work/active/`) with the vault's standard
  frontmatter (date, ~150-char description, tags, `status: active`) linking
  the map URL, and add a one-line bullet for it in that area's index file
  under the exact existing heading the vault's session digest scrapes —
  "Active Projects" for work, "Side Projects" for personal. The headings are
  load-bearing names, scraped verbatim; if the expected heading is missing,
  **say so loudly and stop the linkage step — never invent a new heading**.
  School efforts get no stub note: link the map from the course hub note
  instead (the school digest scrapes only "Courses"), and keep any school
  map files under the school workspace.
- **Charting from elsewhere** (project repos are vault _siblings_, so the
  walk-up finds nothing): if the environment includes a vault, append this
  exact line to the map's Notes so the linkage is visibly owed, not silently
  skipped — `Vault linkage: pending — create the map stub from the next
vault session`. Any later session that loads the map with the vault in
  reach creates the stub and removes the line.
- **No vault in the environment**: skip this section entirely.

```markdown
---
date: <today>
description: "<what this map is finding its way to — one line>"
tags:
  - blueprint-map
status: active
---

# <Effort name> — blueprint map

Map: <map URL>

Decisions land on the map; this stub only anchors it in the vault.
```
