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
        """Schema 2 (W4): file entries plus the settings-hooks json-key merge.

        The shipped map's per-section content pins (engine v1 rule, agents,
        rendered surfaces, skills trees) live in tests/test_machinery_wiring.py
        beside the generator that produces them.
        """
        data = json.loads((MACHINERY_DIR / "vendor-map.json").read_text())
        assert data["schema"] == 2
        assert isinstance(data["entries"], list)
        for entry in data["entries"]:
            assert entry["kind"] in ("file", "json-key")
            assert entry["source"]
            assert entry["target"]
            if entry["kind"] == "json-key":
                assert entry["key"]

    def test_covers_engine_tree_exactly(self) -> None:
        """Every engine file is mapped; no stale engine entries linger.

        ``engine/vault_scope.py`` is the one deliberate exception (W5): it is
        scaffold-owned — init renders it from the scaffold template and
        upgrade never touches it — so it must NOT appear in the managed map.
        """
        data = json.loads((MACHINERY_DIR / "vendor-map.json").read_text())
        mapped_sources = {
            entry["source"]
            for entry in data["entries"]
            if entry["source"].startswith("engine/")
        }
        actual = {
            path.relative_to(MACHINERY_DIR).as_posix()
            for path in (MACHINERY_DIR / "engine").rglob("*")
            if path.is_file()
            and not path.name.endswith(".pyc")
            and not (_JUNK_NAMES & set(path.parts))
        }
        assert mapped_sources == actual - {"engine/vault_scope.py"}


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
# Schema 2: preset-root sources and json-key entries (W4)
# ---------------------------------------------------------------------------

HOOKS_VALUE = {
    "Stop": [
        {
            "hooks": [
                {
                    "type": "command",
                    "command": "bash run-hook.sh stop.py",
                    "timeout": 10000,
                }
            ]
        }
    ]
}

MAP2_ENTRIES = [
    {
        "kind": "file",
        "source": "engine/alpha.py",
        "target": ".claude/scripts/alpha.py",
    },
    {
        "kind": "file",
        "source": "skills/my-skill/SKILL.md",
        "source_root": "preset",
        "target": ".claude/skills/my-skill/SKILL.md",
    },
    {
        "kind": "json-key",
        "source": "rendered/claude-settings-hooks.json",
        "target": ".claude/settings.json",
        "key": "hooks",
    },
]


def _canonical_sha(value) -> str:
    canonical = json.dumps(value, sort_keys=True, separators=(",", ":"))
    return hashlib.sha256(canonical.encode("utf-8")).hexdigest()


@pytest.fixture
def source_machinery2(tmp_path: Path) -> Path:
    """A schema-2 workshop machinery dir: engine + rendered + sibling skills."""
    preset = tmp_path / "workshop" / "presets" / "vault-ops"
    machinery = preset / "machinery"
    (machinery / "engine").mkdir(parents=True)
    (machinery / "engine" / "alpha.py").write_text("print('alpha v1')\n")
    (machinery / "rendered").mkdir()
    (machinery / "rendered" / "claude-settings-hooks.json").write_text(
        json.dumps(HOOKS_VALUE, indent=2) + "\n"
    )
    (preset / "skills" / "my-skill").mkdir(parents=True)
    (preset / "skills" / "my-skill" / "SKILL.md").write_text("# my skill\n")
    (machinery / "vendor-map.json").write_text(
        json.dumps({"schema": 2, "entries": MAP2_ENTRIES}, indent=2) + "\n"
    )
    (preset / "manifest.json").write_text(
        json.dumps({"name": "vault-ops", "version": "9.9.9"}) + "\n"
    )
    return machinery


def _seed_identical_target2(machinery: Path, target: Path) -> None:
    """Target state a schema-2 adopt must accept as a provable no-op."""
    preset = machinery.parent
    for relative, source in (
        (".claude/scripts/alpha.py", machinery / "engine" / "alpha.py"),
        (
            ".claude/skills/my-skill/SKILL.md",
            preset / "skills" / "my-skill" / "SKILL.md",
        ),
    ):
        dest = target / relative
        dest.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(source, dest)
    # Same hooks VALUE, different formatting, extra sibling keys: json-key
    # adoption is semantic (canonical JSON), not byte comparison.
    settings = target / ".claude" / "settings.json"
    settings.write_text(
        json.dumps(
            {"permissions": {"allow": ["Write"]}, "hooks": HOOKS_VALUE},
            indent=4,
        )
    )


class TestSchema2Map:
    def test_adopt_accepts_schema2_and_locks_every_kind(
        self, sync_mod, source_machinery2: Path, vault_target: Path
    ) -> None:
        _seed_identical_target2(source_machinery2, vault_target)

        rc = sync_mod.main(
            [
                "adopt",
                "--target",
                str(vault_target),
                "--source",
                str(source_machinery2),
            ]
        )

        assert rc == 0
        lock = _read_lock(vault_target)
        assert set(lock["files"]) == {
            ".claude/scripts/alpha.py",
            ".claude/skills/my-skill/SKILL.md",
            ".claude/settings.json",
        }
        settings_entry = lock["files"][".claude/settings.json"]
        assert settings_entry["kind"] == "json-key"
        assert settings_entry["key"] == "hooks"
        assert settings_entry["sha256"] == _canonical_sha(HOOKS_VALUE)
        skill_entry = lock["files"][".claude/skills/my-skill/SKILL.md"]
        assert "kind" not in skill_entry

    def test_rejects_unknown_schema(
        self, sync_mod, source_machinery2: Path, vault_target: Path
    ) -> None:
        (source_machinery2 / "vendor-map.json").write_text(
            json.dumps({"schema": 3, "entries": []}) + "\n"
        )

        rc = sync_mod.main(
            [
                "adopt",
                "--target",
                str(vault_target),
                "--source",
                str(source_machinery2),
            ]
        )

        assert rc == 2

    def test_schema1_rejects_json_key_kind(
        self, sync_mod, source_machinery2: Path, vault_target: Path
    ) -> None:
        """A schema-1 map may not smuggle in schema-2 constructs."""
        (source_machinery2 / "vendor-map.json").write_text(
            json.dumps({"schema": 1, "entries": [MAP2_ENTRIES[2]]}) + "\n"
        )

        rc = sync_mod.main(
            [
                "adopt",
                "--target",
                str(vault_target),
                "--source",
                str(source_machinery2),
            ]
        )

        assert rc == 2

    def test_schema1_rejects_preset_source_root(
        self, sync_mod, source_machinery2: Path, vault_target: Path
    ) -> None:
        (source_machinery2 / "vendor-map.json").write_text(
            json.dumps({"schema": 1, "entries": [MAP2_ENTRIES[1]]}) + "\n"
        )

        rc = sync_mod.main(
            [
                "adopt",
                "--target",
                str(vault_target),
                "--source",
                str(source_machinery2),
            ]
        )

        assert rc == 2

    def test_rejects_preset_source_escape(
        self, sync_mod, source_machinery2: Path, vault_target: Path, tmp_path: Path
    ) -> None:
        secret = tmp_path / "secret.txt"
        secret.write_text("s3cret\n")
        entries = [
            {
                "kind": "file",
                "source": "../../../secret.txt",
                "source_root": "preset",
                "target": ".claude/skills/x.md",
            }
        ]
        (source_machinery2 / "vendor-map.json").write_text(
            json.dumps({"schema": 2, "entries": entries}) + "\n"
        )

        rc = sync_mod.main(
            [
                "adopt",
                "--target",
                str(vault_target),
                "--source",
                str(source_machinery2),
            ]
        )

        assert rc == 2

    def test_rejects_duplicate_targets(
        self, sync_mod, source_machinery2: Path, vault_target: Path
    ) -> None:
        entries = [MAP2_ENTRIES[0], dict(MAP2_ENTRIES[0])]
        (source_machinery2 / "vendor-map.json").write_text(
            json.dumps({"schema": 2, "entries": entries}) + "\n"
        )

        rc = sync_mod.main(
            [
                "adopt",
                "--target",
                str(vault_target),
                "--source",
                str(source_machinery2),
            ]
        )

        assert rc == 2


class TestAdoptJsonKey:
    def test_refuses_when_key_value_differs(
        self, sync_mod, source_machinery2: Path, vault_target: Path, capsys
    ) -> None:
        _seed_identical_target2(source_machinery2, vault_target)
        settings = vault_target / ".claude" / "settings.json"
        settings.write_text(json.dumps({"hooks": {"Stop": []}}, indent=2))

        rc = sync_mod.main(
            [
                "adopt",
                "--target",
                str(vault_target),
                "--source",
                str(source_machinery2),
            ]
        )

        assert rc == 1
        assert not (vault_target / LOCKFILE_RELPATH).exists()
        assert ".claude/settings.json" in capsys.readouterr().out

    def test_refuses_when_key_is_absent(
        self, sync_mod, source_machinery2: Path, vault_target: Path
    ) -> None:
        _seed_identical_target2(source_machinery2, vault_target)
        settings = vault_target / ".claude" / "settings.json"
        settings.write_text(json.dumps({"permissions": {}}, indent=2))

        rc = sync_mod.main(
            [
                "adopt",
                "--target",
                str(vault_target),
                "--source",
                str(source_machinery2),
            ]
        )

        assert rc == 1


def _adopted2(sync_mod, machinery: Path, target: Path) -> None:
    _seed_identical_target2(machinery, target)
    rc = sync_mod.main(
        ["adopt", "--target", str(target), "--source", str(machinery)]
    )
    assert rc == 0, "fixture adopt must succeed"


NEW_HOOKS_VALUE = {
    "Stop": [
        {
            "hooks": [
                {
                    "type": "command",
                    "command": "bash run-hook.sh stop.py --v2",
                    "timeout": 20000,
                }
            ]
        }
    ]
}


class TestUpgradeJsonKey:
    def _publish_new_hooks(self, machinery: Path) -> None:
        (machinery / "rendered" / "claude-settings-hooks.json").write_text(
            json.dumps(NEW_HOOKS_VALUE, indent=2) + "\n"
        )

    def test_apply_rewrites_only_the_key(
        self, sync_mod, source_machinery2: Path, vault_target: Path
    ) -> None:
        _adopted2(sync_mod, source_machinery2, vault_target)
        self._publish_new_hooks(source_machinery2)

        rc = sync_mod.main(
            [
                "upgrade",
                "--target",
                str(vault_target),
                "--source",
                str(source_machinery2),
                "--apply",
            ]
        )

        assert rc == 0
        settings_path = vault_target / ".claude" / "settings.json"
        text = settings_path.read_text()
        settings = json.loads(text)
        assert settings["hooks"] == NEW_HOOKS_VALUE
        assert settings["permissions"] == {"allow": ["Write"]}
        assert list(settings) == ["permissions", "hooks"]
        assert text == json.dumps(settings, indent=2) + "\n"
        lock = _read_lock(vault_target)
        record = lock["files"][".claude/settings.json"]
        assert record["sha256"] == _canonical_sha(NEW_HOOKS_VALUE)
        assert record["kind"] == "json-key"
        assert record["key"] == "hooks"

    def test_refuses_over_local_key_edit(
        self, sync_mod, source_machinery2: Path, vault_target: Path
    ) -> None:
        _adopted2(sync_mod, source_machinery2, vault_target)
        self._publish_new_hooks(source_machinery2)
        settings_path = vault_target / ".claude" / "settings.json"
        local = json.loads(settings_path.read_text())
        local["hooks"] = {"Stop": [], "SessionStart": []}
        settings_path.write_text(json.dumps(local, indent=2) + "\n")
        before = settings_path.read_bytes()

        rc = sync_mod.main(
            [
                "upgrade",
                "--target",
                str(vault_target),
                "--source",
                str(source_machinery2),
                "--apply",
            ]
        )

        assert rc == 1
        assert settings_path.read_bytes() == before

    def test_keep_local_records_canonical_hash_and_sticks(
        self, sync_mod, source_machinery2: Path, vault_target: Path
    ) -> None:
        _adopted2(sync_mod, source_machinery2, vault_target)
        self._publish_new_hooks(source_machinery2)
        settings_path = vault_target / ".claude" / "settings.json"
        local = json.loads(settings_path.read_text())
        local_hooks = {"Stop": [], "SessionStart": []}
        local["hooks"] = local_hooks
        settings_path.write_text(json.dumps(local, indent=2) + "\n")

        rc = sync_mod.main(
            [
                "upgrade",
                "--target",
                str(vault_target),
                "--source",
                str(source_machinery2),
                "--apply",
                "--keep-local",
                ".claude/settings.json",
            ]
        )

        assert rc == 0
        record = _read_lock(vault_target)["files"][".claude/settings.json"]
        assert record["keep_local"] is True
        assert record["sha256"] == _canonical_sha(local_hooks)
        assert record["kind"] == "json-key"

        # Sticky: the next upgrade keeps the local key without re-flagging.
        rc = sync_mod.main(
            [
                "upgrade",
                "--target",
                str(vault_target),
                "--source",
                str(source_machinery2),
                "--apply",
            ]
        )
        assert rc == 0
        assert json.loads(settings_path.read_text())["hooks"] == local_hooks

    def test_restores_missing_file_with_key_only(
        self, sync_mod, source_machinery2: Path, vault_target: Path
    ) -> None:
        _adopted2(sync_mod, source_machinery2, vault_target)
        settings_path = vault_target / ".claude" / "settings.json"
        settings_path.unlink()

        rc = sync_mod.main(
            [
                "upgrade",
                "--target",
                str(vault_target),
                "--source",
                str(source_machinery2),
                "--apply",
            ]
        )

        assert rc == 0
        assert json.loads(settings_path.read_text()) == {"hooks": HOOKS_VALUE}

    def test_restores_missing_key_preserving_siblings(
        self, sync_mod, source_machinery2: Path, vault_target: Path
    ) -> None:
        _adopted2(sync_mod, source_machinery2, vault_target)
        settings_path = vault_target / ".claude" / "settings.json"
        settings_path.write_text(
            json.dumps({"permissions": {"allow": ["Write"]}}, indent=2) + "\n"
        )

        rc = sync_mod.main(
            [
                "upgrade",
                "--target",
                str(vault_target),
                "--source",
                str(source_machinery2),
                "--apply",
            ]
        )

        assert rc == 0
        settings = json.loads(settings_path.read_text())
        assert settings["hooks"] == HOOKS_VALUE
        assert settings["permissions"] == {"allow": ["Write"]}

    def test_unparseable_target_refuses_even_with_force(
        self, sync_mod, source_machinery2: Path, vault_target: Path
    ) -> None:
        """--force may overwrite a local edit, but a json-key rewrite cannot
        preserve sibling keys it cannot parse — refuse rather than destroy."""
        _adopted2(sync_mod, source_machinery2, vault_target)
        settings_path = vault_target / ".claude" / "settings.json"
        settings_path.write_text("{not json")

        rc = sync_mod.main(
            [
                "upgrade",
                "--target",
                str(vault_target),
                "--source",
                str(source_machinery2),
                "--apply",
                "--force",
            ]
        )

        assert rc == 1
        assert settings_path.read_text() == "{not json"

    def test_newly_managed_identical_json_key_locks_without_refusal(
        self, sync_mod, source_machinery2: Path, vault_target: Path
    ) -> None:
        """A live settings.json whose hooks key already matches the rendered
        value plans as skip-identical and enters the lock — the vault-side
        W4 pickup path."""
        _seed_identical_target2(source_machinery2, vault_target)
        _write_lock(
            vault_target,
            {
                ".claude/scripts/alpha.py": {
                    "tier": "managed",
                    "sha256": _sha256(
                        vault_target / ".claude/scripts/alpha.py"
                    ),
                }
            },
        )

        rc = sync_mod.main(
            [
                "upgrade",
                "--target",
                str(vault_target),
                "--source",
                str(source_machinery2),
                "--apply",
            ]
        )

        assert rc == 0
        record = _read_lock(vault_target)["files"][".claude/settings.json"]
        assert record["sha256"] == _canonical_sha(HOOKS_VALUE)


class TestCheckJsonKeyAndScanRoots:
    def _locked_target(self, sync_mod, machinery: Path, target: Path) -> None:
        _adopted2(sync_mod, machinery, target)

    def test_ok_survives_reformatting_of_the_file(
        self, sync_mod, check_mod, source_machinery2: Path, vault_target: Path
    ) -> None:
        self._locked_target(sync_mod, source_machinery2, vault_target)
        settings_path = vault_target / ".claude" / "settings.json"
        reordered = {"hooks": HOOKS_VALUE, "permissions": {"allow": ["Write"]}}
        settings_path.write_text(json.dumps(reordered, sort_keys=True))

        rc = check_mod.main(["--target", str(vault_target), "--strict"])

        assert rc == 0

    def test_local_edit_when_key_value_changes(
        self, sync_mod, check_mod, source_machinery2: Path, vault_target: Path, capsys
    ) -> None:
        self._locked_target(sync_mod, source_machinery2, vault_target)
        settings_path = vault_target / ".claude" / "settings.json"
        settings = json.loads(settings_path.read_text())
        settings["hooks"] = {"Stop": []}
        settings_path.write_text(json.dumps(settings, indent=2))
        capsys.readouterr()

        rc = check_mod.main(["--target", str(vault_target), "--json"])

        assert rc == 0
        report = json.loads(capsys.readouterr().out)
        statuses = {f["path"]: f["status"] for f in report["files"]}
        assert statuses[".claude/settings.json"] == "LOCAL-EDIT"

    def test_missing_when_file_deleted(
        self, sync_mod, check_mod, source_machinery2: Path, vault_target: Path, capsys
    ) -> None:
        self._locked_target(sync_mod, source_machinery2, vault_target)
        (vault_target / ".claude" / "settings.json").unlink()
        capsys.readouterr()

        rc = check_mod.main(["--target", str(vault_target), "--json"])

        assert rc == 0
        report = json.loads(capsys.readouterr().out)
        statuses = {f["path"]: f["status"] for f in report["files"]}
        assert statuses[".claude/settings.json"] == "MISSING"

    def test_untracked_scan_covers_new_managed_roots(
        self, sync_mod, check_mod, source_machinery2: Path, vault_target: Path, capsys
    ) -> None:
        self._locked_target(sync_mod, source_machinery2, vault_target)
        for rogue in (
            ".claude/agents/rogue.md",
            ".codex/agents/rogue.toml",
            ".claude/skills/rogue/SKILL.md",
            ".codex/skills/rogue/SKILL.md",
        ):
            path = vault_target / rogue
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_text("rogue\n")
        junk = vault_target / ".claude" / "skills" / "rogue" / "__pycache__"
        junk.mkdir(parents=True)
        (junk / "x.cpython-312.pyc").write_bytes(b"junk")
        (vault_target / ".codex" / "agents" / ".DS_Store").write_bytes(b"junk")
        capsys.readouterr()

        rc = check_mod.main(["--target", str(vault_target), "--json"])

        assert rc == 0
        report = json.loads(capsys.readouterr().out)
        untracked = {
            f["path"] for f in report["files"] if f["status"] == "UNTRACKED"
        }
        assert untracked == {
            ".claude/agents/rogue.md",
            ".codex/agents/rogue.toml",
            ".claude/skills/rogue/SKILL.md",
            ".codex/skills/rogue/SKILL.md",
        }


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

    def test_dist_ships_wiring_agents_and_rendered_surfaces(self) -> None:
        """W4: the wiring spec, canonical agents, and rendered adapters all
        ride the same machinery copytree into dist (covered by the digest)."""
        dist_machinery = REPO_ROOT / "dist" / "vault-ops" / "machinery"
        assert (dist_machinery / "wiring" / "hooks-spec.json").is_file()
        assert (dist_machinery / "tools" / "wiring_gen.py").is_file()
        assert (dist_machinery / "tools" / "vendor_map_gen.py").is_file()
        for name in ("brag-spotter", "cross-linker", "people-profiler"):
            assert (dist_machinery / "agents" / f"{name}.md").is_file()
            assert (
                dist_machinery / "rendered" / "codex-agents" / f"{name}.toml"
            ).is_file()
        assert (
            dist_machinery / "rendered" / "claude-settings-hooks.json"
        ).is_file()
        assert (dist_machinery / "rendered" / "codex-hooks.json").is_file()

    def test_verbs_are_documented(self) -> None:
        """W5 ships adopt/upgrade/init; only the upstream comparison verb
        remains deliberately deferred, and the module docstring must say so."""
        text = (TOOLS_DIR / "machinery_sync.py").read_text()
        module_doc = ast.get_docstring(ast.parse(text)) or ""
        assert "``init --target" in module_doc
        assert "upstream" in module_doc
        assert "deferred" in module_doc.lower()
