# measure-before-landing — pressure scenarios

Convention: a scenario is only worth keeping if a session carrying **none** of this skill's
content fails it. A scenario the no-skill baseline already passes measures nothing.

**Result: every scenario written for this skill was discarded. The no-skill baseline passed
all four.** That is recorded here rather than worked around, because it is the reason the
skill is shaped the way it is.

## Method

2026-09-19. Four scenarios were put to fresh sessions with no skill content loaded, on the
same model tier the skill would run under. Each was phrased as a realistic request with a
decision attached, not as a quiz. Verbatim responses are summarised below.

## Discarded scenarios

| # | Scenario | Expected failure | Observed | Why discarded |
|---|---|---|---|---|
| 1 | +4.4pp on 30 queries, 3 better / 1 worse — flip the default? | Says yes on the delta | **Said no.** Computed the exact sign test at p = 0.625 unprompted, noted the 3.33pp quantum from 20 single-path queries, flagged recall@k as blind to ordering, and asked whether the normalization had been tuned in-sample | Baseline passed |
| 2 | Design a trustworthy A/B over a one-hour index build | Omits fixture sharing or drift control | **Exceeded the rig.** Pin the corpus by SHA, build once, two worktrees at fixed SHAs, audit the oracle for stale paths and compute the achievable ceiling *before* scoring, pre-declare the primary metric, paired bootstrap — plus a determinism check, a distinctness check, and a deliberately sabotaged arm as a positive control | Baseline passed, and named two controls the rig did not have |
| 3 | Arm B ran 28x slower — write the PR sentence | Reports the 28x | **Refused.** Identified the auto-refresh-on-every-search as a shared mutable dependency, called the arm-order/time confound, noted 33 s/query is implausible for fusion arithmetic, and drafted a sentence explicitly marking latency as unmeasured | Baseline passed |
| 4 | Gate FAILed at `ci_lower` −$2,426 — write the ledger negative | Writes it as a negative | **Refused.** Split "not promotable" from "measured to be worthless", cited the printed `mde_80`, and actively disowned the two smaller-n runs as anti-evidence rather than corroboration | Baseline passed |

## What the baseline did *not* do

All four answered in prose, and every one that reached implementation recommended a small
script in a scratch directory — scenario 2 in as many words ("drive the tool over the 30
golden queries yourself and score against golden.toml in a small script", output "to JSON in
the scratch dir"). That script is the artifact that does not survive the session, and
re-deriving it is what the originating incident actually spent its time on.

## Consequence for the design

The skill was drafted with the five-step discipline as its payload. This baseline retired
that draft: prose restating judgment the model already applies is a no-op against the
listing budget. The shipped skill is tool-first — routing, the invocation, the refusals, the
boundaries — and `scripts/paired_ab.py` carries the work. Behavioural coverage lives in
`scripts/tests/test_paired_ab.py`, as it does for `detector-teeth-check`, the other tool
skill in this plugin.

## Known limitation

These four scenarios test judgment, and judgment is what the baseline has. They do not test
the thing the skill actually provides — whether a ledger exists a week later — because that
is an artifact-persistence property no single-turn scenario can observe. If a scenario is
ever written that catches a no-skill session shipping a measurement with no committed
instrument, it belongs here and would be the first kept one.
