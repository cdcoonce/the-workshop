"""The ``init`` verb + scaffold tier for the vault machinery payload (W5).

Covers the three shipped pieces:

- ``machinery/scaffold/`` — the scaffold templates (``scaffold-map.json``
  plus ``*.tmpl`` files and the verbatim ``templates/`` note-template tree)
  that ``init`` renders into a brand-new vault.
- ``machinery_sync.py init`` — non-interactive scaffolding of a fresh vault:
  refuse a non-empty target, render every scaffold template, vendor the full
  managed tier, write the lockfile, ``git init`` + initial commit, print the
  post-init checklist.
- The scaffold/managed tier boundary — scaffold outputs may never collide
  with managed vendor-map targets (validated at map load), scaffold outputs
  under managed scan roots are lock-recorded as ``tier: "scaffold"`` (so the
  UNTRACKED scan stays clean while upgrade never touches them), and upgrade
  migrates a formerly managed scaffold-owned file to the scaffold tier.

Every test is hermetic against tmp_path fixtures — none writes a real vault.
The shipped-payload tests read the committed machinery dir read-only and
render into tmp_path.
"""

from __future__ import annotations

import hashlib
import importlib.util
import json
import os
import shutil
import subprocess
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parent.parent
MACHINERY_DIR = REPO_ROOT / "presets" / "vault-ops" / "machinery"
TOOLS_DIR = MACHINERY_DIR / "tools"
SCAFFOLD_DIR = MACHINERY_DIR / "scaffold"

LOCKFILE_RELPATH = ".vault/machinery.lock.json"

GIT_ENV = {
    **os.environ,
    "GIT_AUTHOR_NAME": "t",
    "GIT_AUTHOR_EMAIL": "t@t",
    "GIT_COMMITTER_NAME": "t",
    "GIT_COMMITTER_EMAIL": "t@t",
    "GIT_CONFIG_GLOBAL": "/dev/null",
    "GIT_CONFIG_SYSTEM": "/dev/null",
}


def _load_tool(name: str):
    path = TOOLS_DIR / f"{name}.py"
    spec = importlib.util.spec_from_file_location(f"_machinery_{name}", path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


@pytest.fixture
def sync_mod():
    return _load_tool("machinery_sync")


@pytest.fixture
def check_mod():
    return _load_tool("machinery_check")


def _sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _read_lock(target: Path) -> dict:
    return json.loads((target / LOCKFILE_RELPATH).read_text())


# ---------------------------------------------------------------------------
# Fixture workshop machinery with a scaffold payload
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

MAP_ENTRIES = [
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

SCAFFOLD_MAP = {
    "schema": 1,
    "entries": [
        {"template": "AGENTS.md.tmpl", "target": "AGENTS.md"},
        {
            "template": "vault_scope.py.tmpl",
            "target": ".claude/scripts/vault_scope.py",
        },
    ],
    "trees": [{"source": "templates", "target": "templates"}],
}

AGENTS_TMPL = (
    "# ${vault_name} — Operating Manual\n\n"
    "Note dirs: ${note_dirs_csv}\n"
    "Contexts: ${contexts_csv}\n"
)

VAULT_SCOPE_TMPL = "GOVERNED_NOTE_DIRS = (${governed_note_dirs})\n"


@pytest.fixture
def source_machinery(tmp_path: Path) -> Path:
    """A schema-2 workshop machinery dir carrying a scaffold payload."""
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
    scaffold = machinery / "scaffold"
    (scaffold / "templates").mkdir(parents=True)
    (scaffold / "AGENTS.md.tmpl").write_text(AGENTS_TMPL)
    (scaffold / "vault_scope.py.tmpl").write_text(VAULT_SCOPE_TMPL)
    (scaffold / "templates" / "Note.md").write_text("{{date}} note\n")
    (scaffold / "scaffold-map.json").write_text(
        json.dumps(SCAFFOLD_MAP, indent=2) + "\n"
    )
    (machinery / "vendor-map.json").write_text(
        json.dumps({"schema": 2, "entries": MAP_ENTRIES}, indent=2) + "\n"
    )
    (preset / "manifest.json").write_text(
        json.dumps({"name": "vault-ops", "version": "9.9.9"}) + "\n"
    )
    return machinery


@pytest.fixture
def vault_target(tmp_path: Path) -> Path:
    target = tmp_path / "vault"
    target.mkdir()
    return target


def _run_init(sync_mod, machinery: Path, target: Path, *extra: str) -> int:
    return sync_mod.main(
        [
            "init",
            "--target",
            str(target),
            "--source",
            str(machinery),
            "--vault-name",
            "Test Vault",
            "--note-dirs",
            "brain,work",
            "--contexts",
            "personal,work",
            *extra,
        ]
    )


# ---------------------------------------------------------------------------
# init: scaffold + vendor + lock
# ---------------------------------------------------------------------------


class TestInit:
    def test_scaffolds_vendors_and_locks(
        self, sync_mod, source_machinery: Path, vault_target: Path
    ) -> None:
        rc = _run_init(sync_mod, source_machinery, vault_target)

        assert rc == 0
        agents = (vault_target / "AGENTS.md").read_text()
        assert "Test Vault" in agents
        assert "brain, work" in agents
        assert "personal, work" in agents
        scope = (vault_target / ".claude/scripts/vault_scope.py").read_text()
        assert 'GOVERNED_NOTE_DIRS = ("brain", "work",)' in scope
        assert (vault_target / "templates" / "Note.md").read_text() == (
            "{{date}} note\n"
        )
        assert (
            vault_target / ".claude/scripts/alpha.py"
        ).read_text() == "print('alpha v1')\n"
        assert (
            vault_target / ".claude/skills/my-skill/SKILL.md"
        ).read_text() == "# my skill\n"
        settings = json.loads(
            (vault_target / ".claude/settings.json").read_text()
        )
        assert settings["hooks"] == HOOKS_VALUE

    def test_lockfile_covers_managed_and_scan_root_scaffold_only(
        self, sync_mod, source_machinery: Path, vault_target: Path
    ) -> None:
        rc = _run_init(sync_mod, source_machinery, vault_target)

        assert rc == 0
        lock = _read_lock(vault_target)
        assert lock["source"]["preset"] == "vault-ops"
        assert lock["source"]["version"] == "9.9.9"
        files = lock["files"]
        assert files[".claude/scripts/alpha.py"]["tier"] == "managed"
        assert files[".claude/scripts/alpha.py"]["sha256"] == _sha256(
            vault_target / ".claude/scripts/alpha.py"
        )
        scaffold_entry = files[".claude/scripts/vault_scope.py"]
        assert scaffold_entry["tier"] == "scaffold"
        assert "sha256" not in scaffold_entry
        # Scaffold outputs outside the managed scan roots stay owner-owned
        # and unlocked.
        assert "AGENTS.md" not in files
        assert "templates/Note.md" not in files

    def test_check_strict_is_clean_after_init(
        self, sync_mod, check_mod, source_machinery: Path, vault_target: Path
    ) -> None:
        assert _run_init(sync_mod, source_machinery, vault_target) == 0

        assert check_mod.main(["--target", str(vault_target), "--strict"]) == 0

    def test_scaffold_edit_stays_clean_but_managed_edit_is_drift(
        self, sync_mod, check_mod, source_machinery: Path, vault_target: Path
    ) -> None:
        """Owner edits to a scaffold file are theirs; managed files drift."""
        assert _run_init(sync_mod, source_machinery, vault_target) == 0
        scope = vault_target / ".claude/scripts/vault_scope.py"
        scope.write_text(scope.read_text() + "# my taxonomy tweak\n")

        assert check_mod.main(["--target", str(vault_target), "--strict"]) == 0

        managed = vault_target / ".claude/scripts/alpha.py"
        managed.write_text("print('edited')\n")
        assert check_mod.main(["--target", str(vault_target), "--strict"]) == 1

    def test_missing_scaffold_file_reports_missing(
        self, sync_mod, check_mod, source_machinery: Path, vault_target: Path
    ) -> None:
        assert _run_init(sync_mod, source_machinery, vault_target) == 0
        (vault_target / ".claude/scripts/vault_scope.py").unlink()

        assert check_mod.main(["--target", str(vault_target), "--strict"]) == 1

    def test_default_parameters(
        self, sync_mod, source_machinery: Path, tmp_path: Path
    ) -> None:
        """No flags: vault name defaults to the dir name, note dirs and
        contexts to the canonical taxonomy."""
        target = tmp_path / "my-new-vault"
        rc = sync_mod.main(
            ["init", "--target", str(target), "--source", str(source_machinery)]
        )

        assert rc == 0
        assert "my-new-vault" in (target / "AGENTS.md").read_text()
        scope = (target / ".claude/scripts/vault_scope.py").read_text()
        assert (
            '("brain", "work", "personal", "org", "perf", "reference",)' in scope
        )

    def test_prints_post_init_checklist(
        self, sync_mod, source_machinery: Path, vault_target: Path, capsys
    ) -> None:
        assert _run_init(sync_mod, source_machinery, vault_target) == 0

        out = capsys.readouterr().out
        assert ".vault-context" in out
        assert "include.path" in out
        assert "machinery_check" in out
        assert "--strict" in out
        assert "hook trust" in out.lower()
        assert "plugin" in out.lower()

    def test_json_output_reports_files_and_checklist(
        self, sync_mod, source_machinery: Path, vault_target: Path, capsys
    ) -> None:
        rc = _run_init(sync_mod, source_machinery, vault_target, "--json")

        assert rc == 0
        report = json.loads(capsys.readouterr().out)
        assert report["verb"] == "init"
        assert report["ok"] is True
        assert "AGENTS.md" in report["scaffold"]
        assert ".claude/scripts/alpha.py" in report["managed"]
        assert any(".vault-context" in step for step in report["checklist"])


# ---------------------------------------------------------------------------
# init: refusals and git behavior
# ---------------------------------------------------------------------------


class TestInitTargetSafety:
    def test_refuses_non_empty_target(
        self, sync_mod, source_machinery: Path, vault_target: Path
    ) -> None:
        (vault_target / "existing.md").write_text("precious\n")

        rc = _run_init(sync_mod, source_machinery, vault_target)

        assert rc == 1
        assert not (vault_target / "AGENTS.md").exists()
        assert not (vault_target / LOCKFILE_RELPATH).exists()
        assert (vault_target / "existing.md").read_text() == "precious\n"

    def test_force_empty_check_overrides_refusal(
        self, sync_mod, source_machinery: Path, vault_target: Path
    ) -> None:
        (vault_target / "existing.md").write_text("precious\n")

        rc = _run_init(
            sync_mod, source_machinery, vault_target, "--force-empty-check"
        )

        assert rc == 0
        assert (vault_target / "AGENTS.md").exists()
        assert (vault_target / "existing.md").read_text() == "precious\n"

    def test_creates_missing_target_directory(
        self, sync_mod, source_machinery: Path, tmp_path: Path
    ) -> None:
        target = tmp_path / "not" / "yet" / "there"

        assert _run_init(sync_mod, source_machinery, target) == 0
        assert (target / "AGENTS.md").exists()

    def test_rejects_hostile_note_dir_token(
        self, sync_mod, source_machinery: Path, vault_target: Path
    ) -> None:
        rc = sync_mod.main(
            [
                "init",
                "--target",
                str(vault_target),
                "--source",
                str(source_machinery),
                "--note-dirs",
                'brain,../evil"',
            ]
        )

        assert rc == 2
        assert not (vault_target / "AGENTS.md").exists()

    def test_requires_a_scaffold_payload(
        self, sync_mod, source_machinery: Path, vault_target: Path
    ) -> None:
        shutil.rmtree(source_machinery / "scaffold")

        assert _run_init(sync_mod, source_machinery, vault_target) == 2


class TestInitGit:
    def test_initializes_git_with_initial_commit(
        self, sync_mod, source_machinery: Path, vault_target: Path, monkeypatch
    ) -> None:
        for key, value in GIT_ENV.items():
            monkeypatch.setenv(key, value)

        assert _run_init(sync_mod, source_machinery, vault_target) == 0

        assert (vault_target / ".git").is_dir()
        log = subprocess.run(
            ["git", "-C", str(vault_target), "log", "--oneline"],
            capture_output=True,
            text=True,
            env=GIT_ENV,
        )
        assert log.returncode == 0
        assert len(log.stdout.strip().splitlines()) == 1
        status = subprocess.run(
            ["git", "-C", str(vault_target), "status", "--porcelain"],
            capture_output=True,
            text=True,
            env=GIT_ENV,
        )
        assert status.stdout.strip() == ""

    def test_empty_git_repo_target_is_not_reinitialized(
        self, sync_mod, source_machinery: Path, vault_target: Path, monkeypatch
    ) -> None:
        """A freshly git-init'd empty dir counts as empty; init neither
        refuses nor commits into a repo it did not create."""
        for key, value in GIT_ENV.items():
            monkeypatch.setenv(key, value)
        subprocess.run(
            ["git", "-C", str(vault_target), "init", "-q"],
            check=True,
            env=GIT_ENV,
        )

        assert _run_init(sync_mod, source_machinery, vault_target) == 0

        head = subprocess.run(
            ["git", "-C", str(vault_target), "rev-parse", "--verify", "HEAD"],
            capture_output=True,
            text=True,
            env=GIT_ENV,
        )
        assert head.returncode != 0, "init must not commit into an existing repo"


# ---------------------------------------------------------------------------
# Tier boundary: scaffold targets may never collide with managed targets
# ---------------------------------------------------------------------------


class TestTierBoundary:
    def _collide(self, machinery: Path) -> None:
        colliding = dict(SCAFFOLD_MAP)
        colliding["entries"] = [
            {"template": "AGENTS.md.tmpl", "target": ".claude/scripts/alpha.py"}
        ]
        (machinery / "scaffold" / "scaffold-map.json").write_text(
            json.dumps(colliding) + "\n"
        )

    def test_init_errors_on_scaffold_managed_collision(
        self, sync_mod, source_machinery: Path, vault_target: Path
    ) -> None:
        self._collide(source_machinery)

        rc = _run_init(sync_mod, source_machinery, vault_target)

        assert rc == 2
        assert not (vault_target / ".claude/scripts/alpha.py").exists()

    def test_upgrade_errors_on_scaffold_managed_collision(
        self, sync_mod, source_machinery: Path, vault_target: Path
    ) -> None:
        assert _run_init(sync_mod, source_machinery, vault_target) == 0
        self._collide(source_machinery)

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

    def test_scan_roots_match_the_check_tool(self, sync_mod, check_mod) -> None:
        """Both vendored tools must agree on what a managed scan root is."""
        assert tuple(sync_mod.MANAGED_SCAN_ROOTS) == tuple(
            check_mod.MANAGED_SCAN_ROOTS
        )


# ---------------------------------------------------------------------------
# Upgrade lifecycle around the scaffold tier
# ---------------------------------------------------------------------------


class TestUpgradeScaffoldTier:
    def test_upgrade_never_touches_a_scaffold_file(
        self, sync_mod, source_machinery: Path, vault_target: Path
    ) -> None:
        assert _run_init(sync_mod, source_machinery, vault_target) == 0
        scope = vault_target / ".claude/scripts/vault_scope.py"
        scope.write_text("GOVERNED_NOTE_DIRS = ('mine',)\n")
        (source_machinery / "scaffold" / "vault_scope.py.tmpl").write_text(
            "GOVERNED_NOTE_DIRS = (${governed_note_dirs})  # v2\n"
        )
        (source_machinery / "engine" / "alpha.py").write_text(
            "print('alpha v2')\n"
        )

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
        assert scope.read_text() == "GOVERNED_NOTE_DIRS = ('mine',)\n"
        assert (
            vault_target / ".claude/scripts/alpha.py"
        ).read_text() == "print('alpha v2')\n"
        assert _read_lock(vault_target)["files"][
            ".claude/scripts/vault_scope.py"
        ] == {"tier": "scaffold"}

    def test_upgrade_migrates_formerly_managed_scaffold_file(
        self, sync_mod, check_mod, source_machinery: Path, vault_target: Path
    ) -> None:
        """A vault locked under the old map (vault_scope managed) upgrades
        cleanly: the file is left alone and re-tiered as scaffold."""
        scripts = vault_target / ".claude" / "scripts"
        scripts.mkdir(parents=True)
        alpha = scripts / "alpha.py"
        alpha.write_text("print('alpha v1')\n")
        scope = scripts / "vault_scope.py"
        scope.write_text("GOVERNED_NOTE_DIRS = ('legacy',)\n")
        skill = vault_target / ".claude/skills/my-skill/SKILL.md"
        skill.parent.mkdir(parents=True)
        skill.write_text("# my skill\n")
        settings = vault_target / ".claude" / "settings.json"
        settings.write_text(json.dumps({"hooks": HOOKS_VALUE}, indent=2) + "\n")
        lock_path = vault_target / LOCKFILE_RELPATH
        lock_path.parent.mkdir(parents=True)
        lock_path.write_text(
            json.dumps(
                {
                    "schema": 1,
                    "source": {
                        "repo": "the-workshop",
                        "preset": "vault-ops",
                        "version": "1.2.0",
                        "ref": None,
                    },
                    "generated_at": "2026-07-25T00:00:00Z",
                    "files": {
                        ".claude/scripts/alpha.py": {
                            "tier": "managed",
                            "sha256": _sha256(alpha),
                        },
                        ".claude/scripts/vault_scope.py": {
                            "tier": "managed",
                            "sha256": _sha256(scope),
                        },
                        ".claude/skills/my-skill/SKILL.md": {
                            "tier": "managed",
                            "sha256": _sha256(skill),
                        },
                    },
                },
                indent=2,
            )
            + "\n"
        )

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
        assert scope.read_text() == "GOVERNED_NOTE_DIRS = ('legacy',)\n"
        lock = _read_lock(vault_target)
        assert lock["files"][".claude/scripts/vault_scope.py"] == {
            "tier": "scaffold"
        }
        assert check_mod.main(["--target", str(vault_target), "--strict"]) == 0


# ---------------------------------------------------------------------------
# Shipped payload: the real scaffold + vendor map
# ---------------------------------------------------------------------------


class TestShippedScaffold:
    def _scaffold_map(self) -> dict:
        return json.loads(
            (SCAFFOLD_DIR / "scaffold-map.json").read_text(encoding="utf-8")
        )

    def test_scaffold_map_templates_exist(self) -> None:
        data = self._scaffold_map()
        assert data["schema"] == 1
        for entry in data["entries"]:
            assert (SCAFFOLD_DIR / entry["template"]).is_file()
        for tree in data.get("trees", []):
            assert (SCAFFOLD_DIR / tree["source"]).is_dir()

    def test_scaffold_covers_the_specified_surface(self) -> None:
        targets = {e["target"] for e in self._scaffold_map()["entries"]}
        assert {
            "AGENTS.md",
            "CLAUDE.md",
            "SETUP.md",
            ".gitconfig",
            ".gitignore",
            "pyproject.toml",
            ".claude/scripts/vault_scope.py",
        } <= targets
        trees = {t["target"] for t in self._scaffold_map().get("trees", [])}
        assert "templates" in trees
        note_templates = sorted(
            p.name for p in (SCAFFOLD_DIR / "templates").glob("*.md")
        )
        assert note_templates, "expected vault note templates as scaffold defaults"

    def test_scaffold_targets_disjoint_from_vendor_map(self) -> None:
        vendor_targets = {
            e["target"]
            for e in json.loads(
                (MACHINERY_DIR / "vendor-map.json").read_text(encoding="utf-8")
            )["entries"]
        }
        scaffold_targets = {
            e["target"] for e in self._scaffold_map()["entries"]
        }
        assert vendor_targets.isdisjoint(scaffold_targets)
        # The point of the boundary: vault_scope.py is scaffold-owned now.
        assert ".claude/scripts/vault_scope.py" in scaffold_targets
        assert ".claude/scripts/vault_scope.py" not in vendor_targets

    def test_vendor_map_ships_the_lifecycle_tools(self) -> None:
        entries = json.loads(
            (MACHINERY_DIR / "vendor-map.json").read_text(encoding="utf-8")
        )["entries"]
        tools = {
            e["source"]: e["target"]
            for e in entries
            if e["source"].startswith("tools/")
        }
        assert tools == {
            "tools/machinery_check.py": ".claude/scripts/machinery_check.py",
            "tools/machinery_sync.py": ".claude/scripts/machinery_sync.py",
        }

    def test_real_init_produces_a_clean_vault(
        self, sync_mod, check_mod, tmp_path: Path, capsys
    ) -> None:
        """End to end against the committed payload: init a fresh vault from
        the real machinery dir, then machinery_check --strict passes."""
        target = tmp_path / "fresh-vault"
        rc = sync_mod.main(
            [
                "init",
                "--target",
                str(target),
                "--source",
                str(MACHINERY_DIR),
                "--vault-name",
                "Fresh Vault",
            ]
        )

        assert rc == 0
        capsys.readouterr()
        assert check_mod.main(["--target", str(target), "--strict"]) == 0

        agents = (target / "AGENTS.md").read_text(encoding="utf-8")
        assert "Fresh Vault" in agents
        for heading in (
            "## Philosophy",
            "## Folder Structure",
            "## Frontmatter Rules (Enforced)",
            "## Wikilink Rules",
            "## Session Behavior",
            "## Constraints",
        ):
            assert heading in agents, f"AGENTS.md.tmpl lost {heading}"
        assert "AGENTS.md" in (target / "CLAUDE.md").read_text(encoding="utf-8")
        setup = (target / "SETUP.md").read_text(encoding="utf-8")
        assert ".vault-context" in setup
        assert "include.path" in setup
        assert "machinery_check" in setup
        assert "hook" in setup.lower() and "trust" in setup.lower()
        assert "pyyaml" in (target / "pyproject.toml").read_text(encoding="utf-8")
        assert "prune" in (target / ".gitconfig").read_text(encoding="utf-8")
        assert ".vault-context" in (target / ".gitignore").read_text(
            encoding="utf-8"
        )
        scope = (target / ".claude/scripts/vault_scope.py").read_text(
            encoding="utf-8"
        )
        assert 'GOVERNED_NOTE_DIRS = ("brain", "work", "personal", "org", "perf", "reference",)' in scope
        assert (target / ".claude/scripts/machinery_check.py").is_file()
        assert (target / ".claude/scripts/machinery_sync.py").is_file()
        assert list((target / "templates").glob("*.md"))

    def test_scaffolded_vault_scope_module_is_importable(
        self, sync_mod, tmp_path: Path
    ) -> None:
        """The rendered vault_scope.py must be real Python exposing the API
        the vendored engine scripts import."""
        target = tmp_path / "fresh-vault"
        assert (
            sync_mod.main(
                [
                    "init",
                    "--target",
                    str(target),
                    "--source",
                    str(MACHINERY_DIR),
                    "--note-dirs",
                    "brain,notes",
                ]
            )
            == 0
        )

        module_path = target / ".claude/scripts/vault_scope.py"
        spec = importlib.util.spec_from_file_location(
            "_scaffolded_vault_scope", module_path
        )
        module = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(module)
        assert module.GOVERNED_NOTE_DIRS == ("brain", "notes")
        for name in (
            "is_governed_markdown_note",
            "is_graph_markdown_note",
            "iter_graph_markdown_notes",
            "iter_governed_markdown_notes",
            "is_transient_note",
        ):
            assert callable(getattr(module, name))

    def test_dist_ships_the_scaffold_payload(self) -> None:
        dist_scaffold = (
            REPO_ROOT / "dist" / "vault-ops" / "machinery" / "scaffold"
        )
        assert (dist_scaffold / "scaffold-map.json").is_file()
        assert (dist_scaffold / "AGENTS.md.tmpl").is_file()
        assert (dist_scaffold / "templates").is_dir()
