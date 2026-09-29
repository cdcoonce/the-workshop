"""Pure coverage for `detect_renames`, driven by pasted `git diff -U0` text."""

from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from rename_detector import Rename, detect_renames  # noqa: E402

TWO_FILE_DIFF = """\
diff --git a/dbt_project.yml b/dbt_project.yml
--- a/dbt_project.yml
+++ b/dbt_project.yml
@@ -2 +2 @@
-  schema: LEGACY_SCHEMA
+  schema: LEGACY_SCHEMA_RAW
diff --git a/src/load.py b/src/load.py
--- a/src/load.py
+++ b/src/load.py
@@ -10 +10 @@
-    frame = read_curve_file(path)
+    frame = read_curveset(path)
"""


def test_each_file_reports_its_rename_with_old_new_and_path() -> None:
    assert detect_renames(TWO_FILE_DIFF) == [
        Rename(old="LEGACY_SCHEMA", new="LEGACY_SCHEMA_RAW", path="dbt_project.yml"),
        Rename(old="read_curve_file", new="read_curveset", path="src/load.py"),
    ]


def test_pairing_is_positional_so_an_extra_removed_line_is_not_a_rename() -> None:
    """Two lines removed, one added: only the first pair is compared."""
    diff = """\
--- a/jobs.py
+++ b/jobs.py
@@ -1,2 +1 @@
-run_daily_curves()
-archive_old_files()
+run_hourly_curves()
"""
    assert detect_renames(diff) == [
        Rename(old="run_daily_curves", new="run_hourly_curves", path="jobs.py"),
    ]


def test_two_renames_on_one_line_each_name_their_own_replacement() -> None:
    diff = """\
--- a/q.sql
+++ b/q.sql
@@ -1 +1 @@
-SELECT LEGACY_SCHEMA.a, other_config.b FROM x
+SELECT LEGACY_SCHEMA_RAW.a, updated_config.b FROM x
"""
    assert detect_renames(diff) == [
        Rename(old="LEGACY_SCHEMA", new="LEGACY_SCHEMA_RAW", path="q.sql"),
        Rename(old="other_config", new="updated_config", path="q.sql"),
    ]


def test_content_lines_that_look_like_file_headers_stay_content() -> None:
    """Inside a hunk, `--- x` is a removed `-- x` and `+++ x` an added `++ x`."""
    diff = """\
diff --git a/job.sql b/job.sql
--- a/job.sql
+++ b/job.sql
@@ -1,2 +1,2 @@
-USE SCHEMA LEGACY_SCHEMA;
--- nightly load
+USE SCHEMA LEGACY_SCHEMA_RAW;
+++ counter
"""
    assert detect_renames(diff) == [
        Rename(old="LEGACY_SCHEMA", new="LEGACY_SCHEMA_RAW", path="job.sql"),
    ]


def test_a_rename_seen_twice_is_reported_once() -> None:
    diff = """\
--- a/a.sql
+++ b/a.sql
@@ -1 +1 @@
-USE SCHEMA LEGACY_SCHEMA;
+USE SCHEMA LEGACY_SCHEMA_RAW;
--- a/b.sql
+++ b/b.sql
@@ -4 +4 @@
-FROM LEGACY_SCHEMA.prices
+FROM LEGACY_SCHEMA_RAW.prices
"""
    assert [r.old for r in detect_renames(diff)] == ["LEGACY_SCHEMA"]


def test_a_dotted_name_with_no_distinctive_part_is_chased_whole() -> None:
    """`pkg.module` has no part worth chasing alone, so the whole name is."""
    diff = """\
--- a/app.py
+++ b/app.py
@@ -1 +1 @@
-import pkg.module
+import pkg.engine
"""
    assert [r.old for r in detect_renames(diff)] == ["pkg.module"]


# The shape of a real Markdown-only rewrite (MR !45): a table row and a sentence
# reworded, dropping distinctive names that code and seeds still use.
PROSE_REWRITE_DIFF = """\
--- a/docs/reference/data-flow.md
+++ b/docs/reference/data-flow.md
@@ -10,3 +10,2 @@
-| `stg_onestream_budget_monthly` | SolarRECRev entities | view |
-Loads `HoldCo` rows with prior_month logic, see pytest.mark.snowflake.
-Old layout lives under _Legacy.
+| Budget rollup | entities | view |
+Rows load by prior window, see helpers.
"""


def test_a_rewritten_prose_table_and_sentence_is_not_a_rename() -> None:
    assert detect_renames(PROSE_REWRITE_DIFF) == []


def test_a_name_dropped_with_no_replacement_is_not_a_rename() -> None:
    """The line has a `+` partner, but `archive_files` has nothing taking its place."""
    diff = """\
--- a/jobs.py
+++ b/jobs.py
@@ -1 +1 @@
-run(load_curves, archive_files)
+run(load_curves)
"""
    assert detect_renames(diff) == []


def test_an_unequal_replace_block_pairs_nothing() -> None:
    """Accepted miss: `foo(old_name, x)` becoming `foo(new_name)` is a real rename,
    but a replace block whose two sides differ in length cannot be paired by
    position without crediting arbitrary names, so the hard gate leaves it."""
    diff = """\
--- a/app.py
+++ b/app.py
@@ -1 +1 @@
-foo(old_name, x)
+foo(new_name)
"""
    assert detect_renames(diff) == []


def test_a_case_only_change_is_not_a_rename() -> None:
    diff = """\
--- a/q.sql
+++ b/q.sql
@@ -1 +1 @@
-SELECT * FROM ONESTREAM_API_RAW_BUDGET
+SELECT * FROM onestream_api_raw_budget
"""
    assert detect_renames(diff) == []


def test_a_change_beyond_case_is_still_a_rename() -> None:
    """Control for the case rule: a new name that differs by more than case."""
    diff = """\
--- a/q.sql
+++ b/q.sql
@@ -1 +1 @@
-SELECT * FROM ONESTREAM_API_RAW_BUDGET
+SELECT * FROM onestream_api_raw_budget_v2
"""
    assert [(r.old, r.new) for r in detect_renames(diff)] == [
        ("ONESTREAM_API_RAW_BUDGET", "onestream_api_raw_budget_v2")
    ]


def test_a_multi_token_block_pairs_only_names_that_share_an_affix() -> None:
    """Two adjacent cells changed: the pair sharing a suffix is a rename, the
    unrelated pair beside it is a reworded cell."""
    diff = """\
--- a/docs/tables.md
+++ b/docs/tables.md
@@ -1 +1 @@
-| daily_curve_view | old_txt |
+| hourly_curve_view | new_zzz |
"""
    assert [(r.old, r.new) for r in detect_renames(diff)] == [
        ("daily_curve_view", "hourly_curve_view")
    ]
