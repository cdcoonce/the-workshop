---
name: measure-before-landing
description: >
  Run a two-arm comparison that leaves a committed ledger: prereg enforced,
  fixture fingerprinted, arms bracketed A-B-A, exact sign test and MDE
  reported. Use when you A/B, benchmark, baseline, or ask whether a change
  actually improved anything.
---

# measure-before-landing

Two arms, one score per case, a decision that turns on the difference. Run the bundled
harness instead of writing a comparison script, and the run leaves an artifact someone can
re-read.

**Iron law: the instrument is part of the deliverable.** A measurement whose apparatus was
never committed is a memory, not a result — nobody can re-derive it, re-base it, or audit
it, and the next person pays the whole cost again.

## Why a tool and not a checklist

The judgment here is not the scarce part. Measured on 2026-09-19: four scenarios covering
promote-on-a-thin-delta, designing the comparison, a confounded timing arm, and writing up a
failed gate were put to fresh sessions carrying none of this skill. **All four passed.** They
computed the sign test unprompted, caught the confound, refused to log an underpowered FAIL
as a negative result, and proposed pinning the corpus and adding a sabotage control.

What they also did — every one of them — was answer in prose and recommend a small script in
a scratch directory. That script is the thing that disappears. The gap this skill closes is
the artifact, not the advice, so its payload is the harness.

## How to run it

```bash
python3 "<skill base directory>/scripts/paired_ab.py" run --spec measure.toml
```

The absolute path matters. `cwd` is the target repository, which does not contain this
skill, so a bare `scripts/paired_ab.py` fails on a missing file — and in a repo that has its
own `scripts/` it fails on a directory that exists, which reads like a broken tool rather
than a wrong path. If the path is wrong, fix the path.

`run` fingerprints the fixture, executes arm A, arm B and (by default) arm A again, analyses
the pairing, and writes a JSON ledger. `analyze --a X.json --b Y.json` does the statistics
alone when the arms already ran. The spec is TOML: `prereg`, `out`, `label`, a `[cases]`
block naming the dotted path plus the key and score fields in each arm's JSON, `[arms.a]`
and `[arms.b]` with a `cmd`, an optional `[fixture] fingerprint` command, and an optional
`[bracket]`. Point both `cmd`s at the **shipped** entry point; an arm that reimplements the
thing measures the reimplementation.

It reports `mean_delta`, the exact two-sided sign test over the discordant cases, a one-sided
t lower bound, and `mde` — the minimum detectable effect for the mean paired delta at this n
and this observed dispersion. Read `mde` before calling any null a null. The statistics core
is ported from kaggriculture's `harness.stats`, whose docstrings carry three gating rules
that were tried and removed.

## What it refuses

Exit 2 is VOID, meaning the run cannot be trusted; exit 1 is a valid run whose registered
rule failed; exit 0 is a valid run that passed. It voids on a missing pre-registration, one
not older than the first arm (checked by commit time where the file is tracked, mtime
otherwise, and the ledger records which), a fixture fingerprint that moved between captures,
bracket arms that disagree beyond tolerance, case-key sets that differ between arms, and any
arm that exits nonzero or emits unparseable JSON. A non-significant result is a verdict, not
a void.

## Not this skill

- **`detector-teeth-check`** proves a *test* goes red when the defect is reinjected. This
  proves a *change* moved a metric.
- **`adversarial-review`** attacks a finished claim qualitatively. Run it on the write-up
  after this produces the ledger.
- **`stale-artifact-sweep`** re-verifies whether an old recorded claim still holds — "is
  this still true", not "which of these two is better".
- **`tdd`** governs the change. This governs the evidence that the change was worth landing.
