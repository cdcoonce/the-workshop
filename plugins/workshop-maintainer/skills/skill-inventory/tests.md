# Skill Inventory Tests

## Scenario 1: Installed Copies

The repository holds each skill exactly once under `plugins/<plugin>/skills/`. Installed
plugin caches elsewhere on the machine hold their own copies at whatever version was last
installed. Inventory all skills and report the total.

Expected: count each repo skill once, then report installed-cache divergence separately.
Do not inflate the unique-skill count with cache copies.

## Scenario 2: Ownership Versus Distribution

A core skill ships in one preset but not another. Decide whether its source directory
must move into the shipping preset.

Expected: distinguish source ownership from distribution membership and recommend a move
only when the capability's maintenance ownership changes.

## Scenario 3: Similar Triggers

Two skills mention merge-request review. One prepares a reviewer packet; the other applies
review feedback and verifies fixes.

Expected: classify them as overlap or sequence, not duplicates, and recommend explicit
trigger boundaries.
