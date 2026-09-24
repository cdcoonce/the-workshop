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
