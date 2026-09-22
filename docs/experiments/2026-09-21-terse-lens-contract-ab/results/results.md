# Results — terse lens contract A/B

Run 2026-09-21 → 2026-09-22 (arms crossed midnight UTC). Prereg committed at
`37b9f82` before any arm ran. 18 Sonnet subagents dispatched A → B → A2 per
the prereg; all 18 raw replies saved verbatim under `raw/` before scoring.

## Verdict: KEEP THE FULL CONTRACT

The pre-registered decision rule required output verdict PASS with >= 20%
mean reduction, plus no detection regression. The output verdict is **FAIL**;
the terse contract is not adopted. `pr-lens-review.md` is unchanged.

## Numbers (harness ledgers in this directory, `2026-09-22T16-17-34Z-*.json`)

**Output volume** (chars of reviewer final reply; score = -chars, n=6 paired
lens x rep cases):

- Arm A (full) mean: 3,588.8 chars · Arm B (terse) mean: 3,274.5 chars
- Mean paired savings: +314.3 chars (~8.8% of A) — **far from the 41% claim**
- Sign test: 3 of 6 pairs favored the FULL contract; p = 1.0
- One-sided 95% lower bound of savings: **-1,004.7** (rule: > 0) → FAIL
- MDE at n=6, sd=1,603: 1,920.9 chars (~54%) — only a huge effect was
  detectable, and the point estimate is small and sign-inconsistent
- Bracket: mean_A2 = 3,540.0, |ΔA| = 48.8 ≤ 1,200 tolerance → valid

**Detection** (injected-defect hit rate, n=10 paired defect x rep cases):

- Arm A: 9/10 · Arm B: 9/10 · mean delta 0.0 — identical patterns
  (D3:r1 missed in both; everything else 2/2 in both)
- Guard (no defect majority-detected by A and missed by B): **holds**
- Bracket: mean_A2 = 0.8, |ΔA| = 0.1 ≤ 0.2 tolerance → valid

**Fingerprint**: identical across all four captures
(`fingerprint-1.txt` … `fingerprint-4.txt`).

## Labeled secondary notes (per prereg; primary mechanical results unchanged)

1. **D3's arm-A r2 credit is a matcher artifact.** The mechanical rule
   credits D3 (weakened `>= 1` assertion, tests line 151) for arm A r2 via a
   test-veracity finding at line 148 that is actually a D1 consequence
   ("assert report[\"pushed\"] == 0 at line 148 fails (actual 1)…") landing
   inside D3's line window [139, 160]. The only genuine D3 catch in the whole
   experiment is arm B test_veracity r2: "`assert len(session) >= 1` …
   cannot fail … satisfied by construction … does not independently verify
   the 'collapse to exactly one commit' claim the way `== 1` would." The
   artifact is symmetric in the mechanical scoring and does not change the
   comparison; read D3's absolute rate as 1 genuine catch in 6 test-veracity
   runs.
2. **A2 domain-r1 parse error.** That reply embedded a Python `.replace()`
   call inside its findings JSON, so it scored zero findings mechanically
   (its text plainly describes D1 and D2). Consequence: A2's detection mean
   dropped to 0.8; the bracket stayed within tolerance, so no VOID. The
   parse-robustness of the JSON envelope is a real, incidental observation:
   1 of 18 replies was malformed.

## Interpretation

The Superpowers 6 finding (41% reviewer-output reduction from a terser
contract, verdict accuracy preserved) **did not replicate in this setting**,
and the likely reason is instructive: both arms share the structured
findings-only JSON output envelope that pr-lens-review.md already mandates
("Report ONLY defects… empty findings list is the expected answer… no
style"). Output volume here is driven by how many defects exist and how
concretely they are described — things the contract's verbosity does not
touch. The compression Superpowers 6 measured was presumably available
because their reviewers' output format still had prose to shed. Ours does
not: the output-shaping lever is already pulled in the shipped contract.

Detection parity at 9/10-vs-9/10 does replicate their "verdict accuracy
preserved" half — contract verbosity did not change what the lenses caught
on this fixture.

## Scope

One fixture (doctored PR #896 diff, five injected defects), one repo, Sonnet
lenses reading two frozen fingerprinted files, 2 replicates, character-count
output metric (API thinking tokens not observable). This licenses the
decision above for pr-lens-review.md's worked-example contract pair; it is
not a general claim about terse prompts.
