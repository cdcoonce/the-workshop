"""Tests for the workbook cell-diff comparison logic.

Only the pure comparison is exercised: building a report from two snapshots.
Reading an actual ``.xlsx`` imports ``openpyxl`` lazily, so the module must
import without that dependency installed — the CI suite runs with only
pytest and ruff injected.

The cases are the two ERG defects this skill exists for. A green suite saw
neither: a variance formula re-pointed to pre-shift rows, and a frame-bar
fill dropped from the columns flanking the data range.
"""

import pytest

from xlsx_cell_diff import (
    CellSnapshot,
    diff_workbooks,
    format_report,
    is_blank,
)


def cell(value=None, **overrides) -> CellSnapshot:
    """A snapshot with neutral styling unless a field is overridden."""
    fields = {
        "value": value,
        "number_format": "General",
        "font": ("Calibri", 11.0, False, False, None),
        "fill": (None, None),
        "border": (None, None, None, None),
        "alignment": (None, None),
    }
    fields.update(overrides)
    return CellSnapshot(**fields)


class TestNoDifferences:
    def test_identical_workbooks_report_nothing(self):
        wb = {"Sheet1": {"A1": cell(1), "B2": cell("x")}}

        assert diff_workbooks(wb, wb) == []

    def test_empty_workbooks_are_equal(self):
        assert diff_workbooks({}, {}) == []


class TestValueAndFormula:
    def test_changed_value_is_reported(self):
        before = {"S": {"A1": cell(1)}}
        after = {"S": {"A1": cell(2)}}

        (diff,) = diff_workbooks(before, after)

        assert diff.sheet == "S"
        assert diff.coordinate == "A1"
        assert diff.kind == "value"
        assert diff.before == 1
        assert diff.after == 2

    def test_changed_formula_is_reported_as_a_formula_not_a_value(self):
        """The ERG defect: =D19-D20 kept its literal rows after a shift.

        Excel would compute a different number, but openpyxl never
        recalculates, so nothing downstream of the writer can see it.
        """
        before = {"Ops": {"D21": cell("=D19-D20")}}
        after = {"Ops": {"D21": cell("=D16-D17")}}

        (diff,) = diff_workbooks(before, after)

        assert diff.kind == "formula"
        assert diff.before == "=D19-D20"
        assert diff.after == "=D16-D17"

    def test_formula_replaced_by_a_literal_is_a_formula_change(self):
        before = {"S": {"A1": cell("=B1+C1")}}
        after = {"S": {"A1": cell(42)}}

        (diff,) = diff_workbooks(before, after)

        assert diff.kind == "formula"


class TestStyle:
    def test_dropped_fill_is_reported(self):
        """The frame-bar fill lost in the columns flanking the data range."""
        before = {"Ops": {"B17": cell(None, fill=("solid", "FF1F4E79"))}}
        after = {"Ops": {"B17": cell(None, fill=(None, None))}}

        (diff,) = diff_workbooks(before, after)

        assert diff.kind == "fill"

    @pytest.mark.parametrize(
        "field,before_value,after_value",
        [
            ("number_format", "General", "0.00%"),
            ("font", ("Calibri", 11.0, False, False, None),
                     ("Calibri", 11.0, True, False, None)),
            ("border", (None, None, None, None), ("thin", None, None, None)),
            ("alignment", (None, None), ("center", None)),
        ],
    )
    def test_each_style_facet_is_compared(self, field, before_value, after_value):
        before = {"S": {"A1": cell(1, **{field: before_value})}}
        after = {"S": {"A1": cell(1, **{field: after_value})}}

        (diff,) = diff_workbooks(before, after)

        assert diff.kind == field

    def test_one_cell_can_report_several_facets(self):
        before = {"S": {"A1": cell(1)}}
        after = {"S": {"A1": cell(2, number_format="0.00%")}}

        kinds = {d.kind for d in diff_workbooks(before, after)}

        assert kinds == {"value", "number_format"}


class TestCoverage:
    def test_a_column_outside_the_data_range_is_still_compared(self):
        """The specific miss: the edit touched C-P, the damage was in B and Q.

        Any diff that scans only the columns a writer populates reproduces
        the original defect.
        """
        before = {
            "Ops": {
                "B17": cell(None, fill=("solid", "FF1F4E79")),
                "D17": cell(1),
                "Q17": cell(None, fill=("solid", "FF1F4E79")),
            }
        }
        after = {
            "Ops": {
                "B17": cell(None, fill=(None, None)),
                "D17": cell(1),
                "Q17": cell(None, fill=(None, None)),
            }
        }

        coords = {d.coordinate for d in diff_workbooks(before, after)}

        assert coords == {"B17", "Q17"}

    def test_added_and_removed_cells_are_reported(self):
        before = {"S": {"A1": cell(1)}}
        after = {"S": {"A1": cell(1), "A2": cell(9)}}

        (added,) = diff_workbooks(before, after)
        assert added.kind == "added"
        assert added.coordinate == "A2"

        (removed,) = diff_workbooks(after, before)
        assert removed.kind == "removed"

    def test_sheet_added_and_removed_are_reported(self):
        before = {"S": {"A1": cell(1)}}
        after = {"S": {"A1": cell(1)}, "New": {"A1": cell(1)}}

        (diff,) = diff_workbooks(before, after)

        assert diff.kind == "sheet_added"
        assert diff.sheet == "New"

    def test_a_removed_sheet_does_not_also_report_every_cell(self):
        before = {"S": {"A1": cell(1)}, "Gone": {"A1": cell(1), "A2": cell(2)}}
        after = {"S": {"A1": cell(1)}}

        diffs = diff_workbooks(before, after)

        assert [d.kind for d in diffs] == ["sheet_removed"]


class TestOrdering:
    def test_differences_sort_by_sheet_then_row_then_column(self):
        before = {"B": {"A2": cell(1)}, "A": {"B1": cell(1), "A1": cell(1)}}
        after = {"B": {"A2": cell(9)}, "A": {"B1": cell(9), "A1": cell(9)}}

        located = [(d.sheet, d.coordinate) for d in diff_workbooks(before, after)]

        assert located == [("A", "A1"), ("A", "B1"), ("B", "A2")]


class TestReport:
    def test_report_names_every_difference(self):
        before = {"Ops": {"D21": cell("=D19-D20")}}
        after = {"Ops": {"D21": cell("=D16-D17")}}

        report = format_report(diff_workbooks(before, after))

        assert "Ops!D21" in report
        assert "formula" in report
        assert "=D19-D20" in report
        assert "=D16-D17" in report

    def test_report_on_no_differences_says_so(self):
        report = format_report([])

        assert "no differences" in report.lower()


class TestBlankScreening:
    """Which cells are worth snapshotting at all.

    The first version of this screen asked ``cell.value is None and
    cell.style == "Normal"``, which looks reasonable and is wrong: openpyxl's
    ``cell.style`` reports the *named* style, and a cell formatted directly
    keeps the name "Normal". Every styling-only cell was therefore dropped
    before comparison, so the tool missed a deleted frame-bar fill — the
    second of the two defects it exists to catch.
    """

    def test_a_truly_empty_cell_is_blank(self):
        assert is_blank(cell(None))

    def test_a_cell_with_a_value_is_not_blank(self):
        assert not is_blank(cell(0))
        assert not is_blank(cell(""))

    @pytest.mark.parametrize(
        "field,value",
        [
            ("fill", ("solid", "FF1F4E79")),
            ("border", ("thin", None, None, None)),
            ("alignment", ("center", None)),
            ("number_format", "0.00%"),
        ],
    )
    def test_an_empty_cell_carrying_formatting_is_not_blank(self, field, value):
        """A frame bar is an empty cell whose only content is its fill."""
        assert not is_blank(cell(None, **{field: value}))

    def test_font_alone_does_not_rescue_an_empty_cell(self):
        """Inherited font on an empty cell is noise, not content."""
        assert is_blank(cell(None, font=("Arial", 14.0, True, False, "FF000000")))
