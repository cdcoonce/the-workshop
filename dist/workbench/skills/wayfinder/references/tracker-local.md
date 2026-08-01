# Wayfinding in Local Markdown

Use this tracker when the repo has no usable remote issue tracker — a
tracker-less clone, a private notes repository, or coursework. The map and
its tickets are plain markdown files, versioned with the repo.

## Where the files live

Default the effort directory to the repo's scratch or planning area, or ask
the user where planning files belong. One constraint is load-bearing for
vaults with an attention ledger that attributes by path: **coursework maps
live under the `school/` workspace** — a school map filed elsewhere is
counted as project work and hides the attention it consumes.

```text
<effort-dir>/
  map.md              # the map body (Destination / Notes / Decisions so far /
                      # Not yet specified / Out of scope)
  issues/
    01-<slug>.md      # one ticket per file, numbered from 01
    02-<slug>.md
```

## Ticket file format

```markdown
Type: grilling # research | prototype | grilling | task
Status: open # open | claimed | resolved
Blocked by: 01, 03 # omit the line when unblocked

## Question

<the decision or investigation this ticket resolves>

## Answer

<appended on resolution>
```

## Operations

- **Map**: the map file, same body template as
  [map-and-tickets.md](map-and-tickets.md).
- **Child ticket**: a new numbered file in the issues directory. Numbering is
  the map order; creation is idempotent by slug — skip a slug that already
  exists.
- **Blocking**: the `Blocked by:` line. A ticket is unblocked when every
  ticket it lists is `resolved` or `closed`.
- **Out of scope**: set `Status: closed` without an Answer and add the
  one-line entry to the map's Out of scope section — `closed` is never
  `resolved`, and it never returns to the frontier.
- **Frontier**: scan the issues directory for files that are `open`, have no
  unresolved blocker, and are unclaimed; lowest number wins.
- **Claim**: set `Status: claimed` and save — before any other work.
- **Resolve**: append the answer under the Answer heading, set
  `Status: resolved`, then add the gist line to the map file's Decisions so
  far.

Labels have no picker to collide with here, and there is no concurrent-editor
risk beyond the repo's own sync flow — resolve conflicts through it.
