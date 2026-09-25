"""Tests for sim_diff.py — pure logic only; Snowflake is always faked.

Run from the scripts/ directory:
    uv run --with pytest --with ruff python -m pytest -q tests
"""

import hashlib
import json
import sys
from pathlib import Path

import pytest

SCRIPTS_DIR = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(SCRIPTS_DIR))

from sim_diff import (  # noqa: E402
    SpecError,
    classify_diff,
    extract_view_body,
    find_write_verbs,
    load_spec,
    main,
    mask_noncode,
    new_duplicate_keys,
    rewrite_refs,
)

FQN = "DEV_ANALYTICS_DB.REVENUE_WATERFALL.BUDGET_MONTHLY"
BASE_FQN = "DEV_RAW_DB.FUNDAMENTAL_CURVES.BUDGETS"


# ---------------------------------------------------------------- masking

def test_mask_blanks_line_comment_but_keeps_length():
    sql = "SELECT 1 -- DELETE me\nFROM t"
    masked = mask_noncode(sql)
    assert len(masked) == len(sql)
    assert "DELETE" not in masked
    assert "SELECT 1" in masked
    assert "FROM t" in masked


def test_mask_blanks_block_comment_and_string_literal():
    sql = "SELECT 'DROP TABLE x' /* TRUNCATE */ , col FROM t"
    masked = mask_noncode(sql)
    assert "DROP" not in masked
    assert "TRUNCATE" not in masked
    assert "col" in masked


def test_mask_handles_escaped_quote_in_string():
    sql = "SELECT 'it''s DELETE' , col FROM t"
    masked = mask_noncode(sql)
    assert "DELETE" not in masked
    assert "col" in masked


def test_mask_can_blank_double_quoted_identifiers():
    sql = 'SELECT "DELETE" FROM t'
    assert "DELETE" in mask_noncode(sql)
    assert "DELETE" not in mask_noncode(sql, mask_quoted_identifiers=True)


# ---------------------------------------------------------------- write-verb guard

def test_write_verbs_absent_in_plain_select():
    assert find_write_verbs("SELECT a, b FROM t WHERE x = 1") == []


def test_write_verbs_ignores_comments_strings_and_quoted_identifiers():
    sql = "SELECT 'DELETE', \"UPDATE\" -- DROP\nFROM t /* MERGE */"
    assert find_write_verbs(sql) == []


def test_write_verbs_catches_real_dml():
    verbs = find_write_verbs("WITH x AS (SELECT 1) DELETE FROM t")
    assert "DELETE" in verbs


def test_write_verbs_catches_ddl():
    assert "CREATE" in find_write_verbs("CREATE OR REPLACE VIEW v AS SELECT 1")


# ---------------------------------------------------------------- extract_view_body

DDL = (
    "create or replace view BUDGET_MONTHLY(\n"
    "\tYEAR_MONTH,\n\tSITE,\n\tCONTRACT,\n\tATTRIBUTE,\n\tVALUE\n"
    ") as\n"
    "WITH source AS (SELECT * FROM dev_raw_db.fundamental_curves.budgets)\n"
    "SELECT * FROM source;"
)


def test_extract_body_strips_header_column_list_and_semicolon():
    body = extract_view_body(DDL)
    assert body.startswith("WITH source AS")
    assert not body.rstrip().endswith(";")
    assert "create or replace" not in body.lower()


def test_extract_body_without_column_list():
    ddl = "create or replace view V as\nSELECT 1 AS x;"
    assert extract_view_body(ddl).strip() == "SELECT 1 AS x"


def test_extract_body_ignores_as_inside_comment():
    ddl = "create or replace view V(\n  a -- not as here\n) as\nSELECT 2 AS a;"
    assert extract_view_body(ddl).strip() == "SELECT 2 AS a"


def test_extract_body_raises_on_non_view_ddl():
    with pytest.raises(ValueError):
        extract_view_body("create table T (x int);")


# ---------------------------------------------------------------- rewrite_refs

def test_rewrite_replaces_unquoted_ref_case_insensitively():
    sql = f"SELECT * FROM {BASE_FQN.lower()} b JOIN x ON 1=1"
    out = rewrite_refs(sql, {BASE_FQN: "(SELECT 1)"})
    assert "(SELECT 1) b" in out
    assert BASE_FQN.lower() not in out


def test_rewrite_replaces_double_quoted_ref():
    sql = 'SELECT * FROM "DEV_RAW_DB"."FUNDAMENTAL_CURVES"."BUDGETS" b'
    out = rewrite_refs(sql, {BASE_FQN: "(SELECT 1)"})
    assert "(SELECT 1) b" in out


def test_rewrite_does_not_match_longer_name():
    sql = f"SELECT * FROM {BASE_FQN.lower()}_ext"
    out = rewrite_refs(sql, {BASE_FQN: "(SELECT 1)"})
    assert out == sql


def test_rewrite_leaves_comments_and_strings_alone():
    sql = (
        f"-- {BASE_FQN.lower()}\n"
        f"SELECT '{BASE_FQN.lower()}' AS s FROM {BASE_FQN.lower()}"
    )
    out = rewrite_refs(sql, {BASE_FQN: "(SELECT 1)"})
    assert out.splitlines()[0] == f"-- {BASE_FQN.lower()}"
    assert f"'{BASE_FQN.lower()}'" in out
    assert out.rstrip().endswith("(SELECT 1)")


def test_rewrite_chains_mappings_recursively():
    # variance reads BUDGET_MONTHLY; proposed BUDGET_MONTHLY reads BUDGETS,
    # which is shadow-patched. The patch must land inside the chained body.
    variance = f"SELECT * FROM {FQN.lower()}"
    proposed_budget = f"SELECT * FROM {BASE_FQN.lower()} WHERE v > 0"
    out = rewrite_refs(
        variance, {FQN: proposed_budget, BASE_FQN: "(SELECT 1 AS v)"}
    )
    assert "(SELECT 1 AS v)" in out
    assert FQN.lower() not in out


def test_rewrite_does_not_recurse_into_own_replacement():
    # A virtual-delete patch references the very table it replaces; the
    # reference inside the patch body must survive as the real table.
    patch = f"SELECT * FROM {BASE_FQN.lower()} WHERE keep = 1"
    sql = f"SELECT * FROM {BASE_FQN.lower()}"
    out = rewrite_refs(sql, {BASE_FQN: patch})
    assert out.count(BASE_FQN.lower()) == 1
    assert "keep = 1" in out


# ---------------------------------------------------------------- diff classification

K = 1  # one key column in these fixtures


def _diff(base, prop, rel_tol=1e-9):
    return classify_diff(base, prop, key_len=K, rel_tol=rel_tol)


def test_identical_rows_produce_empty_diff():
    rows = [("a", 1.0), ("b", 2.0)]
    d = _diff(rows, list(rows))
    assert (d.added, d.removed, d.changed, d.noise_count) == ([], [], [], 0)


def test_last_bit_float_drift_is_noise_not_change():
    base = [("a", 1_658_655.74)]
    prop = [("a", 1_658_655.74 * (1 + 1e-14))]
    d = _diff(base, prop)
    assert d.changed == []
    assert d.noise_count == 1


def test_real_relative_change_is_reported_with_residual():
    base = [("a", 1_658_655.74)]
    prop = [("a", 1_658_656.11)]  # the $0.37 class: ~2e-7 relative
    d = _diff(base, prop)
    assert len(d.changed) == 1
    assert d.noise_count == 0
    assert d.worst is not None and d.worst.rel > 1e-9


def test_added_and_removed_keys_bucket():
    d = _diff([("a", 1.0)], [("b", 1.0)])
    assert [r[0] for r in d.removed] == ["a"]
    assert [r[0] for r in d.added] == ["b"]


def test_null_versus_value_is_a_change_null_pair_is_equal():
    d = _diff([("a", None), ("b", None)], [("a", 1.0), ("b", None)])
    assert len(d.changed) == 1
    assert d.changed[0][0] == "a"


def test_near_zero_uses_absolute_floor():
    d = _diff([("a", 0.0), ("b", 0.0)], [("a", 1e-15), ("b", 0.1)])
    assert len(d.changed) == 1
    assert d.changed[0][0] == "b"
    assert d.noise_count == 1


def test_duplicate_keys_compare_as_multisets():
    base = [("a", 1.0), ("a", 2.0)]
    same = [("a", 2.0), ("a", 1.0)]
    assert _diff(base, same).changed == []
    moved = [("a", 1.0), ("a", 3.0)]
    assert len(_diff(base, moved).changed) == 1


def test_non_numeric_values_compare_exactly():
    d = _diff([("a", "x")], [("a", "y")])
    assert len(d.changed) == 1


# ---------------------------------------------------------------- duplicate-key gate

def test_new_duplicate_key_is_flagged_tolerated_old_one_is_not():
    base = [("a", 1.0), ("a", 2.0), ("b", 1.0)]
    prop = [("a", 1.0), ("a", 2.0), ("b", 1.0), ("b", 9.0)]
    assert new_duplicate_keys(base, prop, key_len=K) == [("b",)]


# ---------------------------------------------------------------- spec loading

def write_spec(tmp_path, spec):
    p = tmp_path / "spec.json"
    p.write_text(json.dumps(spec))
    return p


def minimal_spec(tmp_path):
    (tmp_path / "proposed.sql").write_text(
        f"create or replace view {FQN} as\nSELECT 1 AS k, 2.0 AS v;"
    )
    return {
        "views": [
            {"fqn": FQN, "proposed_sql": "proposed.sql", "key": ["K"],
             "value_columns": ["V"]}
        ]
    }


def test_load_spec_applies_defaults(tmp_path):
    spec = load_spec(write_spec(tmp_path, minimal_spec(tmp_path)))
    assert spec.rel_tol == 1e-9
    assert spec.env_prefix == "SNOWFLAKE_"


def test_load_spec_rejects_missing_key_columns(tmp_path):
    raw = minimal_spec(tmp_path)
    del raw["views"][0]["key"]
    with pytest.raises(SpecError, match="key"):
        load_spec(write_spec(tmp_path, raw))


def test_load_spec_rejects_absent_proposed_file(tmp_path):
    raw = minimal_spec(tmp_path)
    raw["views"][0]["proposed_sql"] = "nope.sql"
    with pytest.raises(SpecError, match="nope.sql"):
        load_spec(write_spec(tmp_path, raw))


def test_load_spec_rejects_nothing_to_simulate(tmp_path):
    raw = minimal_spec(tmp_path)
    del raw["views"][0]["proposed_sql"]
    with pytest.raises(SpecError, match="simulate"):
        load_spec(write_spec(tmp_path, raw))


# ---------------------------------------------------------------- end-to-end (fake warehouse)

LIVE_DDL = (
    f"create or replace view {FQN.split('.')[-1]}(\n\tK,\n\tV\n) as\n"
    "SELECT 1 AS k, 2.0 AS v;"
)


class FakeWarehouse:
    """Answers GET_DDL, baseline, simulation, and check queries."""

    def __init__(self, ddl=LIVE_DDL, baseline=None, simulated=None, checks=None):
        self.ddl = ddl
        self.baseline = baseline if baseline is not None else [(1, 2.0)]
        self.simulated = simulated if simulated is not None else [(1, 2.0)]
        self.checks = checks if checks is not None else []
        self.queries = []

    def __call__(self, sql):
        self.queries.append(sql)
        low = sql.lower()
        if "get_ddl" in low:
            return [(self.ddl,)]
        if "/*sim_diff:check*/" in low:
            return list(self.checks)
        if "/*sim_diff:simulated*/" in low:
            return list(self.simulated)
        return list(self.baseline)


def run_main(tmp_path, raw_spec, warehouse):
    spec_path = write_spec(tmp_path, raw_spec)
    code = main([str(spec_path)], run_query=warehouse)
    out_dir = tmp_path / "sim_diff_out"
    evidence = None
    ev = out_dir / "evidence.json"
    if ev.exists():
        evidence = json.loads(ev.read_text())
    return code, out_dir, evidence


def test_clean_run_exits_zero_and_writes_evidence_and_worksheet(tmp_path):
    wh = FakeWarehouse(simulated=[(1, 2.0 * (1 + 1e-14))])
    code, out_dir, evidence = run_main(tmp_path, minimal_spec(tmp_path), wh)
    assert code == 0
    view = evidence["views"][0]
    assert view["ddl_sha256"] == hashlib.sha256(LIVE_DDL.encode()).hexdigest()
    assert view["buckets"] == {"added": 0, "removed": 0, "changed": 0, "noise": 1}
    worksheet = (out_dir / "worksheet_1.sql").read_text()
    assert view["ddl_sha256"] in worksheet
    assert "GET_DDL" in worksheet.upper()
    assert f"create or replace view {FQN}" in worksheet


def test_changed_rows_exit_one(tmp_path):
    wh = FakeWarehouse(simulated=[(1, 3.0)])
    code, _, evidence = run_main(tmp_path, minimal_spec(tmp_path), wh)
    assert code == 1
    assert evidence["views"][0]["buckets"]["changed"] == 1


def test_new_duplicate_key_exits_one(tmp_path):
    wh = FakeWarehouse(simulated=[(1, 2.0), (1, 5.0)])
    code, _, evidence = run_main(tmp_path, minimal_spec(tmp_path), wh)
    assert code == 1
    assert evidence["views"][0]["new_duplicate_keys"] == [[1]]


def test_write_verb_in_proposed_body_refuses_with_exit_two(tmp_path):
    raw = minimal_spec(tmp_path)
    (tmp_path / "proposed.sql").write_text(
        f"create or replace view {FQN} as\n"
        "SELECT 1 AS k, 2.0 AS v FROM t;\nDELETE FROM t"
    )
    wh = FakeWarehouse()
    code, _, _ = run_main(tmp_path, raw, wh)
    assert code == 2
    assert all("/*sim_diff:simulated*/" not in q for q in wh.queries)


def test_invalid_spec_exits_two(tmp_path):
    spec_path = tmp_path / "spec.json"
    spec_path.write_text("{}")
    assert main([str(spec_path)], run_query=FakeWarehouse()) == 2


def test_failing_check_exits_one_and_names_the_check(tmp_path):
    raw = minimal_spec(tmp_path)
    raw["views"][0]["checks"] = [
        {"label": "identity", "sql": f"SELECT * FROM {FQN} WHERE v < 0"}
    ]
    wh = FakeWarehouse(checks=[(1, -1.0)])
    code, _, evidence = run_main(tmp_path, raw, wh)
    assert code == 1
    check = evidence["views"][0]["checks"][0]
    assert check["label"] == "identity"
    assert check["passed"] is False


def test_check_sql_targets_the_simulated_body_not_the_live_view(tmp_path):
    raw = minimal_spec(tmp_path)
    raw["views"][0]["checks"] = [
        {"label": "identity", "sql": f"SELECT * FROM {FQN} WHERE v < 0"}
    ]
    wh = FakeWarehouse()
    code, _, _ = run_main(tmp_path, raw, wh)
    assert code == 0
    check_queries = [q for q in wh.queries if "/*sim_diff:check*/" in q.lower()]
    assert check_queries and all(FQN.lower() not in q.lower() for q in check_queries)


def test_shadow_table_patch_reaches_the_simulation_query(tmp_path):
    raw = minimal_spec(tmp_path)
    (tmp_path / "proposed.sql").write_text(
        f"create or replace view {FQN} as\n"
        f"SELECT k, v FROM {BASE_FQN.lower()}"
    )
    (tmp_path / "patch.sql").write_text(
        f"SELECT k, v FROM {BASE_FQN.lower()} WHERE keep = 1"
    )
    raw["shadow_tables"] = {BASE_FQN: "patch.sql"}
    wh = FakeWarehouse()
    run_main(tmp_path, raw, wh)
    sim = [q for q in wh.queries if "/*sim_diff:simulated*/" in q.lower()]
    assert sim and "keep = 1" in sim[0]
