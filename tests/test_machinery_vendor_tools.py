"""Vendor/drift tooling for the vault machinery payload (W3).

Covers the three shipped pieces:

- ``presets/vault-ops/machinery/vendor-map.json`` — the managed-set
  declaration (every ``engine/`` file -> its vault target path).
- ``machinery/tools/machinery_check.py`` — offline drift detector run inside
  a target vault (stdlib only, no git, no network).
- ``machinery/tools/machinery_sync.py`` — the vendor CLI (``adopt`` /
  ``upgrade``) run from a workshop checkout against a target vault.

Every test is hermetic against tmp_path fixtures that simulate a vault —
none reads or writes a real vault checkout.
"""

from __future__ import annotations

import ast
import hashlib
import importlib.util
import json
import shutil
import subprocess
import sys
from datetime import datetime, timezone
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parent.parent
MACHINERY_DIR = REPO_ROOT / "presets" / "vault-ops" / "machinery"
TOOLS_DIR = MACHINERY_DIR / "tools"

LOCKFILE_RELPATH = ".vault/machinery.lock.json"

_JUNK_NAMES = {"__pycache__", ".pytest_cache", ".ruff_cache", ".DS_Store"}


def _load_tool(name: str):
    """Import a machinery tool module directly from its shipped file path."""
    path = TOOLS_DIR / f"{name}.py"
    spec = importlib.util.spec_from_file_location(f"_machinery_{name}", path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


@pytest.fixture
def check_mod():
    return _load_tool("machinery_check")


@pytest.fixture
def sync_mod():
    return _load_tool("machinery_sync")


def _sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


# ---------------------------------------------------------------------------
# Fixture vault / workshop builders
# ---------------------------------------------------------------------------

MAP_ENTRIES = [
    {
        "kind": "file",
        "source": "engine/alpha.py",
        "target": ".claude/scripts/alpha.py",
    },
    {
        "kind": "file",
        "source": "engine/run-hook.sh",
        "target": ".claude/scripts/run-hook.sh",
    },
    {
        "kind": "file",
        "source": "engine/queries/deep.py",
        "target": ".claude/scripts/queries/deep.py",
    },
]


@pytest.fixture
def source_machinery(tmp_path: Path) -> Path:
    """A simulated workshop machinery dir: engine files, vendor map, manifest."""
    preset = tmp_path / "workshop" / "presets" / "vault-ops"
    machinery = preset / "machinery"
    engine = machinery / "engine"
    (engine / "queries").mkdir(parents=True)
    (engine / "alpha.py").write_text("print('alpha v1')\n")
    (engine / "run-hook.sh").write_text("#!/bin/sh\necho hook\n")
    (engine / "queries" / "deep.py").write_text("print('deep v1')\n")
    (machinery / "vendor-map.json").write_text(
        json.dumps({"schema": 1, "entries": MAP_ENTRIES}, indent=2) + "\n"
    )
    (preset / "manifest.json").write_text(
        json.dumps({"name": "vault-ops", "version": "9.9.9"}) + "\n"
    )
    return machinery


@pytest.fixture
def vault_target(tmp_path: Path) -> Path:
    """An empty simulated vault repo."""
    target = tmp_path / "vault"
    target.mkdir()
    return target


def _seed_identical_target(machinery: Path, target: Path) -> None:
    """Copy every mapped file into the target at its mapped path."""
    for entry in MAP_ENTRIES:
        dest = target / entry["target"]
        dest.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(machinery / entry["source"], dest)


def _read_lock(target: Path) -> dict:
    return json.loads((target / LOCKFILE_RELPATH).read_text())


def _write_lock(target: Path, files: dict[str, dict]) -> None:
    lock = {
        "schema": 1,
        "source": {
            "repo": "the-workshop",
            "preset": "vault-ops",
            "version": "9.9.9",
            "ref": None,
        },
        "generated_at": "2026-07-25T00:00:00Z",
        "files": files,
    }
    lock_path = target / LOCKFILE_RELPATH
    lock_path.parent.mkdir(parents=True, exist_ok=True)
    lock_path.write_text(json.dumps(lock, indent=2) + "\n")


def _adopted(sync_mod, machinery: Path, target: Path) -> None:
    """Run a successful adopt so upgrade tests start from a locked state."""
    _seed_identical_target(machinery, target)
    rc = sync_mod.main(
        ["adopt", "--target", str(target), "--source", str(machinery)]
    )
    assert rc == 0, "fixture adopt must succeed"


# ---------------------------------------------------------------------------
# vendor-map.json
# ---------------------------------------------------------------------------


class TestVendorMap:
    def test_versioned_envelope(self) -> None:
        data = json.loads((MACHINERY_DIR / "vendor-map.json").read_text())
        assert data["schema"] == 1
        assert isinstance(data["entries"], list)
        for entry in data["entries"]:
            assert entry["kind"] == "file"
            assert entry["source"].startswith("engine/")
            assert entry["target"].startswith(".claude/scripts/")

    def test_covers_engine_tree_exactly(self) -> None:
        """Every engine file is mapped; no stale entries linger."""
        data = json.loads((MACHINERY_DIR / "vendor-map.json").read_text())
        mapped_sources = {entry["source"] for entry in data["entries"]}
        actual = {
            path.relative_to(MACHINERY_DIR).as_posix()
            for path in (MACHINERY_DIR / "engine").rglob("*")
            if path.is_file()
            and not path.name.endswith(".pyc")
            and not (_JUNK_NAMES & set(path.parts))
        }
        assert mapped_sources == actual

    def test_targets_follow_v1_rule(self) -> None:
        """v1 rule: engine/<relpath> -> .claude/scripts/<relpath>."""
        data = json.loads((MACHINERY_DIR / "vendor-map.json").read_text())
        for entry in data["entries"]:
            relative = entry["source"].removeprefix("engine/")
            assert entry["target"] == f".claude/scripts/{relative}"


# ---------------------------------------------------------------------------
# machinery_sync adopt
# ---------------------------------------------------------------------------


class TestAdopt:
    def test_happy_path_writes_lockfile(
        self, sync_mod, source_machinery: Path, vault_target: Path
    ) -> None:
        _seed_identical_target(source_machinery, vault_target)

        rc = sync_mod.main(
            [
                "adopt",
                "--target",
                str(vault_target),
                "--source",
                str(source_machinery),
            ]
        )

        assert rc == 0
        lock = _read_lock(vault_target)
        assert lock["schema"] == 1
        assert lock["source"]["repo"] == "the-workshop"
        assert lock["source"]["preset"] == "vault-ops"
        assert lock["source"]["version"] == "9.9.9"
        assert "ref" in lock["source"]
        stamp = datetime.fromisoformat(
            lock["generated_at"].replace("Z", "+00:00")
        )
        assert stamp.utcoffset() == timezone.utc.utcoffset(None)
        assert set(lock["files"]) == {entry["target"] for entry in MAP_ENTRIES}
        for entry in MAP_ENTRIES:
            record = lock["files"][entry["target"]]
            assert record["tier"] == "managed"
            assert record["sha256"] == _sha256(vault_target / entry["target"])

    def test_refuses_on_single_byte_diff(
        self, sync_mod, source_machinery: Path, vault_target: Path
    ) -> None:
        _seed_identical_target(source_machinery, vault_target)
        edited = vault_target / ".claude/scripts/alpha.py"
        edited.write_text(edited.read_text() + "#")

        rc = sync_mod.main(
            [
                "adopt",
                "--target",
                str(vault_target),
                "--source",
                str(source_machinery),
            ]
        )

        assert rc == 1
        assert not (vault_target / LOCKFILE_RELPATH).exists()

    def test_refuses_on_missing_target_file(
        self, sync_mod, source_machinery: Path, vault_target: Path, capsys
    ) -> None:
        _seed_identical_target(source_machinery, vault_target)
        (vault_target / ".claude/scripts/queries/deep.py").unlink()

        rc = sync_mod.main(
            [
                "adopt",
                "--target",
                str(vault_target),
                "--source",
                str(source_machinery),
            ]
        )

        assert rc == 1
        assert not (vault_target / LOCKFILE_RELPATH).exists()
        assert "deep.py" in capsys.readouterr().out

    def test_json_output_reports_per_file_status(
        self, sync_mod, source_machinery: Path, vault_target: Path, capsys
    ) -> None:
        _seed_identical_target(source_machinery, vault_target)
        edited = vault_target / ".claude/scripts/alpha.py"
        edited.write_text(edited.read_text() + "#")

        rc = sync_mod.main(
            [
                "adopt",
                "--target",
                str(vault_target),
                "--source",
                str(source_machinery),
                "--json",
            ]
        )

        assert rc == 1
        report = json.loads(capsys.readouterr().out)
        assert report["ok"] is False
        statuses = {f["target"]: f["status"] for f in report["files"]}
        assert statuses[".claude/scripts/alpha.py"] == "differs"
        assert statuses[".claude/scripts/run-hook.sh"] == "identical"

    def test_ref_is_null_outside_git(
        self, sync_mod, source_machinery: Path, vault_target: Path
    ) -> None:
        _adopted(sync_mod, source_machinery, vault_target)

        assert _read_lock(vault_target)["source"]["ref"] is None

    def test_ref_resolves_from_git_checkout(
        self, sync_mod, source_machinery: Path, vault_target: Path
    ) -> None:
        workshop_root = source_machinery.parents[2]
        env = {
            "GIT_AUTHOR_NAME": "t",
            "GIT_AUTHOR_EMAIL": "t@t",
            "GIT_COMMITTER_NAME": "t",
            "GIT_COMMITTER_EMAIL": "t@t",
            "PATH": "/usr/bin:/bin:/usr/local/bin",
        }
        subprocess.run(
            ["git", "init", "-q", str(workshop_root)], check=True, env=env
        )
        subprocess.run(
            ["git", "-C", str(workshop_root), "add", "-A"], check=True, env=env
        )
        subprocess.run(
            ["git", "-C", str(workshop_root), "commit", "-q", "-m", "seed"],
            check=True,
            env=env,
        )
        head = subprocess.run(
            ["git", "-C", str(workshop_root), "rev-parse", "HEAD"],
            check=True,
            env=env,
            capture_output=True,
            text=True,
        ).stdout.strip()

        _adopted(sync_mod, source_machinery, vault_target)

        assert _read_lock(vault_target)["source"]["ref"] == head


# ---------------------------------------------------------------------------
# machinery_check
# ---------------------------------------------------------------------------


class TestCheck:
    def _drifted_target(self, target: Path) -> None:
        """Target with one file per status: OK, LOCAL-EDIT, MISSING, UNTRACKED."""
        scripts = target / ".claude" / "scripts"
        scripts.mkdir(parents=True)
        ok = scripts / "ok.py"
        ok.write_text("print('ok')\n")
        edited = scripts / "edited.py"
        edited.write_text("print('edited, locally')\n")
        (scripts / "rogue.py").write_text("print('rogue')\n")
        _write_lock(
            target,
            {
                ".claude/scripts/ok.py": {
                    "tier": "managed",
                    "sha256": _sha256(ok),
                },
                ".claude/scripts/edited.py": {
                    "tier": "managed",
                    "sha256": "0" * 64,
                },
                ".claude/scripts/gone.py": {
                    "tier": "managed",
                    "sha256": "1" * 64,
                },
            },
        )

    def test_reports_all_four_statuses(
        self, check_mod, vault_target: Path, capsys
    ) -> None:
        self._drifted_target(vault_target)

        rc = check_mod.main(["--target", str(vault_target), "--json"])

        assert rc == 0
        report = json.loads(capsys.readouterr().out)
        statuses = {f["path"]: f["status"] for f in report["files"]}
        assert statuses[".claude/scripts/ok.py"] == "OK"
        assert statuses[".claude/scripts/edited.py"] == "LOCAL-EDIT"
        assert statuses[".claude/scripts/gone.py"] == "MISSING"
        assert statuses[".claude/scripts/rogue.py"] == "UNTRACKED"

    def test_human_report_names_statuses(
        self, check_mod, vault_target: Path, capsys
    ) -> None:
        self._drifted_target(vault_target)

        rc = check_mod.main(["--target", str(vault_target)])

        assert rc == 0
        out = capsys.readouterr().out
        for token in ("OK", "LOCAL-EDIT", "MISSING", "UNTRACKED"):
            assert token in out

    def test_strict_exits_1_on_drift(self, check_mod, vault_target: Path) -> None:
        self._drifted_target(vault_target)

        assert check_mod.main(["--target", str(vault_target), "--strict"]) == 1

    def test_strict_exits_0_when_clean(
        self, check_mod, vault_target: Path
    ) -> None:
        scripts = vault_target / ".claude" / "scripts"
        scripts.mkdir(parents=True)
        ok = scripts / "ok.py"
        ok.write_text("print('ok')\n")
        _write_lock(
            vault_target,
            {".claude/scripts/ok.py": {"tier": "managed", "sha256": _sha256(ok)}},
        )

        assert check_mod.main(["--target", str(vault_target), "--strict"]) == 0

    def test_missing_lockfile_is_an_error(
        self, check_mod, vault_target: Path
    ) -> None:
        assert check_mod.main(["--target", str(vault_target)]) == 2

    def test_untracked_scan_ignores_pycache_junk(
        self, check_mod, vault_target: Path, capsys
    ) -> None:
        scripts = vault_target / ".claude" / "scripts"
        pycache = scripts / "__pycache__"
        pycache.mkdir(parents=True)
        (pycache / "ok.cpython-312.pyc").write_bytes(b"junk")
        ok = scripts / "ok.py"
        ok.write_text("print('ok')\n")
        _write_lock(
            vault_target,
            {".claude/scripts/ok.py": {"tier": "managed", "sha256": _sha256(ok)}},
        )

        rc = check_mod.main(["--target", str(vault_target), "--json"])

        assert rc == 0
        report = json.loads(capsys.readouterr().out)
        assert all(f["status"] == "OK" for f in report["files"])

    def test_stdlib_only_imports(self) -> None:
        """machinery_check is vendored into vaults: stdlib imports only."""
        tree = ast.parse((TOOLS_DIR / "machinery_check.py").read_text())
        imported: set[str] = set()
        for node in ast.walk(tree):
            if isinstance(node, ast.Import):
                imported.update(alias.name.split(".")[0] for alias in node.names)
            elif isinstance(node, ast.ImportFrom) and node.level == 0:
                if node.module:
                    imported.add(node.module.split(".")[0])
        non_stdlib = imported - set(sys.stdlib_module_names)
        assert not non_stdlib, f"non-stdlib imports: {sorted(non_stdlib)}"


# ---------------------------------------------------------------------------
# machinery_sync upgrade
# ---------------------------------------------------------------------------


class TestUpgrade:
    def test_dry_run_mutates_nothing(
        self, sync_mod, source_machinery: Path, vault_target: Path, capsys
    ) -> None:
        _adopted(sync_mod, source_machinery, vault_target)
        capsys.readouterr()
        (source_machinery / "engine" / "alpha.py").write_text("print('alpha v2')\n")
        lock_before = (vault_target / LOCKFILE_RELPATH).read_bytes()
        target_before = (vault_target / ".claude/scripts/alpha.py").read_bytes()

        rc = sync_mod.main(
            [
                "upgrade",
                "--target",
                str(vault_target),
                "--source",
                str(source_machinery),
            ]
        )

        assert rc == 0
        out = capsys.readouterr().out
        assert "copy" in out
        assert "skip-identical" in out
        assert (vault_target / LOCKFILE_RELPATH).read_bytes() == lock_before
        assert (
            vault_target / ".claude/scripts/alpha.py"
        ).read_bytes() == target_before

    def test_apply_copies_and_relocks(
        self, sync_mod, source_machinery: Path, vault_target: Path
    ) -> None:
        _adopted(sync_mod, source_machinery, vault_target)
        new_source = source_machinery / "engine" / "alpha.py"
        new_source.write_text("print('alpha v2')\n")

        rc = sync_mod.main(
            [
                "upgrade",
                "--target",
                str(vault_target),
                "--source",
                str(source_machinery),
                "--apply",
            ]
        )

        assert rc == 0
        copied = vault_target / ".claude/scripts/alpha.py"
        assert copied.read_bytes() == new_source.read_bytes()
        lock = _read_lock(vault_target)
        assert lock["files"][".claude/scripts/alpha.py"]["sha256"] == _sha256(
            copied
        )

    def test_refuses_over_local_edit(
        self, sync_mod, source_machinery: Path, vault_target: Path
    ) -> None:
        _adopted(sync_mod, source_machinery, vault_target)
        local = vault_target / ".claude/scripts/alpha.py"
        local.write_text("print('my local tweak')\n")
        (source_machinery / "engine" / "alpha.py").write_text("print('alpha v2')\n")
        lock_before = (vault_target / LOCKFILE_RELPATH).read_bytes()

        rc = sync_mod.main(
            [
                "upgrade",
                "--target",
                str(vault_target),
                "--source",
                str(source_machinery),
                "--apply",
            ]
        )

        assert rc == 1
        assert local.read_text() == "print('my local tweak')\n"
        assert (vault_target / LOCKFILE_RELPATH).read_bytes() == lock_before

    def test_refusal_applies_nothing_else(
        self, sync_mod, source_machinery: Path, vault_target: Path
    ) -> None:
        """A refused plan is atomic: no other file is copied either."""
        _adopted(sync_mod, source_machinery, vault_target)
        (vault_target / ".claude/scripts/alpha.py").write_text("print('tweak')\n")
        (source_machinery / "engine" / "alpha.py").write_text("print('alpha v2')\n")
        upgradeable_source = source_machinery / "engine" / "queries" / "deep.py"
        upgradeable_source.write_text("print('deep v2')\n")
        upgradeable_target = vault_target / ".claude/scripts/queries/deep.py"
        before = upgradeable_target.read_bytes()

        rc = sync_mod.main(
            [
                "upgrade",
                "--target",
                str(vault_target),
                "--source",
                str(source_machinery),
                "--apply",
            ]
        )

        assert rc == 1
        assert upgradeable_target.read_bytes() == before

    def test_keep_local_records_and_skips(
        self, sync_mod, source_machinery: Path, vault_target: Path
    ) -> None:
        _adopted(sync_mod, source_machinery, vault_target)
        local = vault_target / ".claude/scripts/alpha.py"
        local.write_text("print('my local tweak')\n")
        (source_machinery / "engine" / "alpha.py").write_text("print('alpha v2')\n")

        rc = sync_mod.main(
            [
                "upgrade",
                "--target",
                str(vault_target),
                "--source",
                str(source_machinery),
                "--apply",
                "--keep-local",
                ".claude/scripts/alpha.py",
            ]
        )

        assert rc == 0
        assert local.read_text() == "print('my local tweak')\n"
        record = _read_lock(vault_target)["files"][".claude/scripts/alpha.py"]
        assert record["keep_local"] is True
        assert record["sha256"] == _sha256(local)

    def test_keep_local_is_sticky_across_upgrades(
        self, sync_mod, source_machinery: Path, vault_target: Path
    ) -> None:
        """A recorded keep_local survives later upgrades without re-flagging."""
        _adopted(sync_mod, source_machinery, vault_target)
        local = vault_target / ".claude/scripts/alpha.py"
        local.write_text("print('my local tweak')\n")
        (source_machinery / "engine" / "alpha.py").write_text("print('alpha v2')\n")
        sync_mod.main(
            [
                "upgrade",
                "--target",
                str(vault_target),
                "--source",
                str(source_machinery),
                "--apply",
                "--keep-local",
                ".claude/scripts/alpha.py",
            ]
        )
        (source_machinery / "engine" / "alpha.py").write_text("print('alpha v3')\n")

        rc = sync_mod.main(
            [
                "upgrade",
                "--target",
                str(vault_target),
                "--source",
                str(source_machinery),
                "--apply",
            ]
        )

        assert rc == 0
        assert local.read_text() == "print('my local tweak')\n"
        record = _read_lock(vault_target)["files"][".claude/scripts/alpha.py"]
        assert record["keep_local"] is True

    def test_force_overwrites_local_edit(
        self, sync_mod, source_machinery: Path, vault_target: Path
    ) -> None:
        _adopted(sync_mod, source_machinery, vault_target)
        local = vault_target / ".claude/scripts/alpha.py"
        local.write_text("print('my local tweak')\n")
        new_source = source_machinery / "engine" / "alpha.py"
        new_source.write_text("print('alpha v2')\n")

        rc = sync_mod.main(
            [
                "upgrade",
                "--target",
                str(vault_target),
                "--source",
                str(source_machinery),
                "--apply",
                "--force",
            ]
        )

        assert rc == 0
        assert local.read_bytes() == new_source.read_bytes()
        record = _read_lock(vault_target)["files"][".claude/scripts/alpha.py"]
        assert record["sha256"] == _sha256(local)
        assert not record.get("keep_local")

    def test_requires_lockfile(
        self, sync_mod, source_machinery: Path, vault_target: Path
    ) -> None:
        _seed_identical_target(source_machinery, vault_target)

        rc = sync_mod.main(
            [
                "upgrade",
                "--target",
                str(vault_target),
                "--source",
                str(source_machinery),
                "--apply",
            ]
        )

        assert rc == 2

    def test_restores_missing_managed_file(
        self, sync_mod, source_machinery: Path, vault_target: Path
    ) -> None:
        _adopted(sync_mod, source_machinery, vault_target)
        missing = vault_target / ".claude/scripts/queries/deep.py"
        missing.unlink()

        rc = sync_mod.main(
            [
                "upgrade",
                "--target",
                str(vault_target),
                "--source",
                str(source_machinery),
                "--apply",
            ]
        )

        assert rc == 0
        assert missing.read_bytes() == (
            source_machinery / "engine" / "queries" / "deep.py"
        ).read_bytes()


# ---------------------------------------------------------------------------
# Write-path allowlist (structural safety)
# ---------------------------------------------------------------------------


class TestWritePathAllowlist:
    def _hostile_map(self, machinery: Path, target_path: str) -> None:
        entries = [
            {"kind": "file", "source": "engine/alpha.py", "target": target_path}
        ]
        (machinery / "vendor-map.json").write_text(
            json.dumps({"schema": 1, "entries": entries}) + "\n"
        )

    def test_rejects_traversal_target(
        self, sync_mod, source_machinery: Path, vault_target: Path
    ) -> None:
        self._hostile_map(source_machinery, "../../escape")

        rc = sync_mod.main(
            [
                "adopt",
                "--target",
                str(vault_target),
                "--source",
                str(source_machinery),
            ]
        )

        assert rc == 2
        assert not (vault_target.parent / "escape").exists()
        assert not (vault_target.parents[1] / "escape").exists()
        assert not (vault_target / LOCKFILE_RELPATH).exists()

    def test_rejects_absolute_target(
        self, sync_mod, source_machinery: Path, vault_target: Path, tmp_path: Path
    ) -> None:
        evil = tmp_path / "evil.py"
        self._hostile_map(source_machinery, str(evil))

        rc = sync_mod.main(
            [
                "adopt",
                "--target",
                str(vault_target),
                "--source",
                str(source_machinery),
            ]
        )

        assert rc == 2
        assert not evil.exists()

    def test_upgrade_rejects_traversal_target_too(
        self, sync_mod, source_machinery: Path, vault_target: Path
    ) -> None:
        _adopted(sync_mod, source_machinery, vault_target)
        self._hostile_map(source_machinery, "../../escape")

        rc = sync_mod.main(
            [
                "upgrade",
                "--target",
                str(vault_target),
                "--source",
                str(source_machinery),
                "--apply",
            ]
        )

        assert rc == 2
        assert not (vault_target.parent / "escape").exists()

    def test_rejects_traversal_source(
        self, sync_mod, source_machinery: Path, vault_target: Path, tmp_path: Path
    ) -> None:
        """A map entry may not read outside the machinery dir either."""
        secret = tmp_path / "secret.txt"
        secret.write_text("s3cret\n")
        entries = [
            {
                "kind": "file",
                "source": "../../../../secret.txt",
                "target": ".claude/scripts/alpha.py",
            }
        ]
        (source_machinery / "vendor-map.json").write_text(
            json.dumps({"schema": 1, "entries": entries}) + "\n"
        )

        rc = sync_mod.main(
            [
                "adopt",
                "--target",
                str(vault_target),
                "--source",
                str(source_machinery),
            ]
        )

        assert rc == 2


# ---------------------------------------------------------------------------
# CLI entry points run standalone (the vendored/hook execution mode)
# ---------------------------------------------------------------------------


class TestStandaloneExecution:
    def test_check_runs_as_a_script(self, vault_target: Path) -> None:
        scripts = vault_target / ".claude" / "scripts"
        scripts.mkdir(parents=True)
        ok = scripts / "ok.py"
        ok.write_text("print('ok')\n")
        _write_lock(
            vault_target,
            {".claude/scripts/ok.py": {"tier": "managed", "sha256": _sha256(ok)}},
        )

        result = subprocess.run(
            [
                sys.executable,
                str(TOOLS_DIR / "machinery_check.py"),
                "--target",
                str(vault_target),
                "--strict",
            ],
            capture_output=True,
            text=True,
        )

        assert result.returncode == 0, result.stderr

    def test_sync_runs_as_a_script(
        self, source_machinery: Path, vault_target: Path
    ) -> None:
        _seed_identical_target(source_machinery, vault_target)

        result = subprocess.run(
            [
                sys.executable,
                str(TOOLS_DIR / "machinery_sync.py"),
                "adopt",
                "--target",
                str(vault_target),
                "--source",
                str(source_machinery),
            ],
            capture_output=True,
            text=True,
        )

        assert result.returncode == 0, result.stderr
        assert (vault_target / LOCKFILE_RELPATH).exists()


# ---------------------------------------------------------------------------
# Build integration: the payload ships the tools and the map
# ---------------------------------------------------------------------------


class TestShippedPayload:
    def test_dist_ships_tools_and_vendor_map(self) -> None:
        """build_preset copies machinery/ wholesale; the checked-in dist must
        carry the vendor tooling (verify-generated keeps it fresh)."""
        dist_machinery = REPO_ROOT / "dist" / "vault-ops" / "machinery"
        assert (dist_machinery / "vendor-map.json").is_file()
        assert (dist_machinery / "tools" / "machinery_check.py").is_file()
        assert (dist_machinery / "tools" / "machinery_sync.py").is_file()

    def test_deferred_verbs_are_documented(self) -> None:
        """W3 ships adopt/check/upgrade only; init and upstream are deferred
        deliberately, and the module docstring must say so."""
        text = (TOOLS_DIR / "machinery_sync.py").read_text()
        module_doc = ast.get_docstring(ast.parse(text)) or ""
        assert "init" in module_doc
        assert "upstream" in module_doc
        assert "deferred" in module_doc.lower()
