---
name: persona-builder
description: Build an installable, portable, self-tuning coach/sounding-board persona for a named owner. Interviews the owner (grill + audition rounds), deep-researches their field into curated knowledge packs, assembles a three-layer persona package as an advisor-* preset, and delivers it via PR. Use when the user wants to create a persona, coach, sounding board, advisor, or expert companion for themselves or someone else.
---

# Persona Builder

Turns "I want a coach for X" into an installable **advisor-`*` preset**: a persona with a
spec'd point of view, field-specific knowledge packs, structured memory, and a
self-tuning loop — portable across Claude Code, Codex, and Cortex Code via the
existing three-manifest build.

Not to be confused with `persona-*` presets (output-style layers). An **advisor
preset** is a knowledgeable counterpart with its own memory and stance; an output
style is a voice.

## Non-negotiable design rules

1. **Never ask an abstract question you can demonstrate instead.** Owners are bad at
   describing tone in the abstract and great at reacting to examples. Vague answer →
   generate contrasting concrete samples and infer the spec from their choices.
2. **Disagreement is a spec'd duty, not a vibe.** Every persona ships a stance
   contract: cite knowledge packs against the owner's reasoning when they conflict,
   take a position before asking questions, audition-calibrated pushback level. The
   failure mode this skill exists to prevent is the generic yes-man.
3. **The layer split is also the privacy boundary.** What lands in the repo is
   role-generic and shareable-grade. Personal calibration, memory, and preferences
   write only to the owner's local tuning/private layers and never enter a PR.
4. **No runtime dependencies outside the generated package.** The persona must run
   for an owner who has none of this repo's other plugins installed.

## Pipeline

Six phases, in order. Each phase's detail lives in its reference file — load it when
you reach that phase, not before.

### Phase 1 — Intake

Confirm with `AskUserQuestion`: who the persona is for (the owner should be at the
keyboard — if not, stop and schedule a session with them), the field, the owner's
role/seniority, target harness(es), and the owner's employer AI policy if work
topics are in scope. Output: an intake card.

### Phase 2 — Interview + Auditions

Structured grill for goals, scope, boundaries, and conversational contract, then
**audition rounds**: answer the owner's real scenario 2–3 contrasting ways
(Socratic / direct-advisor / devil's-advocate); their picks and edits become the
behavior spec. Also emits the research brief.
See [interview-and-auditions.md](references/interview-and-auditions.md).

### Phase 3 — Research + Knowledge Packs

Embedded fan-out research from the research brief (no external skill dependency),
adversarial verification, then curation into per-topic packs gated by the
per-heuristic checklist (claim / when-it-applies / when-it-fails / source / date)
plus a one-page always-loaded cheat sheet.
See [research-and-packs.md](references/research-and-packs.md).

### Phase 4 — Package Assembly

Assemble the three-layer package as an `advisor-<role>` preset: plugin-managed **base**
(behavior spec + packs + router), local **tuning** overlay (owner overrides, update-
safe), local **private** layer (mini-vault memory + preferences log). Includes the
retune/wrap-up feedback loop, staleness-nudged refresh, and the **owner guide**
(README.md) explaining how the persona works to the person who owns it.
See [package-format.md](references/package-format.md).

### Phase 5 — Behavior Eval

Turn audition scenarios plus mandatory edge scenarios (owner-is-wrong-needs-pushback,
vague ask, boundary-adjacent topic) into the package's `tests.md`; score the persona
against expected postures qa-tester-style. Failures block delivery.
See [package-format.md](references/package-format.md) § Scenario suite.

### Phase 6 — Delivery

Branch off fresh `origin/main`, add the preset, rebuild docs/dist, run the gate, and
open the PR. If the machine has no write access to this repo, fall back to emitting a
patch bundle for the maintainer. Then walk the owner through install on their
harness.
See [delivery-and-pr.md](references/delivery-and-pr.md).

## Definition of done

- Preset builds cleanly for all three platforms (`build_preset` emits Claude, Codex,
  and Cortex manifests) and passes the smoke test.
- `tests.md` scenario suite passes, including every mandatory edge scenario.
- Every knowledge-pack entry passes the checklist gate; every pack carries citations
  and a researched-on date.
- The repo copy contains nothing personal — verified before the PR is opened.
- The owner has the persona installed and has completed one real conversation with
  the retune loop exercised once.
