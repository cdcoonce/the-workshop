# The Dispatch Handoff

What to do when the map drains to zero open tickets. Blueprint produces
decisions; this is how those decisions leave the map and become buildable
work — the one step where the skill hands off rather than decides.

The law still holds here: **blueprint never files build issues itself.**
This procedure composes the _material_ a dispatch flow files from, and hands
it over. Where the ecosystem has no dispatch flow, the material is the
deliverable — give it to the user and stop.

## Preconditions

Run this only when the frontier query returns **zero open children**. All
blocked, all claimed, and a wiring defect are different outcomes with
different responses — see "Work the map" in [SKILL.md](../SKILL.md). A map
with open tickets is not done, however finished the decisions feel.

## 1. Read every resolution comment

Read the resolution comment on **every closed child**, including tickets
closed as out of scope — an out-of-scope closure is a boundary the epic must
respect, and re-filing work the map already ruled out is the cheapest
mistake available here. Read comments, not bodies: the body is the question,
the comment is the answer. Read the map body too, for Notes (standing
constraints for the whole effort) and Out of scope.

**The completeness test is falsifiable.** map-and-tickets.md requires each
resolution to be complete enough to write a build issue from the comment
alone. If acceptance criteria can't be written without opening the code, the
decision was never actually made — reopen that ticket and resolve it. Do not
paper over a thin resolution with code archaeology: that converts an unmade
decision into an implementation guess, and the guess arrives wearing a
decision's authority.

## 2. Compose ONE epic, not one issue per ticket

N resolved tickets do **not** become N build issues. Compose a single
self-contained epic and let the ecosystem's decomposer cut the DAG.

The map's ticket boundaries are _decision_ boundaries — sized to one session
of deciding, which bears no relationship to how the work slices. Filing
per-ticket ships the decision structure as the build structure and
guarantees dependency edges nobody drew.

The epic carries the four sections map-and-tickets.md holds resolutions to:

- **Problem** — what is wrong or missing and why it matters. Drawn from the
  destination, not from any one ticket.
- **Evidence** — the map link as the evidence trail, plus the specific
  resolutions establishing each claim, referred to by title with the link
  wrapped in the name. Never restate a decision's full reasoning; the ticket
  holds it, and a second copy drifts.
- **Proposed behavior** — the decided design, assembled across resolutions.
- **Acceptance criteria** — checkboxes, including a test criterion.

**Carry the falsifiable criterion.** If a resolution produced a test that
could declare the whole effort failed, it belongs in the acceptance criteria
verbatim. It is the most perishable thing on the map — it lives in one
resolution comment and nowhere else — and the build is where it stops being
free to state and starts being expensive to discover.

Whatever the map left in **Not yet specified** stays out. That is fog, not
scope; filing it invents the decisions the map declined to make.

## 3. Invert the label guard

The map and its tickets carry **only `blueprint:*` labels**, never
autonomous-picker vocabulary. **The epic inverts this**: it is the handoff
into the autonomous backlog, so it carries that vocabulary and no
`blueprint:*` label at all.

Backwards fails in both directions, and neither is loud. A picker-labelled
_ticket_ gets swept into a build pipeline mid-map. A `blueprint:*`-labelled
_epic_ lands in a backlog no picker scans — it reads as filed while nothing
will ever pick it up.

The dispatch flow owns the exact labels and the promotion decision. Default
to leaving promotion to the user: an epic entering an autonomous pipeline
spends real tokens, and a drained map is a poor moment to discover that.

## 4. Record the epic on the map, then close it

Append the filed epic to the map body — re-read it first, per the append
discipline — under Decisions so far or a short `## Dispatched` heading. Then
close the map.

An unrecorded epic is precisely the failure this step prevents: the map
reads as drained-but-abandoned, and the next session re-derives an epic that
already exists.

If the destination named filing the epic as its final clause, filing it is
what closes the map. If anything remains, leave the map open and say what.
