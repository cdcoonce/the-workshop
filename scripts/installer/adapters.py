from __future__ import annotations

import shutil
import tempfile
from collections.abc import Iterator
from contextlib import contextmanager
from pathlib import Path

from scripts.installer.bundle import Bundle
from scripts.installer.report import InstallReport, Scope

# A persona package's owner-owned layer: tuning, preferences, and memory. It
# exists only on the owner's machine and a base update must never touch it
# (see persona-builder's package-format.md). Install rebuilds the destination
# wholesale, so this directory is carried across explicitly.
LOCAL_OVERLAY = "local"


@contextmanager
def _preserved_overlay(dest: Path) -> Iterator[Path | None]:
    """Move an existing `local/` out of `dest` for the duration of a reinstall.

    Yields the staged path, or None when there is nothing to preserve. The
    staging directory is removed on the way out, so a failed install cannot
    leave the overlay stranded in a temp dir — it is either back in place or
    still where it started.
    """
    overlay = dest / LOCAL_OVERLAY
    if not overlay.is_dir():
        yield None
        return
    staging = Path(tempfile.mkdtemp(prefix="workshop-overlay-"))
    staged = staging / LOCAL_OVERLAY
    shutil.move(str(overlay), str(staged))
    try:
        yield staged
    finally:
        shutil.rmtree(staging, ignore_errors=True)


class AgentAdapter:
    """Installs an agent-agnostic Bundle into one coding agent's world.

    Subclasses implement the agent-specific placement and report any bundle
    capability they cannot support (never a silent half-install)."""

    name: str = ""

    def detect(self, target: Path) -> bool:
        raise NotImplementedError

    def install(self, bundle: Bundle, target: Path, scope: Scope) -> InstallReport:
        raise NotImplementedError

    def uninstall(self, target: Path, preset: str) -> InstallReport:
        raise NotImplementedError


class ClaudeCodeAdapter(AgentAdapter):
    """Full-fidelity target: a preset is a Claude Code plugin. Placing it under
    `<target>/.claude/plugins/<preset>/` is the install — Claude Code
    auto-discovers plugins there and `plugin.json` declares skills/agents/
    commands/hooks. No settings.json surgery; nothing is skipped."""

    name = "claude-code"

    def _plugins_dir(self, target: Path) -> Path:
        return target / ".claude" / "plugins"

    def detect(self, target: Path) -> bool:
        return (target / ".claude").is_dir() or (target / "CLAUDE.md").is_file()

    def install(self, bundle: Bundle, target: Path, scope: Scope) -> InstallReport:
        report = InstallReport(agent=self.name, preset=bundle.name)
        dest = self._plugins_dir(target) / bundle.name
        with _preserved_overlay(dest) as overlay:
            if dest.exists():
                shutil.rmtree(dest)  # idempotent re-install
            dest.parent.mkdir(parents=True, exist_ok=True)
            shutil.copytree(bundle.path, dest)
            if overlay is not None:
                # The owner's overlay wins over one shipped in the base: `local/`
                # is machine-only by construction, so a packaged copy is a
                # default, never a replacement for what the owner has tuned.
                shipped = dest / LOCAL_OVERLAY
                if shipped.exists():
                    shutil.rmtree(shipped)
                shutil.move(str(overlay), str(shipped))
        report.add_installed(f"plugin -> {dest}")
        return report

    def uninstall(self, target: Path, preset: str) -> InstallReport:
        report = InstallReport(agent=self.name, preset=preset)
        dest = self._plugins_dir(target) / preset
        if dest.exists():
            shutil.rmtree(dest)
            report.add_removed(str(dest))
        else:
            report.add_skipped(preset, "not installed")
        return report


# Registry — adding Cursor/Gemini/Cortex later is a new class + one entry here.
_ADAPTERS: dict[str, AgentAdapter] = {}


def register(adapter: AgentAdapter) -> None:
    _ADAPTERS[adapter.name] = adapter


def get_adapter(name: str) -> AgentAdapter:
    return _ADAPTERS[name]


def adapter_names() -> list[str]:
    return sorted(_ADAPTERS)


def detect_adapter(target: Path) -> AgentAdapter | None:
    for name in adapter_names():
        if _ADAPTERS[name].detect(target):
            return _ADAPTERS[name]
    return None


register(ClaudeCodeAdapter())
