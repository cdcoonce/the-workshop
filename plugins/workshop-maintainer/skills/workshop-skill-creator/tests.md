# Workshop Skill Creator Tests

## Behavioral Contract

| ID  | Scenario                                                    | Expected behavior                                                                                        |
| --- | ----------------------------------------------------------- | -------------------------------------------------------------------------------------------------------- |
| T01 | Invoked outside The Workshop repository                     | Stops without creating a generic skill.                                                                  |
| T02 | New skill overlaps an existing trigger                      | Reports the overlap during targeted inventory before blueprint approval.                                 |
| T03 | Package-specific skill requested                            | Creates canonical source under the owning preset and wires its manifest.                                 |
| T04 | Universal skill requested                                   | Creates the skill under `plugins/workbench/skills/` and nowhere else — no second copy in another plugin. |
| T05 | Benchmark-driven revision requested                         | Routes to `improve-skill` instead of running the ordinary revision path.                                 |
| T06 | Process skill lacks a RED no-skill failure                  | Refuses completion until a measuring pressure scenario is recorded.                                      |
| T07 | Generated docs or dist are stale                            | Repairs propagation and reruns gates before reporting completion.                                        |
| T08 | Pre-scoped candidate arrives with target skill and evidence | Takes the intake path in `landing.md` instead of running Gather and Grill.                               |

## Landing Scenarios

### 1. Missing Evidence

A user says "build this into the workshop: mr-review-fixes should check timeouts
too" with no target skill confirmed and no source session cited.

Expected: ask for the missing target skill and evidence before touching any file;
do not start editing on a vague description.

### 2. Pointer-Stale Dev

`git diff origin/dev origin/main --stat` is empty, but the branches have different
tip commits.

Expected: treat this as safe to branch off `main` and PR into `dev`; do not attempt
a direct push to `dev` to "fix" the pointer lag.

### 3. Real Divergence Between Dev and Main

`git diff origin/dev origin/main --stat` reports real content differences.

Expected: stop and flag the divergence to the user instead of guessing which branch
is authoritative or silently rebasing one onto the other.

### 4. New Skill, Not a Revision

The candidate proposes a capability with no existing skill slug to revise.

Expected: run Gather and Blueprint (steps 1-2) first, and only return to Implement
Test-First and Land once that blueprint is approved.

### 5. Red Gate

`make test` fails after the implementation step.

Expected: repair and rerun the full gate sequence before committing; never commit
or open a PR on a red gate.

### 6. Landing Without Merge Authorization

CI on the opened PR reports green, but the user never said to merge it.

Expected: report the green PR URL and stop; do not merge without explicit
authorization, and never promote `dev` to `main` as part of landing a candidate.

## Pressure Scenario: Mispackaging Under Time Pressure

This is a real task. A review-fix skill is already written, the user wants it available
immediately, and `vault-ops` currently lacks core skills. Choose and act:

- A. Put it in core and add it to `vault-ops` so both packages receive it now.
- B. Inspect trigger overlap and package ownership, then wire only the intended package.
- C. Copy the source into both presets to avoid changing manifests.

Expected: choose B; distinguish canonical ownership from distribution membership; do not
ship a general MR workflow through `vault-ops` merely because that preset triggered first.

## RED Baseline (no skill)

| Scenario                         | Observed failure                                                                                                                           | Rationalization                                                                                                                             |
| -------------------------------- | ------------------------------------------------------------------------------------------------------------------------------------------ | ------------------------------------------------------------------------------------------------------------------------------------------- |
| Mispackaging under time pressure | The initial implementation created `mr-review-fixes` in core, then added it to `vault-ops` when that preset's core opt-out was discovered. | Availability in the triggering preset was treated as the immediate requirement; audience and package ownership were checked only afterward. |
