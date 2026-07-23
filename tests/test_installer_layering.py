"""The persona package's layering invariant, enforced at the install path.

A persona package is three layers: a plugin-managed **base**, a local **tuning**
overlay, and a **private** layer (memory, preferences). The whole design rests on
one promise — a base update never touches `local/` — and until now nothing
enforced it. `package-format.md` says outright: do not ship a change to the
install/update path without this test passing.

`install()` rebuilds the destination on every run (`rmtree` then `copytree`), so
an update silently took the owner's tuning and memory with it.
"""

from __future__ import annotations

import json
from pathlib import Path

from scripts.installer.adapters import ClaudeCodeAdapter
from scripts.installer.bundle import Bundle
from scripts.installer.report import Scope


def _write(path: Path, text: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text, encoding="utf-8")


def _advisor_package(root: Path, name: str, *, version: str, spec: str) -> Path:
    """A minimal package shaped like an advisor persona bundle."""
    _write(
        root / name / ".claude-plugin" / "plugin.json",
        json.dumps({"name": name, "version": version}),
    )
    _write(root / name / "skills" / "advisor" / "SKILL.md", spec)
    return root / name


def _owner_overlay(install: Path) -> dict[Path, str]:
    """The `local/` skeleton from package-format.md, with owner content."""
    files = {
        install / "local" / "tuning.md": "# Tuning\n\nBe terser about roadmaps.\n",
        install / "local" / "preferences.md": "# Preferences\n\nNo emoji.\n",
        install / "local" / "memory" / "MEMORY.md": "- [Q3 plan](decisions/q3.md)\n",
        install
        / "local"
        / "memory"
        / "decisions"
        / "q3.md": "Chose the narrow launch.\n",
    }
    for path, text in files.items():
        _write(path, text)
    return files


def _install(presets: Path, name: str, target: Path) -> Path:
    adapter = ClaudeCodeAdapter()
    adapter.install(Bundle.load(presets, name), target, Scope.PROJECT)
    return target / ".claude" / "plugins" / name


class TestPersonaLayering:
    def test_local_overlay_survives_a_base_update(self, tmp_path: Path) -> None:
        presets = tmp_path / "presets"
        target = tmp_path / "repo"
        target.mkdir()
        _advisor_package(presets, "advisor-x", version="1.0.0", spec="# v1 spec\n")

        install = _install(presets, "advisor-x", target)
        overlay = _owner_overlay(install)

        # The base update: same package, new version and new base content.
        _advisor_package(presets, "advisor-x", version="2.0.0", spec="# v2 spec\n")
        _install(presets, "advisor-x", target)

        for path, text in overlay.items():
            assert path.exists(), f"{path.name} did not survive the update"
            assert path.read_text() == text, f"{path.name} was rewritten"

    def test_the_base_update_actually_applied(self, tmp_path: Path) -> None:
        """Preserving `local/` must not come at the cost of not updating."""
        presets = tmp_path / "presets"
        target = tmp_path / "repo"
        target.mkdir()
        _advisor_package(presets, "advisor-x", version="1.0.0", spec="# v1 spec\n")
        install = _install(presets, "advisor-x", target)
        _owner_overlay(install)

        _advisor_package(presets, "advisor-x", version="2.0.0", spec="# v2 spec\n")
        _install(presets, "advisor-x", target)

        assert (install / "skills" / "advisor" / "SKILL.md").read_text() == "# v2 spec\n"
        plugin = json.loads((install / ".claude-plugin" / "plugin.json").read_text())
        assert plugin["version"] == "2.0.0"

    def test_base_files_removed_upstream_are_gone_after_update(
        self, tmp_path: Path
    ) -> None:
        """Preservation is scoped to `local/`; the base is still rebuilt."""
        presets = tmp_path / "presets"
        target = tmp_path / "repo"
        target.mkdir()
        _advisor_package(presets, "advisor-x", version="1.0.0", spec="# v1 spec\n")
        _write(presets / "advisor-x" / "skills" / "retired" / "SKILL.md", "# gone\n")
        install = _install(presets, "advisor-x", target)
        _owner_overlay(install)
        assert (install / "skills" / "retired").exists()

        (presets / "advisor-x" / "skills" / "retired" / "SKILL.md").unlink()
        (presets / "advisor-x" / "skills" / "retired").rmdir()
        _install(presets, "advisor-x", target)

        assert not (install / "skills" / "retired").exists()

    def test_update_without_an_overlay_is_unaffected(self, tmp_path: Path) -> None:
        presets = tmp_path / "presets"
        target = tmp_path / "repo"
        target.mkdir()
        _advisor_package(presets, "advisor-x", version="1.0.0", spec="# v1 spec\n")
        install = _install(presets, "advisor-x", target)

        _advisor_package(presets, "advisor-x", version="2.0.0", spec="# v2 spec\n")
        _install(presets, "advisor-x", target)

        assert not (install / "local").exists()
        assert (install / "skills" / "advisor" / "SKILL.md").read_text() == "# v2 spec\n"

    def test_owner_overlay_wins_over_a_local_dir_shipped_in_the_base(
        self, tmp_path: Path
    ) -> None:
        """`local/` is machine-only by construction; a packaged one must not
        overwrite the owner's. Tuning wins over base — that is the invariant."""
        presets = tmp_path / "presets"
        target = tmp_path / "repo"
        target.mkdir()
        _advisor_package(presets, "advisor-x", version="1.0.0", spec="# v1 spec\n")
        install = _install(presets, "advisor-x", target)
        overlay = _owner_overlay(install)

        _advisor_package(presets, "advisor-x", version="2.0.0", spec="# v2 spec\n")
        _write(presets / "advisor-x" / "local" / "tuning.md", "# SHIPPED DEFAULT\n")
        _install(presets, "advisor-x", target)

        tuning = install / "local" / "tuning.md"
        assert tuning.read_text() == overlay[tuning]
