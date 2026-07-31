---
name: adversarial-review
description: >
  Attacks finished work by trying to disprove what it claims, and reports what
  survives with the evidence. Use when the user says "adversarial review",
  "attack this", "try to break this", "poke holes in this", "prove me wrong",
  "be skeptical", or wants a hostile pass over work that is claimed done —
  before declaring it finished, shipping it, merging it, or trusting a result.
---

# Adversarial Review

Ordinary review asks whether the work looks right — a question it was written to
answer comfortably. This asks: **what would make this wrong, and is it?**

## Iron Law

> NO CLAIM PASSES WITHOUT A DISPROOF ATTEMPT THAT COULD HAVE FAILED IT.

If nothing you ran or checked could have come back the other way, you have not
reviewed the claim — you have restated it.
[references/discipline.md](references/discipline.md) has the rationalizations that
route around this law and the red flags that mean it already broke.

**Read-only.** This skill reports; it does not fix. Edit the work and its evidence
moves underneath your own findings, so none of them can be audited. Fixing is a
separate invocation.

## 1. Build the claim ledger

Enumerate what the work asserts, from every surface that carries an assertion:
commit subjects and bodies, MR/PR descriptions, test names, docstrings, comments,
the summary an agent wrote when it called the work done. Implicit claims count —
a changed line asserts the old one was wrong, and a deleted branch asserts nothing
reached it.

Ledger it before attacking anything. Fewer rows than the change has moving parts
means the enumeration stopped early, not that the work claims little. See
[references/claim-taxonomy.md](references/claim-taxonomy.md).

## 2. Attack each claim

For every row, write the condition that would falsify it, then go try to produce
that condition. Prefer the disproof you can run over the one you can only argue.
[references/falsification-playbook.md](references/falsification-playbook.md) gives
the standard attacks per claim type — including the one that catches most: revert
the change and check whether the new tests actually go red.

Check the barrier before accepting it — "no credentials", "wrong runtime", "needs
prod" are assumptions more often than facts. Once it is real, three failed
attempts is the ceiling: record what you tried, grade it `PLAUSIBLE`, move on.

## 3. Grade on evidence, not conviction

| Verdict        | Bar                                                                                       |
| -------------- | ----------------------------------------------------------------------------------------- |
| `REFUTED`      | A reproducible trigger shows the claim is false: command run, `file:line`, breaking input |
| `CONFIRMED`    | A check that could have refuted it was run, and did not                                   |
| `PLAUSIBLE`    | A specific concrete argument, no reproduction. The ceiling for reasoning alone            |
| `UNVERIFIABLE` | Out of reach from here, and why                                                           |

Reasoning never reaches `REFUTED` or `CONFIRMED`. That boundary is the whole
defense against a review that sounds rigorous and is invented.

## 4. Report — every slot REQUIRED

```
## Claim ledger
| # | Claim | Source | Verdict | Evidence |

## Findings            REQUIRED — severity-ranked
For each: what breaks, the concrete trigger (inputs → wrong output), and file:line.

## Could not verify    REQUIRED — the slot this skill exists to force
What you did not examine, what you could not execute, and which ledger rows you
chose not to attack. Bound the review, not just the findings.

## Verdict
One line, scoped to what you actually covered.
```

**This is the slot that fails.** Baselines showed agents attack claims well, then
hand back a closed account with no boundary — so readers take the findings list as
complete. Get the shape right:

- ✅ "Only `rounding.py` was executed. `invoice.py` and the settlement writer were
  read but never run; no ledger row was attacked for either. Nothing was checked
  against real broker data."
- ❌ "Repo is back to committed state, only `__pycache__` is untracked." — hygiene,
  not scope, sitting where the boundary belongs.
- ❌ A reproduction limit filed under one finding and nowhere else. Not being able
  to run it is a fact about your coverage, not about that finding.

## Not this skill

- `plan-ceo-review` — challenges a plan **before** implementation. This runs after work claims to be done.
- `security-review` — threat model and attacker surface. Reach for it when a finding is a vulnerability.
- `daa-code-review` — style, lint, and quality signal. Cheaper, and not adversarial.
- `detector-teeth-check` — proves a suite would catch its bug. Recommend it when a ledger row is "the tests cover this"; do not run it from here.
