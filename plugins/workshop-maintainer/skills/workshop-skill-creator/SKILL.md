---
name: workshop-skill-creator
description: >
  Creates and revises skills owned by The Workshop repository. Use when the user
  asks to add, create, write, revise, or package a Workshop skill.
---

# Workshop Skill Creator

Own the complete Workshop skill change: design, source, ownership, tests,
distribution wiring, generated artifacts, and verification.

## Repository Guard

Run only in The Workshop repository. Verify `core/skills/`, `presets/`,
`scripts/build_preset.py`, and `scripts/build_docs.py` exist. Otherwise stop and
explain that this is not a generic skill-authoring workflow.

## Route the Request

- For benchmark-driven revision, invoke `improve-skill` and follow it.
- For creation or ordinary revision, continue below.
- For package reorganization or broad consolidation, run `skill-inventory` first.

Before every change, perform a targeted inventory: locate related trigger phrases,
adjacent capabilities, canonical ownership, shipped presets, and generated copies.
Generated `dist/` and installed cache copies are consumers, never edit targets.

## 1. Gather and Grill

Gather purpose, trigger phrases, output, boundaries, structure, and dependencies.
Invoke `grill-me` using [skill-grill-domains.md](references/skill-grill-domains.md).
Ask only questions repository evidence cannot answer. If structured questions are
unavailable, use the fallback format defined there.

## 2. Blueprint

Present the complete blueprint from [blueprint-template.md](references/blueprint-template.md),
including canonical source owner and every preset that should ship the skill. Obtain
user approval before editing. Ordinary revisions may use a concise diff-oriented
blueprint, but approval is still required.

## 3. Implement Test-First

Write the smallest failing repository test that proves ownership, package membership,
or build behavior before changing production source. Then create or revise only the
canonical skill directory:

- Universal capability: `core/skills/<slug>/`.
- Package-specific capability: `presets/<preset>/skills/<slug>/`.

Use progressive disclosure and keep `SKILL.md` below 100 lines. Wire preset manifests
explicitly; never copy source merely to make another preset ship it. For process skills,
apply [discipline-toolkit.md](references/discipline-toolkit.md) and complete the RED
baseline required by [pressure-testing.md](references/pressure-testing.md).

## 4. Review and Propagate

Apply every check in [quality-criteria.md](references/quality-criteria.md). Fix failures
before continuing. Then run, in order:

1. `make docs`
2. `make build`
3. `uv run python -m scripts.smoke_test <preset>` for every affected preset
4. `make test`

Repair source, wiring, generated artifacts, or tests until every gate passes. Never
report a partially propagated skill as complete.

## 5. Report

Report canonical files, package membership, generated outputs, and exact gate results.
