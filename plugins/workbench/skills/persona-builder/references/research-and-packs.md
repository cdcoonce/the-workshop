# Phase 3 — Research + Knowledge Packs

Goal: modular, opinionated, cited knowledge packs the persona routes into on demand —
practitioner-grade, not survey summaries. This phase is **self-contained**: it uses
only WebSearch/WebFetch (or the harness equivalents) and its own procedure below. It
must not invoke any skill outside this plugin.

## Step 1 — Fan-out from the research brief

For each topic in the brief, run 3–5 searches from **different angles**: the
canonical theory, the strongest published critique of it, current practice at the
owner's seniority level, and recent developments if the topic is flagged
fast-moving. One angle per search; collect sources, don't synthesize yet.

## Step 2 — Adversarial verification

A claim is admitted only if it survives an explicit refutation attempt:

- Find the claim's strongest published criticism or known failure case.
- Check the claim's age against the topic's speed (a 2004 usability heuristic ages
  differently than a 2024 AI-product pattern).
- Two independent sources minimum for anything stated as consensus; one primary
  source is acceptable for anything stated as an attributed opinion.

Claims that fail become either **contested entries** (kept, marked contested, both
sides cited) or are dropped. Never silently keep a weakened claim.

## Step 3 — Curation into packs

One pack per topic, written in the field's own vocabulary register (from the brief).

**Per-heuristic checklist gate** — every entry must state ALL of:

1. **The claim, as an opinion** — "Prefer X over Y when Z", not "some practitioners
   believe…".
2. **When it applies** — the conditions that make it the right call.
3. **When it fails or is contested** — the boundary conditions, the strongest
   counter-position, or the named critic. _An entry missing this line is rejected;
   knowing where a heuristic breaks is what separates practitioner from summary._
4. **Source** — citation with link.
5. **Date** — source date and the pack's researched-on date.

Pack header carries: topic, researched-on date, staleness threshold (months; short
for fast-moving topics), and a 3–5 line "load me when…" routing hint.

## Step 4 — Cheat sheet + router

- **Cheat sheet** — one page, always loaded with the persona: the 10–15 heuristics
  the owner will need in most conversations, one line each, pack-linked.
- **Router** — one line per pack in the persona's entry point: what's inside and
  when to load it. The persona loads packs on demand, never all at once. This is
  the progressive-discovery system; keep the router honest when packs change.

## Refresh path

The persona nudges when a pack passes its staleness threshold ("my agentic-UX pack
is 9 months old — want a refresh?"). A refresh re-runs Steps 1–3 **for that pack
only** and delivers the diff through the Phase 6 channel (PR or patch bundle).
Curation edits from the previous version are preserved unless their claims failed
re-verification.
