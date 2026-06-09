from __future__ import annotations

import shutil
from pathlib import Path

from scripts.installer.bundle import Bundle
from scripts.installer.report import InstallReport, Scope


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
        if dest.exists():
            shutil.rmtree(dest)  # idempotent re-install
        dest.parent.mkdir(parents=True, exist_ok=True)
        shutil.copytree(bundle.path, dest)
        report.add_installed(f"plugin -> {dest}")
        return report

    def uninstall(self, target: Path, preset: str) -> InstallReport:
        report = InstallReport(agent=self.name, preset=preset)
        dest = self._plugins_dir(target) / preset
        if dest.exists():
            shutil.rmtree(dest)
            report.add_installed(f"removed {dest}")
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
