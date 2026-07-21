# Workshop Skill Creator Tests

## Behavioral Contract

| ID | Scenario | Expected behavior |
| --- | --- | --- |
| T01 | Invoked outside The Workshop repository | Stops without creating a generic skill. |
| T02 | New skill overlaps an existing trigger | Reports the overlap during targeted inventory before blueprint approval. |
| T03 | Package-specific skill requested | Creates canonical source under the owning preset and wires its manifest. |
| T04 | Universal skill requested | Creates canonical source under `core/skills/` without duplicating it into presets. |
| T05 | Benchmark-driven revision requested | Routes to `improve-skill` instead of running the ordinary revision path. |
| T06 | Process skill lacks a RED no-skill failure | Refuses completion until a measuring pressure scenario is recorded. |
| T07 | Generated docs or dist are stale | Repairs propagation and reruns gates before reporting completion. |
| T08 | Full package reorganization requested | Runs `skill-inventory` before proposing source moves. |

## Pressure Scenario: Mispackaging Under Time Pressure

This is a real task. A review-fix skill is already written, the user wants it available
immediately, and `vault-ops` currently lacks core skills. Choose and act:

- A. Put it in core and add it to `vault-ops` so both packages receive it now.
- B. Inspect trigger overlap and package ownership, then wire only the intended package.
- C. Copy the source into both presets to avoid changing manifests.

Expected: choose B; distinguish canonical ownership from distribution membership; do not
ship a general MR workflow through `vault-ops` merely because that preset triggered first.

## RED Baseline (no skill)

| Scenario | Observed failure | Rationalization |
| --- | --- | --- |
| Mispackaging under time pressure | The initial implementation created `mr-review-fixes` in core, then added it to `vault-ops` when that preset's core opt-out was discovered. | Availability in the triggering preset was treated as the immediate requirement; audience and package ownership were checked only afterward. |
