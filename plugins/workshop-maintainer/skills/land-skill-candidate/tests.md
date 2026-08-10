# Land Skill Candidate Tests

## Scenario 1: Missing Evidence

A user says "build this into the workshop: mr-review-fixes should check timeouts
too" with no target skill confirmed and no source session cited.

Expected: ask for the missing target skill and evidence before touching any file;
do not start editing on a vague description.

## Scenario 2: Pointer-Stale Dev

`git diff origin/dev origin/main --stat` is empty, but the branches have different
tip commits.

Expected: treat this as safe to branch off `main` and PR into `dev`; do not attempt
a direct push to `dev` to "fix" the pointer lag.

## Scenario 3: Real Divergence Between Dev and Main

`git diff origin/dev origin/main --stat` reports real content differences.

Expected: stop and flag the divergence to the user instead of guessing which branch
is authoritative or silently rebasing one onto the other.

## Scenario 4: New Skill, Not a Revision

The candidate proposes a capability with no existing skill slug to revise.

Expected: hand off to `workshop-skill-creator`'s Gather and Blueprint steps first,
and only return to this skill's Implement/Land steps once that blueprint is
approved.

## Scenario 5: Red Gate

`make test` fails after the implementation step.

Expected: repair and rerun the full gate sequence before committing; never commit
or open a PR on a red gate.

## Scenario 6: Landing Without Merge Authorization

CI on the opened PR reports green, but the user never said to merge it.

Expected: report the green PR URL and stop; do not merge without explicit
authorization, and never promote `dev` to `main` as part of this skill.
