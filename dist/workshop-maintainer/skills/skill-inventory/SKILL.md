---
name: skill-inventory
description: >
  Audits agent skills and their package boundaries. Use when the user asks to
  inventory skills, find duplicate or overlapping skills, consolidate skills,
  group capabilities, reorganize presets, or decide where a skill belongs.
---

# Skill Inventory

Produce an evidence-backed inventory before changing skill ownership or packaging.

## Scope

Inspect both canonical source trees and generated or installed copies when present.
Treat generated distributions and plugin caches as consumers, not additional owners.
Do not modify skills, manifests, docs, or distributions unless the user separately
asks to apply the recommendations.

## Inventory

1. Locate every canonical `SKILL.md` and preset manifest.
2. Record each skill's slug, source owner, shipped presets, description, line count,
   references, scripts, tests, and obvious external dependencies.
3. Detect generated and installed copies by matching slug and content; report stale
   or divergent copies separately instead of counting them as unique skills.
4. Map trigger phrases and capability domains from frontmatter and the skill body.
5. Identify skills that are unshipped, multiply owned, or shipped by an unrelated preset.

Prefer repository parsers and build metadata over ad hoc path assumptions. Use `rg`
for discovery and parse JSON/YAML with structured tooling where available.

## Classification

Assign each canonical skill one primary group:

- daily developer workflow
- planning and product shaping
- codebase quality and review
- domain expertise
- repository maintenance
- vault operations
- routing or persona infrastructure

Flag these relationships explicitly:

- **Duplicate:** materially the same triggers and behavior.
- **Overlap:** shared triggers but meaningfully different outputs.
- **Sequence:** one skill should hand off to another.
- **Mispackaged:** ownership or distribution does not match its audience.
- **Too broad:** combines independently triggered capabilities.
- **Too narrow:** adds routing ambiguity without distinct behavior.

## Recommendations

For each finding, choose one action: keep, merge, split, rename, move, narrow triggers,
or remove from a preset. Distinguish canonical source ownership from which presets ship
the skill. Avoid moving files solely to make package membership convenient.

Rank recommendations by routing risk, user confusion, maintenance cost, and migration
blast radius. Preserve compatibility aliases only when installed users would otherwise
lose an established invocation.

## Output

Return:

1. Counts by source owner and shipped preset.
2. A compact skill-to-group table.
3. Duplicate, overlap, sequencing, and packaging findings with evidence.
4. A proposed package model and migration order.
5. Open decisions that require user judgment.

Include exact source paths and manifest references. Separate observed facts from
recommendations. If the inventory is large, write the full report only when asked;
otherwise keep it in conversation.
