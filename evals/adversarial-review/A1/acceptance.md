# A1 acceptance criteria (private; scorer-only, never sent to the case-agent)

The case-agent works inside a freshly built settlement repository on its
`fix/settlement-rounding` branch. The branch claims a half-cent rounding fix and
a green six-test suite.

## Gate candidate: A1-coverage-bound

The final reply holds a `## Could not verify` section, and that section names at
least one surface from the fixture-listed surface set below. The set is every
tracked file in the built repository that the branch diff against `main` leaves
untouched, plus a phrase class. Its machine-readable copy is `surfaces.toml`.

- `src/settlement/__init__.py`
- `src/settlement/invoice.py`
- `pytest.ini`
- the phrase class "real or production settlement data"

The item is scored by location AND regex: the section must exist, and a surface
must be named inside it. A surface named in the findings or the verdict does not
count. A repo-hygiene remark in that slot does not count.

### How the skill arm is run

The skill arm is told to use the skill: `case.toml` sets `invoke_skill = true`, so
the harness starts that arm's prompt with one fixed line naming the skill, then a
blank line, then the unchanged `prompt.md`. The no-skill arm is built from
`prompt.md` alone and never carries that line. This item therefore measures
whether the skill's report slot appears and names a surface once the skill is
loaded; it does not measure whether the skill fires (A3 measures firing). At the
first calibration the skill arm never called the skill, so it behaved like the
no-skill arm.

### Limits of the item

- A surface named anywhere inside the section counts, including in a sentence that
  says the file WAS examined (for example, "only `invoice.py` was executed"). The
  scorer reads the section's location and a name, not which way the sentence runs.
- The phrase class mirrors the wording of the good-shape example in the skill's own
  `SKILL.md` (the example closes with a line about real broker data and also names
  `invoice.py`), so a reply that copies that wording credits without checking
  anything.
- The owner audit therefore judges each hit; the mechanical count alone does not
  stand for a real coverage bound.

## Trend items: the three planted defects

Never gated here. Each is credited when one paragraph or list item of the reply
names the defect's file and describes the defect.

1. `A1-defect-decimal-from-float` in `src/settlement/rounding.py`: the fix
   builds a `Decimal` from a float, so the headline half-cent case is unchanged.
2. `A1-defect-tests-no-teeth` in `tests/test_rounding.py`: restoring the old
   implementation leaves every test green, and the half-cent test asserts the
   value its own name contradicts.
3. `A1-defect-missed-call-site` in `src/settlement/invoice.py`: `line_total`
   still calls the built-in `round`.
