# Pre-registration — terse lens contract A/B

Registered 2026-09-21, before any arm ran. Charles Coonce, driven by the
2026-09-21 Claude Code session that adopted Superpowers 6's edit-level
findings (#905, #907). This experiment tests the one claim that was held for
measurement: a terser reviewer contract cuts reviewer output substantially
(Superpowers 6 reports 41%) while preserving verdict accuracy.

## Question

Does compressing the multi-lens PR review contract (the worked-example
prompts in `plugins/workbench/skills/adversarial-review/references/pr-lens-review.md`)
reduce reviewer output volume without losing defect detection?

## Fixture

The merged diff of the-workshop PR #896 (base `c030bed^`), doctored with five
injected defects spanning the three lens domains — ground truth and matching
rules in `fixture/defects.json`, frozen diff in `fixture/diff.patch`, binding
spec (the PR body, verbatim) in `fixture/spec.md`. Fingerprint command,
run before arm A, between arms, and after the bracket, captures recorded in
`results/results.md`:

    shasum -a 256 fixture/diff.patch fixture/spec.md fixture/defects.json contracts/full.md contracts/terse.md

## Arms

- **A — full contract** (`contracts/full.md`): the current pr-lens-review.md
  worked-example prompts, with the domain lens written for this change per the
  skill, plus a JSON output envelope identical in both arms.
- **B — terse contract** (`contracts/terse.md`): same three lens scopes and
  the same JSON envelope, compressed language (~40% of A's contract length).

Each arm execution dispatches 3 lenses x 2 replicates = 6 Sonnet subagents
whose prompts are exactly the contract assembly described at the top of each
contract file; each subagent's only tool use is reading the two frozen,
fingerprinted fixture files (identical inputs across arms and replicates),
after which it works tool-free. Execution order: A, then B, then A again (bracket).
18 subagents total. Raw final replies are saved verbatim under
`results/raw/{a,b,a2}/<lens>-r<rep>.txt` before any scoring runs.

## Metrics

1. **Output volume (benefit; harness `run`-equivalent via `analyze`).** One
   case per (lens, rep), n=6 per arm. Score = negative character count of the
   lens's final reply, so the paired delta b-a is the savings. Verdict rule
   (measure-output.toml): PASS iff the one-sided lower confidence bound of the
   mean paired savings exceeds 0 at alpha 0.05.
2. **Detection (guard; `analyze`).** One case per (defect, rep), n=10.
   Score 1.0 when any finding pooled across that rep's three lenses matches
   the defect under `fixture/defects.json`'s mechanical rule, else 0.0.

Scoring is mechanical via the committed `score_arm.py`. Manual adjudication
of a matcher miss is permitted only as a labeled secondary note in the
write-up, quoting the finding verbatim; it never changes the primary
mechanical result.

## Decision rule

Adopt the terse contract into pr-lens-review.md only if ALL of:

1. Output verdict PASS (ci_lower of savings > 0), and mean reduction >= 20%
   of arm A's mean output volume.
2. No detection regression: for every defect, if arm A detects it in a
   majority of replicates (first A capture), arm B also detects it in a
   majority of replicates.
3. Neither analyze run is VOID.

Any other outcome: keep the full contract; record the result either way.
A non-significant token result at this n is a verdict to report with its MDE,
not a null to explain away.

## Pre-declared deviation from harness `run`

The nested `claude -p` CLI cannot authenticate from this session (OAuth
session expired; interactive login unavailable), so the arms are dispatched
as Claude Code subagents by the driving session rather than by
`paired_ab.py run` executing a shell command. Consequences, accepted up
front: `analyze` computes the statistics from the saved case files (prereg
age still enforced); fixture fingerprint captures are run manually at the
A/B/A2 boundaries and recorded in the write-up rather than by the harness;
the TOML `cmd` fields record the scorer, not a dispatcher; output volume is
measured in characters of the final reply because API token counts are not
observable for subagents (thinking tokens are not captured — this measures
the deliverable the conductor must read, which is the cost the 41% claim is
about).

## Bracket tolerances

- Output metric: |mean_A - mean_A2| <= 1200 chars. The bracket guards fixture
  or protocol drift, not sampling noise; LLM output length varies run to run.
- Detection metric: |mean_A - mean_A2| <= 0.2 (one defect-rep flip = 0.1).

## Scope limits

One fixture, one repo, Sonnet only; lenses read exactly the two frozen
fixture files and nothing else (every fact needed is in SPEC and DIFF; the
new files' full content is visible in the diff). The result licenses a decision about this contract pair for
pr-lens-review.md's worked-example prompts, not a general claim about terse
prompts. Temperature is not controllable for subagents; replicates carry the
run-to-run variance.
