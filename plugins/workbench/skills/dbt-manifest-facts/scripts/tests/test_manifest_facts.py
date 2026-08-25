"""Behaviour tests for `manifest_facts.py`.

The fixture below is shaped like a real dbt manifest rather than a minimal one,
because every bug this script exists to catch hides in a shape difference: a
seed whose only children are tests, a mart keyed on a column combination rather
than a surrogate, a test node that hangs off two parents. A toy manifest passes
all of those by accident.
"""

from __future__ import annotations

import json
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

import manifest_facts as mf  # noqa: E402


def _model(name, materialized="table", depends=()):
    return {
        "unique_id": f"model.proj.{name}",
        "name": name,
        "resource_type": "model",
        "config": {"materialized": materialized},
        "original_file_path": f"models/{name}.sql",
        "depends_on": {"nodes": list(depends)},
    }


def _seed(name):
    return {
        "unique_id": f"seed.proj.{name}",
        "name": name,
        "resource_type": "seed",
        "config": {"materialized": "seed"},
        "original_file_path": f"seeds/{name}.csv",
        "depends_on": {"nodes": []},
    }


def _test(name, kind, parents, **kwargs):
    node = {
        "unique_id": f"test.proj.{name}",
        "name": name,
        "resource_type": "test",
        "config": {"materialized": "test"},
        "depends_on": {"nodes": list(parents)},
    }
    if kind is not None:
        node["test_metadata"] = {"name": kind, "kwargs": kwargs}
    return node


@pytest.fixture
def manifest():
    """A project with one wired seed, one orphan seed, and two marts.

    `orphan_seed` is the case that matters: fully tested, referenced by nothing.
    """
    nodes = {}
    for node in (
        _model("stg_thing", materialized="view"),
        _model("int_thing", depends=["model.proj.stg_thing"]),
        _model("mart_slots", depends=["model.proj.int_thing", "seed.proj.wired_seed"]),
        _model("mart_history", materialized="incremental", depends=["model.proj.int_thing"]),
        _seed("wired_seed"),
        _seed("orphan_seed"),
        _test("u_stg", "unique", ["model.proj.stg_thing"], column_name="id"),
        _test(
            "combo_slots",
            "unique_combination_of_columns",
            ["model.proj.mart_slots"],
            combination_of_columns=["queue_position", "tech_number"],
        ),
        _test("nn_slots", "not_null", ["model.proj.mart_slots"], column_name="queue_uid"),
        _test("nn_hist", "not_null", ["model.proj.mart_history"], column_name="id"),
        # A singular test carries no test_metadata at all.
        _test("assert_invariant", None, ["model.proj.mart_history"]),
        # An orphan seed can still be fully tested — which is what hides it.
        _test("nn_orphan", "not_null", ["seed.proj.orphan_seed"], column_name="key"),
    ):
        nodes[node["unique_id"]] = node

    child_map = {
        "model.proj.stg_thing": ["model.proj.int_thing", "test.proj.u_stg"],
        "model.proj.int_thing": ["model.proj.mart_slots", "model.proj.mart_history"],
        "model.proj.mart_slots": ["test.proj.combo_slots", "test.proj.nn_slots"],
        "model.proj.mart_history": ["test.proj.nn_hist", "test.proj.assert_invariant"],
        "seed.proj.wired_seed": ["model.proj.mart_slots"],
        # Tests only — nothing consumes it.
        "seed.proj.orphan_seed": ["test.proj.nn_orphan"],
    }
    return {"nodes": nodes, "sources": {}, "child_map": child_map, "metadata": {}}


# --- summary ---------------------------------------------------------------


def test_summary_counts_resources_and_materializations(manifest):
    result = mf.summary(manifest)
    assert result["resources"]["model"] == 4
    assert result["resources"]["seed"] == 2
    assert result["materializations"] == {"incremental": 1, "table": 2, "view": 1}


def test_summary_separates_singular_tests_from_generic_ones(manifest):
    """A singular test has no test_metadata; counting it as generic hides it."""
    result = mf.summary(manifest)
    assert result["tests"]["singular"] == 1
    assert result["tests"]["not_null"] == 3
    assert result["tests"]["unique"] == 1
    assert result["total_tests"] == 6


# --- orphans ---------------------------------------------------------------


def test_orphans_finds_a_seed_whose_only_children_are_tests(manifest):
    """The defect this skill was built to catch."""
    found = [o["name"] for o in mf.orphans(manifest)]
    assert "orphan_seed" in found
    assert "wired_seed" not in found


def test_orphans_reports_the_test_count_that_makes_an_orphan_look_wired(manifest):
    orphan = next(o for o in mf.orphans(manifest) if o["name"] == "orphan_seed")
    assert orphan["tests"] == 1
    assert orphan["resource_type"] == "seed"


def test_leaf_marts_are_orphans_only_when_nothing_consumes_them(manifest):
    """A terminal mart has no model children — it is reported, and should be.

    Consumers live outside the project, so this is a prompt to confirm, not a
    defect on its own. The distinction belongs to the reader, not the script.
    """
    found = {o["name"] for o in mf.orphans(manifest)}
    assert {"mart_slots", "mart_history"} <= found


# --- keys ------------------------------------------------------------------


def test_keys_reports_a_column_combination_not_just_a_surrogate(manifest):
    """Reading only `unique` would report this mart as having no key at all."""
    slots = next(k for k in mf.keys(manifest) if k["name"] == "mart_slots")
    assert slots["unique"] == []
    assert slots["unique_combination"] == [["queue_position", "tech_number"]]
    assert slots["not_null"] == 1


def test_keys_can_target_one_model(manifest):
    assert [k["name"] for k in mf.keys(manifest, "stg_thing")] == ["stg_thing"]


def test_keys_raises_on_an_unknown_model(manifest):
    with pytest.raises(mf.ManifestError):
        mf.keys(manifest, "does_not_exist")


def test_keys_flags_a_model_with_no_uniqueness_at_all(manifest):
    history = next(k for k in mf.keys(manifest) if k["name"] == "mart_history")
    assert history["unique"] == []
    assert history["unique_combination"] == []


# --- lineage ---------------------------------------------------------------


def test_lineage_excludes_tests_from_children(manifest):
    """Counting tests as children turns every tested model into a consumer."""
    result = mf.lineage(manifest, "int_thing")
    assert result["children"] == ["mart_history", "mart_slots"]
    assert result["parents"] == ["stg_thing"]


def test_lineage_surfaces_materialization(manifest):
    assert mf.lineage(manifest, "mart_history")["materialized"] == "incremental"


def test_lineage_raises_on_unknown_node(manifest):
    with pytest.raises(mf.ManifestError):
        mf.lineage(manifest, "nope")


# --- loading and staleness -------------------------------------------------


def test_load_manifest_names_dbt_parse_when_the_file_is_missing(tmp_path):
    with pytest.raises(mf.ManifestError, match="dbt parse"):
        mf.load_manifest(tmp_path / "target" / "manifest.json")


def test_load_manifest_rejects_a_file_that_is_not_a_manifest(tmp_path):
    bad = tmp_path / "manifest.json"
    bad.write_text(json.dumps({"something": "else"}))
    with pytest.raises(mf.ManifestError, match="does not look like"):
        mf.load_manifest(bad)


def test_stale_sources_detects_a_model_edited_after_the_parse(tmp_path):
    target = tmp_path / "target"
    target.mkdir()
    manifest_path = target / "manifest.json"
    manifest_path.write_text("{}")
    model = tmp_path / "models" / "later.sql"
    model.parent.mkdir()
    model.write_text("select 1")
    # Push the model's mtime past the manifest's deterministically.
    import os

    stamp = manifest_path.stat().st_mtime + 10
    os.utime(model, (stamp, stamp))

    assert model in mf.stale_sources(manifest_path, tmp_path)


def test_stale_sources_ignores_build_output_and_vendored_packages(tmp_path):
    """`target/` and `dbt_packages/` churn on every build and are not source."""
    target = tmp_path / "target"
    target.mkdir()
    manifest_path = target / "manifest.json"
    manifest_path.write_text("{}")

    import os

    stamp = manifest_path.stat().st_mtime + 10
    for noise in (target / "compiled.sql", tmp_path / "dbt_packages" / "dep" / "m.sql"):
        noise.parent.mkdir(parents=True, exist_ok=True)
        noise.write_text("select 1")
        os.utime(noise, (stamp, stamp))

    assert mf.stale_sources(manifest_path, tmp_path) == []


# --- CLI -------------------------------------------------------------------


def _write_project(tmp_path, manifest):
    target = tmp_path / "target"
    target.mkdir()
    (target / "manifest.json").write_text(json.dumps(manifest))
    return tmp_path


def test_cli_orphans_exits_nonzero_so_it_can_gate_ci(tmp_path, manifest, capsys):
    project = _write_project(tmp_path, manifest)
    code = mf.main(["orphans", "--project-dir", str(project)])
    assert code == 1
    assert "orphan_seed" in capsys.readouterr().out


def test_cli_summary_exits_clean(tmp_path, manifest):
    project = _write_project(tmp_path, manifest)
    assert mf.main(["summary", "--project-dir", str(project)]) == 0


def test_cli_refuses_a_stale_manifest_by_default(tmp_path, manifest, capsys):
    """Silence on a stale manifest is the failure mode; make it loud."""
    project = _write_project(tmp_path, manifest)
    model = project / "models" / "new.sql"
    model.parent.mkdir(parents=True, exist_ok=True)
    model.write_text("select 1")
    import os

    stamp = (project / "target" / "manifest.json").stat().st_mtime + 10
    os.utime(model, (stamp, stamp))

    code = mf.main(["summary", "--project-dir", str(project)])
    assert code == 2
    assert "STALE" in capsys.readouterr().err


def test_cli_allow_stale_downgrades_the_refusal_to_a_warning(tmp_path, manifest, capsys):
    project = _write_project(tmp_path, manifest)
    model = project / "models" / "new.sql"
    model.parent.mkdir(parents=True, exist_ok=True)
    model.write_text("select 1")
    import os

    stamp = (project / "target" / "manifest.json").stat().st_mtime + 10
    os.utime(model, (stamp, stamp))

    code = mf.main(["summary", "--allow-stale", "--project-dir", str(project)])
    captured = capsys.readouterr()
    assert code == 0
    assert "STALE" in captured.err
    assert "resources:" in captured.out


def test_cli_missing_manifest_exits_two(tmp_path, capsys):
    code = mf.main(["summary", "--project-dir", str(tmp_path)])
    assert code == 2
    assert "dbt parse" in capsys.readouterr().err
