"""Provenance of every file A2 copies from the terse-lens-contract A/B experiment.

Each recorded ``source_blob_sha`` is checked against ``git rev-parse
<resolved_ref>:<source_path>`` (the experiment as it stood at the resolved
ref), never against a hash of working-tree bytes of a file this case does not
own. The experiment's own files are copy-only: this case neither edits nor
references them in place.
"""

from __future__ import annotations

import tomllib

import pytest
_EXPERIMENT = "docs/experiments/2026-09-21-terse-lens-contract-ab"


@pytest.fixture(scope="module")
def provenance(case_dir) -> dict:
    return tomllib.loads((case_dir / "provenance.toml").read_text(encoding="utf-8"))


def test_provenance_records_a_full_resolved_commit_sha(provenance):
    ref = provenance["resolved_ref"]
    assert len(ref) == 40 and set(ref) <= set("0123456789abcdef")


def test_every_copied_fixture_file_has_a_provenance_entry(provenance, case_dir):
    recorded = {entry["file"] for entry in provenance["files"]}
    on_disk = {
        path.relative_to(case_dir).as_posix() for path in (case_dir / "fixture").rglob("*") if path.is_file()
    }
    assert on_disk == {"fixture/defects.json", "fixture/diff.patch", "fixture/spec.md"}
    assert on_disk <= recorded


def test_every_copied_ab_raw_has_a_provenance_entry(provenance, case_dir):
    recorded = {entry["file"] for entry in provenance["files"]}
    on_disk = {
        path.relative_to(case_dir).as_posix() for path in (case_dir / "ab_raws").rglob("*") if path.is_file()
    }
    assert len(on_disk) == 18  # 3 arms (a, b, a2) x 3 lenses x 2 replicates
    assert on_disk <= recorded


def test_provenance_lists_no_file_that_is_not_in_the_case(provenance, case_dir):
    for entry in provenance["files"]:
        assert (case_dir / entry["file"]).is_file(), entry["file"]


def test_each_entry_names_a_source_inside_the_experiment(provenance):
    for entry in provenance["files"]:
        assert entry["source_path"].startswith(_EXPERIMENT + "/"), entry


def test_each_source_blob_sha_is_what_git_resolves_at_the_resolved_ref(provenance, git):
    for entry in provenance["files"]:
        resolved = git("rev-parse", f"{provenance['resolved_ref']}:{entry['source_path']}").strip()
        assert entry["source_blob_sha"] == resolved, entry["file"]


def test_each_copy_is_byte_identical_to_its_source_blob(provenance, case_dir, git):
    for entry in provenance["files"]:
        copied = git("hash-object", "--", str(case_dir / entry["file"])).strip()
        assert copied == entry["source_blob_sha"], entry["file"]


def test_the_experiment_directory_is_unmodified_since_the_resolved_ref(provenance, git):
    """The experiment is a frozen record: A2 copies from it and never edits it."""
    changed = git("diff", "--name-only", provenance["resolved_ref"], "--", _EXPERIMENT)
    assert changed.strip() == "", changed
    untracked = git("ls-files", "--others", "--exclude-standard", "--", _EXPERIMENT)
    assert untracked.strip() == "", untracked
