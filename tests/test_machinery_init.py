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
import sys
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parent.parent
MACHINERY_DIR = REPO_ROOT / "plugins" / "workbench" / "machinery"
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
            "target": ".vault/config/vault_scope.py",
        },
    ],
    "trees": [{"source": "templates", "target": "templates"}],
}

# The pre-#687 layout, where scaffold output landed under a managed scan root.
# Upgrade's scaffold-tier handling only ever applies to vaults created before
# that change, so the tests that exercise it opt into this shape explicitly
# rather than the default fixture carrying a layout init no longer writes.
LEGACY_SCAFFOLD_MAP = {
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


def _shipped_tree_targets() -> list[tuple[Path, str]]:
    """(source file, vault-relative target) for every shipped verbatim tree file."""
    data = json.loads(
        (SCAFFOLD_DIR / "scaffold-map.json").read_text(encoding="utf-8")
    )
    pairs: list[tuple[Path, str]] = []
    for tree in data.get("trees", []):
        root = SCAFFOLD_DIR / tree["source"]
        for path in sorted(root.rglob("*")):
            if path.is_file():
                relative = path.relative_to(root).as_posix()
                pairs.append((path, f"{tree['target']}/{relative}"))
    return pairs


def _use_legacy_scaffold_layout(machinery: Path) -> None:
    (machinery / "scaffold" / "scaffold-map.json").write_text(
        json.dumps(LEGACY_SCAFFOLD_MAP, indent=2) + "\n"
    )


def _write_legacy_lock(target: Path, files: dict[str, dict]) -> None:
    """The lockfile a pre-#687 init would have left behind."""
    lock_path = target / LOCKFILE_RELPATH
    lock_path.parent.mkdir(parents=True, exist_ok=True)
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
                "files": files,
            },
            indent=2,
        )
        + "\n"
    )

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
    def test_scaffolds_the_owner_tier_and_nothing_else(
        self, sync_mod, source_machinery: Path, vault_target: Path
    ) -> None:
        """Init renders the owner's files and vendors nothing (#687).

        The managed tier used to be copied in here too. It is not any more:
        the engine, skills, and hooks run from the installed plugin, and a
        second copy in the vault has no updater since `vault-upgrade` was
        retired -- it would be frozen at whatever version was installed on the
        day the vault happened to be created.
        """
        rc = _run_init(sync_mod, source_machinery, vault_target)

        assert rc == 0
        agents = (vault_target / "AGENTS.md").read_text()
        assert "Test Vault" in agents
        assert "brain, work" in agents
        assert "personal, work" in agents
        scope = (vault_target / ".vault/config/vault_scope.py").read_text()
        assert 'GOVERNED_NOTE_DIRS = ("brain", "work",)' in scope
        assert (vault_target / "templates" / "Note.md").read_text() == (
            "{{date}} note\n"
        )
        assert not (vault_target / ".claude/scripts").exists()
        assert not (vault_target / ".claude/skills").exists()

    def test_writes_no_lockfile(
        self, sync_mod, source_machinery: Path, vault_target: Path
    ) -> None:
        """No managed tier means nothing to lock.

        The lockfile records hashes so a later `upgrade` can tell an owner's
        edit from an upstream change. With nothing vendored there is no such
        distinction to draw, and writing one anyway would advertise a
        managed tier the vault does not have.
        """
        assert _run_init(sync_mod, source_machinery, vault_target) == 0

        assert not (vault_target / LOCKFILE_RELPATH).exists()

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
        scope = (target / ".vault/config/vault_scope.py").read_text()
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
        assert "hook trust" in out.lower()
        # The plugin install is the step the vault cannot work without, so the
        # checklist must not present it as optional the way it once did.
        assert "workbench@the-workshop" in out
        assert "REQUIRED" in out
        # Nothing is vendored any more, so there is no drift check to run.
        assert "machinery_check" not in out

    def test_json_output_reports_files_and_checklist(
        self, sync_mod, source_machinery: Path, vault_target: Path, capsys
    ) -> None:
        rc = _run_init(sync_mod, source_machinery, vault_target, "--json")

        assert rc == 0
        report = json.loads(capsys.readouterr().out)
        assert report["verb"] == "init"
        assert report["ok"] is True
        assert "AGENTS.md" in report["scaffold"]
        assert ".vault/config/vault_scope.py" in report["scaffold"]
        assert any(".vault-context" in step for step in report["checklist"])
        # No managed tier is written, so the report must not claim one.
        assert "managed" not in report
        assert "lockfile_written" not in report


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

    def test_init_writes_only_the_scaffold_tier_so_a_collision_is_moot(
        self, sync_mod, source_machinery: Path, vault_target: Path
    ) -> None:
        """Init no longer refuses a collision, because it cannot cause one.

        The disjointness rail guards exactly one thing: no path written by two
        tiers in the same run. Init stopped writing the managed tier (#687), so
        for init the check had become not merely vacuous but wrong -- it
        forbade the scaffold from owning `.claude/settings.json`, a path only
        the stale managed map claims, and one a new vault genuinely needs in
        order to wire its plugin-presence check.

        What must still hold is that the colliding path gets the SCAFFOLD
        content, not the managed content, and that the managed tier is absent
        entirely. Upgrade keeps the refusal -- see the sibling test -- because
        upgrade does write both.
        """
        self._collide(source_machinery)

        rc = _run_init(sync_mod, source_machinery, vault_target)

        assert rc == 0
        written = vault_target / ".claude/scripts/alpha.py"
        assert "Test Vault" in written.read_text(), (
            "the colliding path took managed content; init writes scaffold only"
        )

    def test_upgrade_errors_on_scaffold_managed_collision(
        self, sync_mod, source_machinery: Path, vault_target: Path
    ) -> None:
        """Upgrade writes both tiers, so the rail still applies there."""
        _use_legacy_scaffold_layout(source_machinery)
        _write_legacy_lock(vault_target, {})
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
        """A legacy vault upgrades its managed files and leaves the owner's alone.

        Built by hand rather than through `init`, which no longer produces a
        vendored, locked vault (#687). This is the only shape upgrade will ever
        meet: one created before that change.
        """
        _use_legacy_scaffold_layout(source_machinery)
        scripts = vault_target / ".claude" / "scripts"
        scripts.mkdir(parents=True)
        alpha = scripts / "alpha.py"
        alpha.write_text("print('alpha v1')\n")
        skill = vault_target / ".claude/skills/my-skill/SKILL.md"
        skill.parent.mkdir(parents=True)
        skill.write_text("# my skill\n")
        (vault_target / ".claude" / "settings.json").write_text(
            json.dumps({"hooks": HOOKS_VALUE}, indent=2) + "\n"
        )
        scope = scripts / "vault_scope.py"
        scope.write_text("GOVERNED_NOTE_DIRS = ('mine',)\n")
        _write_legacy_lock(
            vault_target,
            {
                ".claude/scripts/alpha.py": {
                    "tier": "managed",
                    "sha256": _sha256(alpha),
                },
                ".claude/skills/my-skill/SKILL.md": {
                    "tier": "managed",
                    "sha256": _sha256(skill),
                },
                ".claude/scripts/vault_scope.py": {"tier": "scaffold"},
            },
        )
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
        _use_legacy_scaffold_layout(source_machinery)
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
            ".vault/vault.json",
            ".vault/config/vault_scope.py",
        } <= targets
        trees = {t["target"] for t in self._scaffold_map().get("trees", [])}
        assert {"templates", ".vault", ".claude"} <= trees
        note_templates = sorted(
            p.name for p in (SCAFFOLD_DIR / "templates").glob("*.md")
        )
        assert note_templates, "expected vault note templates as scaffold defaults"

    def test_no_scaffold_template_is_an_unrendered_copy_of_a_shipped_default(
        self,
    ) -> None:
        """Every owner-config template must consume an interview answer (#687).

        A template with no placeholders is a byte-copy of a shipped default.
        Scaffolding one hands the owner a frozen fork that shadows that default
        wholesale and never receives a later fix -- and, in `context_paths.py`'s
        case, hardcodes `brain/` into a vault whose taxonomy may not have it.
        An owner who wants one copies the matching `*_defaults.py` out of the
        engine, which dates the fork to their decision instead of to the day
        they happened to run init.
        """
        owner_config = [
            entry
            for entry in self._scaffold_map()["entries"]
            if entry["target"].startswith(".vault/config/")
        ]
        assert owner_config, "expected at least the taxonomy config"
        for entry in owner_config:
            body = (SCAFFOLD_DIR / entry["template"]).read_text(encoding="utf-8")
            assert "${" in body, (
                f"{entry['template']} scaffolds a copy of a shipped default "
                "with nothing parameterized; do not scaffold it"
            )

    def test_scaffold_owns_settings_json_and_the_managed_map_is_stale(
        self,
    ) -> None:
        """The one deliberate overlap with the managed map, and why it is safe.

        A new vault needs `.claude/settings.json` to wire its plugin-presence
        check. The managed map also claims that path, but its claim is dead:
        it carries the pre-cutover hook wiring at `.claude/scripts/run-hook.sh`,
        a script that no longer exists, while the real hooks fire from the
        plugin. Init writes the scaffold tier only, so the overlap cannot
        produce a double write -- see the tier-boundary tests. The managed map
        is stale by its own generator's admission and is replaced in #667.
        """
        vendor_entries = json.loads(
            (MACHINERY_DIR / "vendor-map.json").read_text(encoding="utf-8")
        )["entries"]
        vendor_targets = {e["target"] for e in vendor_entries}
        scaffold_targets = {
            e["target"] for e in self._scaffold_map()["entries"]
        } | {t for _, t in _shipped_tree_targets()}

        assert ".vault/config/vault_scope.py" in scaffold_targets
        assert ".vault/config/vault_scope.py" not in vendor_targets
        # Owner config no longer lands under a managed scan root at all, so
        # the scaffold-under-scan-root lock bookkeeping is legacy-only.
        assert not any(
            t.startswith(".claude/scripts/") for t in scaffold_targets
        )
        assert vendor_targets & scaffold_targets == {".claude/settings.json"}

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
        self, sync_mod, tmp_path: Path, capsys
    ) -> None:
        """End to end against the committed payload: init a fresh vault from
        the real machinery dir and check the owner's surface is complete.

        No `machinery_check --strict` step any more: that verifies a vendored
        managed tier against a lockfile, and init writes neither (#687).
        """
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
        assert "hook" in setup.lower() and "trust" in setup.lower()
        # The new vault's own setup guide must describe the layout it actually
        # has: plugin-installed, not vendored-and-lockfile-checked.
        assert "workbench@the-workshop" in setup
        assert ".vault/vault.json" in setup
        assert "machinery_check" not in setup
        assert "machinery.lock.json" not in setup
        assert "pyyaml" in (target / "pyproject.toml").read_text(encoding="utf-8")
        assert "prune" in (target / ".gitconfig").read_text(encoding="utf-8")
        assert ".vault-context" in (target / ".gitignore").read_text(
            encoding="utf-8"
        )
        scope = (target / ".vault/config/vault_scope.py").read_text(
            encoding="utf-8"
        )
        assert 'GOVERNED_NOTE_DIRS = ("brain", "work", "personal", "org", "perf", "reference",)' in scope
        assert (target / ".vault/vault.json").is_file()
        assert (target / ".vault/check-plugin.sh").is_file()
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

        module_path = target / ".vault/config/vault_scope.py"
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

    def test_owner_written_context_paths_drive_the_loader(
        self, sync_mod, tmp_path: Path, capsys
    ) -> None:
        """The opt-in half of #687's decision has to actually work.

        `context_paths.py` is no longer scaffolded -- it carried no interview
        placeholders, so init was writing a byte-copy of the shipped defaults
        that then shadowed them forever. Not scaffolding it is only defensible
        if an owner who *chooses* to write one still gets it read. That is what
        this pins: a vault with no owner config uses the shipped defaults, and
        one where the owner created `.vault/config/context_paths.py` uses
        theirs.

        Run as subprocesses because `context_loader` reads its config at import
        time; in-process, module caching would decide the result.
        """
        target = tmp_path / "fresh-vault"
        assert (
            sync_mod.main(
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
            == 0
        )
        capsys.readouterr()

        config_dir = target / ".vault" / "config"
        probe = (
            f"import sys; sys.path.insert(0, {str(ENGINE_DIR)!r})\n"
            "import context_loader\n"
            "print(context_loader.NOTE_PATHS['north_star'])\n"
        )

        def _run() -> str:
            env = dict(os.environ)
            # PYTHONPATH is what run-vault-hook.sh sets for the owner tier.
            env["PYTHONPATH"] = str(config_dir)
            env["CLAUDE_PROJECT_DIR"] = str(target)
            result = subprocess.run(
                [sys.executable, "-c", probe],
                capture_output=True,
                text=True,
                env=env,
                cwd=str(target),
            )
            assert result.returncode == 0, result.stderr
            return result.stdout.strip()

        # A vault init produced: no owner override, shipped defaults apply.
        assert _run() == "brain/North Star.md"

        # The owner opts in by writing the file init deliberately did not.
        (config_dir / "context_paths.py").write_text(
            'COMMON_NOTE_PATHS = {"north_star": "brain/Goals.md"}\n'
            "CONTEXT_NOTE_PATHS = {}\n",
            encoding="utf-8",
        )
        assert _run() == "brain/Goals.md"


# ---------------------------------------------------------------------------
# A scaffolded vault has to actually work
# ---------------------------------------------------------------------------

ENGINE_DIR = MACHINERY_DIR / "engine"

# Deliberately unlike the shipped default taxonomy. A test that scaffolded the
# default taxonomy would pass whether or not the owner's file was ever read --
# the same input problem that let #691 live for a release.
INTERVIEW_NOTE_DIRS = "atlas,workshop"
INTERVIEW_TAXONOMY = ("atlas", "workshop")
SHIPPED_DEFAULT_TAXONOMY = (
    "brain",
    "work",
    "personal",
    "org",
    "perf",
    "reference",
)

_RESOLVE_PROBE = """\
import sys
sys.path.insert(0, {engine!r})   # exactly what every vault hook entry point does
import vault_scope_resolved as resolved
print(repr(resolved.GOVERNED_NOTE_DIRS))
"""


def _init_real_vault(sync_mod, target: Path, *extra: str) -> int:
    return sync_mod.main(
        [
            "init",
            "--target",
            str(target),
            "--source",
            str(MACHINERY_DIR),
            "--vault-name",
            "Fresh Vault",
            *extra,
        ]
    )


class TestScaffoldedVaultIsUsable:
    """#687: a vault init produces must be a vault the engine can actually read.

    Every assertion here runs against the committed payload, and the central
    one goes through the real resolution path in a subprocess rather than
    loading the rendered file directly. Loading it directly proves it is valid
    Python; it does not prove any engine will ever find it -- and "valid but
    unreachable" is exactly the state a scaffolded vault was in.
    """

    def test_scaffolded_owner_config_reaches_the_engine(
        self, sync_mod, tmp_path: Path, capsys
    ) -> None:
        """The interview's taxonomy must arrive, not the shipped default.

        This is the assertion #687 asks for, and it is the whole point of the
        issue: a vault whose owner answered the taxonomy question and then had
        that answer silently discarded looks identical to a healthy one.
        """
        target = tmp_path / "fresh-vault"
        assert _init_real_vault(
            sync_mod, target, "--note-dirs", INTERVIEW_NOTE_DIRS
        ) == 0
        capsys.readouterr()

        env = dict(os.environ)
        env.pop("PYTHONPATH", None)
        env["CLAUDE_PROJECT_DIR"] = str(target)
        result = subprocess.run(
            [
                sys.executable,
                "-c",
                _RESOLVE_PROBE.format(engine=str(ENGINE_DIR)),
            ],
            capture_output=True,
            text=True,
            env=env,
            cwd=str(target),
        )

        assert result.returncode == 0, result.stderr
        assert repr(INTERVIEW_TAXONOMY) in result.stdout, (
            "the scaffolded vault's taxonomy did not reach the engine; got "
            f"{result.stdout.strip()!r}"
        )
        assert repr(SHIPPED_DEFAULT_TAXONOMY) not in result.stdout

    def test_scaffolded_vault_is_live_rather_than_inert(
        self, sync_mod, tmp_path: Path, capsys
    ) -> None:
        """`.vault/vault.json` is the switch that makes the hooks run at all.

        `run-vault-hook.sh` walks up for this file and exits before starting an
        interpreter when it is absent. A vault without it is not a degraded
        vault -- it is an inert directory that looks exactly like a healthy one
        until you go looking for the thing that did not happen. Leaving it to a
        checklist step made "silently does nothing" the default outcome of a
        successful init.
        """
        target = tmp_path / "fresh-vault"
        assert _init_real_vault(sync_mod, target) == 0
        capsys.readouterr()

        marker = target / ".vault" / "vault.json"
        assert marker.is_file(), "init produced a vault whose hooks never fire"
        data = json.loads(marker.read_text(encoding="utf-8"))
        assert data["plugin"] == "workbench@the-workshop"
        assert data["min_plugin_version"], "no floor for the staleness check"

    def test_plugin_presence_check_is_shipped_and_wired(
        self, sync_mod, tmp_path: Path, capsys
    ) -> None:
        """Once the hooks ship in a plugin, the failure mode is silence.

        The plugin gets uninstalled or downgraded and the vault simply stops
        auto-committing, loading context, and validating frontmatter, with
        nothing to notice. Shipping the check but leaving it unwired would
        reproduce the same silence one level up.
        """
        target = tmp_path / "fresh-vault"
        assert _init_real_vault(sync_mod, target) == 0
        capsys.readouterr()

        check = target / ".vault" / "check-plugin.sh"
        assert check.is_file()
        settings = json.loads(
            (target / ".claude" / "settings.json").read_text(encoding="utf-8")
        )
        wired = json.dumps(settings.get("hooks", {}))
        assert "check-plugin.sh" in wired, (
            f"the presence check ships but nothing runs it: {wired}"
        )

    def test_owner_config_holds_only_what_the_interview_parameterized(
        self, sync_mod, tmp_path: Path, capsys
    ) -> None:
        """`.vault/config/` starts with exactly one file, per #650.

        `vault_scope.py` is the only template that consumes an interview
        answer. The others carry no placeholders at all -- they are byte-copies
        of the shipped defaults, and scaffolding a copy creates a frozen fork
        that shadows those defaults wholesale and never receives a later fix.
        `context_paths.py` is the clearest case: it hardcodes `brain/`, which
        is simply wrong in a vault whose taxonomy has no `brain/`.

        An owner who wants one copies the matching `*_defaults.py` out of the
        engine and edits it. That is opt-in, and it is dated by their choice
        rather than by the day they ran init.
        """
        target = tmp_path / "fresh-vault"
        assert _init_real_vault(
            sync_mod, target, "--note-dirs", INTERVIEW_NOTE_DIRS
        ) == 0
        capsys.readouterr()

        config_dir = target / ".vault" / "config"
        assert sorted(p.name for p in config_dir.iterdir()) == ["vault_scope.py"]

    def test_engine_recognises_a_scaffolded_vault_with_any_taxonomy(
        self, sync_mod, tmp_path: Path, capsys
    ) -> None:
        """The engine must agree with the hook guard about what a vault is.

        `find_vault_root` used to key on `CLAUDE.md` plus a `brain/` + `perf/`
        signature. Init creates no note directories at all, so that signature
        could never match a fresh vault -- every one reported "not in a vault
        directory" on its first session, whatever taxonomy its owner chose.
        The taxonomy here deliberately contains neither `brain` nor `perf`, so
        a passing assertion cannot be an accident of the default answers.
        """
        target = tmp_path / "fresh-vault"
        assert _init_real_vault(
            sync_mod, target, "--note-dirs", INTERVIEW_NOTE_DIRS
        ) == 0
        capsys.readouterr()

        probe = (
            f"import sys; sys.path.insert(0, {str(ENGINE_DIR)!r})\n"
            "import vault_utils\n"
            f"print(vault_utils.find_vault_root(__import__('pathlib').Path({str(target)!r})))\n"
        )
        env = dict(os.environ)
        env.pop("PYTHONPATH", None)
        result = subprocess.run(
            [sys.executable, "-c", probe],
            capture_output=True,
            text=True,
            env=env,
            cwd=str(target),
        )

        assert result.returncode == 0, result.stderr
        assert result.stdout.strip() == str(target), (
            "the engine does not recognise the vault init just created: "
            f"{result.stdout.strip()!r}"
        )

    def test_machine_local_state_the_hooks_write_is_not_synced(
        self, sync_mod, tmp_path: Path, capsys
    ) -> None:
        """A vault must not start committing its own per-machine state.

        The vault auto-commits, so anything the hooks write that is not
        gitignored gets committed on the first session and then conflicts on
        every two-machine sync. `plugin-state.json` is the sharpest case: it
        records THIS machine's plugin cache path, so pulled onto a machine
        without the plugin it reports the plugin present when it is not --
        and `check-plugin.sh` reads exactly that file to decide.
        """
        target = tmp_path / "fresh-vault"
        assert _init_real_vault(sync_mod, target) == 0
        capsys.readouterr()

        ignored = (target / ".gitignore").read_text(encoding="utf-8")
        for path in (
            ".vault/plugin-state.json",
            ".vault/.plugin-miss-count",
            ".claude/data/*",
            ".claude/worktrees/",
            ".claude/settings.local.json",
            ".brain/notebook-*.md",
            ".brain/gardener-*.md",
        ):
            assert path in ignored, f"the hooks write {path} and it would sync"

    def test_init_vendors_no_engine_copy(
        self, sync_mod, tmp_path: Path, capsys
    ) -> None:
        """The engine ships in the plugin; a copy in the vault is dead weight.

        It also has no updater: `vault-upgrade` was retired, so a vendored
        engine is frozen at the version that happened to be installed the day
        the vault was created, sitting beside the live one and drifting.
        """
        target = tmp_path / "fresh-vault"
        assert _init_real_vault(sync_mod, target) == 0
        capsys.readouterr()

        assert not (target / ".claude" / "scripts").exists(), (
            "init vendored an engine copy the vault does not run and nothing "
            "maintains"
        )
