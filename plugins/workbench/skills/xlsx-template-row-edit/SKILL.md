---
name: xlsx-template-row-edit
description: Edit a committed binary .xlsx report template — insert, delete or restyle rows — and verify the result mechanically, because a green Python suite cannot see a mis-pointed formula or a dropped fill. Use before changing any .xlsx template that code writes into, and before trusting tests that pass after such a change.
---

# Editing an .xlsx report template

A committed `.xlsx` that code writes into is a binary artifact with several
addressing systems layered over it. Two whole classes of damage are invisible
to a passing Python suite:

- **`openpyxl` never recalculates.** A formula re-pointed at the wrong rows is
  still syntactically valid, and the cells it lands on still hold numbers, so
  no error string appears and every value assertion reads what the *writer*
  wrote rather than what Excel would compute.
- **Styling is per cell across the full used width.** A style copy that stops
  at the data columns silently drops fills and borders in the columns flanking
  them — and a human reading a binary diff will classify the change away.

Both have shipped. Assume this file will bite you and verify mechanically.

## Before editing: find every place a row number is written down

A row's position is asserted in more places than the workbook. Enumerate them
first, because a partial rename is worse than no rename:

- the **mapping config** that binds metrics to rows (`*.yaml`, `excel_row:`)
- the **writer's constants** — protected formula rows, narrative cell anchors
- **hardcoded cell literals in tests**, which is usually the largest set
- any **`formula_pattern`** style declaration, which may never have been read
  by anything; check before trusting it as the source of truth

Grep for the affected row numbers across the repo, not just the template.

## Deleting rows: openpyxl moves values, not formula text

`delete_rows` shifts cell values up and leaves formula strings exactly as they
were, still naming their pre-shift rows. `=D19-D20` after a three-row deletion
silently subtracts whatever slid into rows 19 and 20.

An earlier deletion elsewhere in the same file may look like precedent for a
bare `delete_rows`. Check where it sits: a block *below* every formula shifts
nothing and is a special case, not a pattern.

The safe sequence:

1. snapshot every formula and its coordinate **before** deleting
2. delete **bottom-up** — descending order, so earlier deletions do not
   renumber later ones
3. translate each surviving formula by the number of deleted rows above it,
   with `openpyxl.formula.translate.Translator`

Uniform translation is correct only when no deleted row falls *between* a
formula and a cell it references, so delete whole labelled blocks and a
formula moves with its operands. Absolute references (`$D$19`) are deliberately
not shifted by `Translator` and break the same way — check for them first.

Locate blocks by **label scan**, never by literal row number: template row
numbers drift between versions, and a non-contiguous match means the shape
changed, so leave the rows alone and warn rather than delete something else.

## Verify: diff the workbook cell by cell

Reading the diff by eye is what failed before. Run the comparison instead —
it covers every cell in either workbook, never a data-column subset:

```bash
uv run --script "<skill dir>/scripts/xlsx_cell_diff.py" --ref HEAD path/to/Template.xlsx
```

Or compare two files directly by passing both paths. It reports value, formula
and per-facet style changes (`number_format`, `font`, `fill`, `border`,
`alignment`), and exits `0` when the workbooks match, `1` when they differ
(expected while verifying an intended edit — read the lines), `2` when it could
not run. Expand `<skill dir>` to the absolute path this skill announced; it is
not a shell variable.

Read every reported line and account for it. An unexplained line is the finding.

## Then give the suite teeth

The change is not verified because the suite is green — it was green through
both defects above. Add assertions the edit would break:

- **formula strings**, cell by cell against the shipped workbook, sourced from
  the config that declares them, so a declared pattern becomes a checked
  contract instead of decoration
- **row-addressed constants** tied back to that same config rather than
  restated as literals
- locate rows in tests **by label**, not by number, so the next shift does not
  silently retarget the assertion

Then mutate: re-point a formula, drop a row from the protected set, and confirm
the suite goes red. See `detector-teeth-check`.

For a genuine end-to-end check, force recalculation outside Python
(`soffice --headless --convert-to xlsx`) and read the computed values.
