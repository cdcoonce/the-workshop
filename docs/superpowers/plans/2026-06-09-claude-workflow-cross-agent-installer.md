# claude-workflow Cross-Agent Installer Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** A `claude-workflow install` CLI that places a built preset bundle into a detected coding agent (Claude Code first), via a pluggable agent-adapter seam, so a teammate sets up a repo with one command.

**Architecture:** One agent-agnostic `Bundle` (a built `dist/<preset>/` plugin dir) + a pluggable `AgentAdapter` seam (place the bundle in the agent's world, report capability skips) + a thin `argparse` CLI. Project-scoped default, `--user` opt-in. Presets are bundled into the wheel so no runtime fetch.

**Tech Stack:** Python 3.12, `scripts/` package (hatchling), pytest, `shutil`/`pathlib`, `argparse`. Imports are `from scripts.installer.<module> import …` (matching `from scripts.build_preset import build_preset`). **Test command:** `uv run --with pytest python -m pytest` (pytest is not a project dep — it's added via `--with`).

**Scope note:** This plan delivers the bundle + seam + **ClaudeCodeAdapter** + CLI — working, testable software (you can install a preset into a Claude Code repo). The **CortexCodeAdapter** is a follow-on (it needs a research spike into Cortex Code's extension mechanism first — see spec Open Items — so its concrete code can't be planned yet). The seam is built so it slots in without core changes.

---

## File Structure

- `scripts/installer/__init__.py` — package marker.
- `scripts/installer/report.py` — `Scope` enum, `InstallReport` (installed + skipped-with-reason).
- `scripts/installer/bundle.py` — `Bundle` (wraps a built preset dir) + `BundleError`.
- `scripts/installer/adapters.py` — `AgentAdapter` base, `ClaudeCodeAdapter`, registry helpers.
- `scripts/installer/cli.py` — `install` / `list` commands + `main()`.
- `pyproject.toml` — add `[project.scripts]` entry point + bundle built presets into the wheel.
- Tests: `tests/test_installer_report.py`, `tests/test_installer_bundle.py`, `tests/test_installer_claude_adapter.py`, `tests/test_installer_cli.py`.

---

### Task 1: Report types (`Scope`, `InstallReport`)

**Files:**

- Create: `scripts/installer/__init__.py` (empty)
- Create: `scripts/installer/report.py`
- Test: `tests/test_installer_report.py`

- [ ] **Step 1: Write the failing test**

```python
# tests/test_installer_report.py
from scripts.installer.report import InstallReport, Scope


def test_scope_values():
    assert Scope.PROJECT.value == "project"
    assert Scope.USER.value == "user"


def test_report_records_installed_and_skipped_with_reason():
    r = InstallReport(agent="claude-code", preset="data-pipeline")
    r.add_installed("plugin -> /repo/.claude/plugins/data-pipeline")
    r.add_skipped("hooks", "agent has no hook mechanism")
    assert r.installed == ["plugin -> /repo/.claude/plugins/data-pipeline"]
    assert r.skipped == [("hooks", "agent has no hook mechanism")]
```

- [ ] **Step 2: Run test to verify it fails**

Run: `uv run --with pytest python -m pytest tests/test_installer_report.py -v`
Expected: FAIL with `ModuleNotFoundError: No module named 'scripts.installer'`

- [ ] **Step 3: Write minimal implementation**

```python
# scripts/installer/__init__.py
```

```python
# scripts/installer/report.py
from __future__ import annotations

from dataclasses import dataclass, field
from enum import Enum


class Scope(str, Enum):
    PROJECT = "project"
    USER = "user"


@dataclass
class InstallReport:
    """What an adapter did: items installed, and items skipped with a reason
    (a capability the target agent does not support). Never a silent half-install."""

    agent: str
    preset: str
    installed: list[str] = field(default_factory=list)
    skipped: list[tuple[str, str]] = field(default_factory=list)

    def add_installed(self, item: str) -> None:
        self.installed.append(item)

    def add_skipped(self, item: str, reason: str) -> None:
        self.skipped.append((item, reason))
```

- [ ] **Step 4: Run test to verify it passes**

Run: `uv run --with pytest python -m pytest tests/test_installer_report.py -v`
Expected: PASS (2 passed)

- [ ] **Step 5: Commit**

```bash
git add scripts/installer/__init__.py scripts/installer/report.py tests/test_installer_report.py
git commit -m "feat(installer): InstallReport + Scope types"
```

---

### Task 2: `Bundle` (a built preset on disk)

**Files:**

- Create: `scripts/installer/bundle.py`
- Test: `tests/test_installer_bundle.py`

- [ ] **Step 1: Write the failing test**

```python
# tests/test_installer_bundle.py
import json

import pytest

from scripts.installer.bundle import Bundle, BundleError


def _make_preset(root, name):
    p = root / name / ".claude-plugin"
    p.mkdir(parents=True)
    (p / "plugin.json").write_text(json.dumps({"name": name, "version": "1.0.0"}))
    (root / name / "skills").mkdir()
    return root / name


def test_load_returns_bundle_for_valid_preset(tmp_path):
    _make_preset(tmp_path, "data-pipeline")
    b = Bundle.load(tmp_path, "data-pipeline")
    assert b.name == "data-pipeline"
    assert b.path == tmp_path / "data-pipeline"


def test_load_raises_for_missing_preset(tmp_path):
    with pytest.raises(BundleError):
        Bundle.load(tmp_path, "nope")


def test_available_lists_only_valid_presets(tmp_path):
    _make_preset(tmp_path, "analysis")
    _make_preset(tmp_path, "data-pipeline")
    (tmp_path / "not-a-preset").mkdir()  # no .claude-plugin/plugin.json
    assert Bundle.available(tmp_path) == ["analysis", "data-pipeline"]
```

- [ ] **Step 2: Run test to verify it fails**

Run: `uv run --with pytest python -m pytest tests/test_installer_bundle.py -v`
Expected: FAIL with `ModuleNotFoundError: No module named 'scripts.installer.bundle'`

- [ ] **Step 3: Write minimal implementation**

```python
# scripts/installer/bundle.py
from __future__ import annotations

from pathlib import Path


class BundleError(Exception):
    """Raised when a preset bundle is missing or malformed."""


class Bundle:
    """A built preset on disk: a complete Claude Code plugin directory
    (`<presets_root>/<name>/` containing `.claude-plugin/plugin.json`)."""

    def __init__(self, name: str, path: Path) -> None:
        self.name = name
        self.path = path

    @staticmethod
    def _is_preset(path: Path) -> bool:
        return (path / ".claude-plugin" / "plugin.json").is_file()

    @classmethod
    def load(cls, presets_root: Path, name: str) -> "Bundle":
        path = presets_root / name
        if not cls._is_preset(path):
            raise BundleError(
                f"preset {name!r} not found under {presets_root} "
                "(no .claude-plugin/plugin.json)"
            )
        return cls(name, path)

    @classmethod
    def available(cls, presets_root: Path) -> list[str]:
        if not presets_root.is_dir():
            return []
        return sorted(p.name for p in presets_root.iterdir() if cls._is_preset(p))
```

- [ ] **Step 4: Run test to verify it passes**

Run: `uv run --with pytest python -m pytest tests/test_installer_bundle.py -v`
Expected: PASS (3 passed)

- [ ] **Step 5: Commit**

```bash
git add scripts/installer/bundle.py tests/test_installer_bundle.py
git commit -m "feat(installer): Bundle — load/validate/list built presets"
```

---

### Task 3: `AgentAdapter` base + registry

**Files:**

- Create: `scripts/installer/adapters.py` (base + registry; ClaudeCodeAdapter added in Task 4)
- Test: `tests/test_installer_claude_adapter.py` (registry tests; adapter tests in Task 4)

- [ ] **Step 1: Write the failing test**

```python
# tests/test_installer_claude_adapter.py
import pytest

from scripts.installer.adapters import adapter_names, get_adapter


def test_get_adapter_unknown_raises():
    with pytest.raises(KeyError):
        get_adapter("does-not-exist")


def test_claude_code_is_registered():
    assert "claude-code" in adapter_names()
```

- [ ] **Step 2: Run test to verify it fails**

Run: `uv run --with pytest python -m pytest tests/test_installer_claude_adapter.py -v`
Expected: FAIL with `ModuleNotFoundError: No module named 'scripts.installer.adapters'`

- [ ] **Step 3: Write minimal implementation**

```python
# scripts/installer/adapters.py
from __future__ import annotations

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
```

(Note: `test_claude_code_is_registered` stays RED until Task 4 registers it — that is expected; it passes at the end of Task 4. The `get_adapter_unknown_raises` test passes now.)

- [ ] **Step 4: Run test to verify partial pass**

Run: `uv run --with pytest python -m pytest tests/test_installer_claude_adapter.py::test_get_adapter_unknown_raises -v`
Expected: PASS

- [ ] **Step 5: Commit**

```bash
git add scripts/installer/adapters.py tests/test_installer_claude_adapter.py
git commit -m "feat(installer): AgentAdapter base + registry seam"
```

---

### Task 4: `ClaudeCodeAdapter`

**Files:**

- Modify: `scripts/installer/adapters.py` (add `ClaudeCodeAdapter` + `register(ClaudeCodeAdapter())`)
- Test: `tests/test_installer_claude_adapter.py` (add install/uninstall/detect tests)

- [ ] **Step 1: Write the failing tests**

```python
# add to tests/test_installer_claude_adapter.py
import json

from scripts.installer.adapters import ClaudeCodeAdapter
from scripts.installer.bundle import Bundle
from scripts.installer.report import Scope


def _make_preset(root, name):
    p = root / name / ".claude-plugin"
    p.mkdir(parents=True)
    (p / "plugin.json").write_text(json.dumps({"name": name, "version": "1.0.0"}))
    (root / name / "skills").mkdir()
    (root / name / "skills" / "s.md").write_text("# skill")
    return root / name


def test_detect_true_when_claude_dir_present(tmp_path):
    (tmp_path / ".claude").mkdir()
    assert ClaudeCodeAdapter().detect(tmp_path) is True


def test_detect_false_on_bare_dir(tmp_path):
    assert ClaudeCodeAdapter().detect(tmp_path) is False


def test_install_places_plugin_and_reports(tmp_path):
    presets = tmp_path / "presets"
    presets.mkdir()
    _make_preset(presets, "data-pipeline")
    repo = tmp_path / "repo"
    repo.mkdir()

    report = ClaudeCodeAdapter().install(
        Bundle.load(presets, "data-pipeline"), repo, Scope.PROJECT
    )

    dest = repo / ".claude" / "plugins" / "data-pipeline"
    assert (dest / ".claude-plugin" / "plugin.json").is_file()
    assert (dest / "skills" / "s.md").is_file()
    assert report.installed and not report.skipped


def test_install_is_idempotent(tmp_path):
    presets = tmp_path / "presets"
    presets.mkdir()
    _make_preset(presets, "data-pipeline")
    repo = tmp_path / "repo"
    repo.mkdir()
    adapter = ClaudeCodeAdapter()
    bundle = Bundle.load(presets, "data-pipeline")

    adapter.install(bundle, repo, Scope.PROJECT)
    adapter.install(bundle, repo, Scope.PROJECT)  # second run must not raise

    assert (repo / ".claude" / "plugins" / "data-pipeline" / "skills" / "s.md").is_file()


def test_uninstall_removes_then_reports_skip_when_absent(tmp_path):
    presets = tmp_path / "presets"
    presets.mkdir()
    _make_preset(presets, "data-pipeline")
    repo = tmp_path / "repo"
    repo.mkdir()
    adapter = ClaudeCodeAdapter()
    adapter.install(Bundle.load(presets, "data-pipeline"), repo, Scope.PROJECT)

    r1 = adapter.uninstall(repo, "data-pipeline")
    assert not (repo / ".claude" / "plugins" / "data-pipeline").exists()
    assert r1.installed  # recorded the removal

    r2 = adapter.uninstall(repo, "data-pipeline")  # already gone
    assert r2.skipped == [("data-pipeline", "not installed")]
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `uv run --with pytest python -m pytest tests/test_installer_claude_adapter.py -v`
Expected: FAIL with `ImportError: cannot import name 'ClaudeCodeAdapter'`

- [ ] **Step 3: Write minimal implementation**

Add to `scripts/installer/adapters.py` (before the registry section), plus register it at the bottom:

```python
import shutil


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
```

At the very bottom of the file:

```python
register(ClaudeCodeAdapter())
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `uv run --with pytest python -m pytest tests/test_installer_claude_adapter.py -v`
Expected: PASS (all, including `test_claude_code_is_registered`)

- [ ] **Step 5: Commit**

```bash
git add scripts/installer/adapters.py tests/test_installer_claude_adapter.py
git commit -m "feat(installer): ClaudeCodeAdapter — place/remove plugin idempotently"
```

---

### Task 5: CLI (`install` / `list`)

**Files:**

- Create: `scripts/installer/cli.py`
- Test: `tests/test_installer_cli.py`

- [ ] **Step 1: Write the failing test**

```python
# tests/test_installer_cli.py
import json

from scripts.installer import cli


def _make_preset(root, name):
    p = root / name / ".claude-plugin"
    p.mkdir(parents=True)
    (p / "plugin.json").write_text(json.dumps({"name": name, "version": "1.0.0"}))


def test_install_project_scope_places_plugin(tmp_path, monkeypatch):
    presets = tmp_path / "presets"
    presets.mkdir()
    _make_preset(presets, "data-pipeline")
    repo = tmp_path / "repo"
    (repo / ".claude").mkdir(parents=True)  # so claude-code auto-detects
    monkeypatch.setattr(cli, "PRESETS_ROOT", presets)
    monkeypatch.chdir(repo)

    rc = cli.main(["install", "--preset", "data-pipeline"])

    assert rc == 0
    assert (repo / ".claude" / "plugins" / "data-pipeline" / ".claude-plugin" / "plugin.json").is_file()


def test_install_dry_run_writes_nothing(tmp_path, monkeypatch):
    presets = tmp_path / "presets"
    presets.mkdir()
    _make_preset(presets, "data-pipeline")
    repo = tmp_path / "repo"
    (repo / ".claude").mkdir(parents=True)
    monkeypatch.setattr(cli, "PRESETS_ROOT", presets)
    monkeypatch.chdir(repo)

    rc = cli.main(["install", "--preset", "data-pipeline", "--dry-run"])

    assert rc == 0
    assert not (repo / ".claude" / "plugins" / "data-pipeline").exists()


def test_install_unknown_preset_errors(tmp_path, monkeypatch, capsys):
    presets = tmp_path / "presets"
    presets.mkdir()
    _make_preset(presets, "data-pipeline")
    repo = tmp_path / "repo"
    (repo / ".claude").mkdir(parents=True)
    monkeypatch.setattr(cli, "PRESETS_ROOT", presets)
    monkeypatch.chdir(repo)

    rc = cli.main(["install", "--preset", "nope"])

    assert rc == 2
    assert "data-pipeline" in capsys.readouterr().out  # lists valid presets


def test_list_shows_presets_and_detected_agent(tmp_path, monkeypatch, capsys):
    presets = tmp_path / "presets"
    presets.mkdir()
    _make_preset(presets, "analysis")
    repo = tmp_path / "repo"
    (repo / ".claude").mkdir(parents=True)
    monkeypatch.setattr(cli, "PRESETS_ROOT", presets)
    monkeypatch.chdir(repo)

    rc = cli.main(["list"])

    out = capsys.readouterr().out
    assert rc == 0
    assert "analysis" in out
    assert "claude-code" in out
```

- [ ] **Step 2: Run test to verify it fails**

Run: `uv run --with pytest python -m pytest tests/test_installer_cli.py -v`
Expected: FAIL with `ModuleNotFoundError: No module named 'scripts.installer.cli'`

- [ ] **Step 3: Write minimal implementation**

```python
# scripts/installer/cli.py
from __future__ import annotations

import argparse
from pathlib import Path

from scripts.installer.adapters import (
    adapter_names,
    detect_adapter,
    get_adapter,
)
from scripts.installer.bundle import Bundle, BundleError
from scripts.installer.report import Scope

# Built presets ship inside the wheel next to this module (see packaging task).
PRESETS_ROOT = Path(__file__).resolve().parent / "presets"


def _resolve_target(scope: Scope) -> Path:
    return Path.home() if scope is Scope.USER else Path.cwd()


def _print_report(report) -> None:
    for item in report.installed:
        print(f"  installed: {item}")
    for item, reason in report.skipped:
        print(f"  skipped {item}: {reason}")


def cmd_install(args) -> int:
    scope = Scope.USER if args.user else Scope.PROJECT
    target = _resolve_target(scope)

    if args.agent:
        adapter = get_adapter(args.agent) if args.agent in adapter_names() else None
    else:
        adapter = detect_adapter(target)
    if adapter is None:
        print(f"no supported agent detected/selected. known: {adapter_names()}")
        return 2

    try:
        bundle = Bundle.load(PRESETS_ROOT, args.preset)
    except BundleError:
        print(f"unknown preset {args.preset!r}. available: {Bundle.available(PRESETS_ROOT)}")
        return 2

    if args.dry_run:
        print(f"[dry-run] would install {bundle.name} for {adapter.name} into {target}")
        return 0

    print(f"installing {bundle.name} for {adapter.name} ({scope.value}) into {target}")
    _print_report(adapter.install(bundle, target, scope))
    return 0


def cmd_list(args) -> int:
    target = Path.cwd()
    detected = detect_adapter(target)
    print(f"presets: {Bundle.available(PRESETS_ROOT)}")
    print(f"agents (known): {adapter_names()}")
    print(f"detected here: {detected.name if detected else 'none'}")
    return 0


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="claude-workflow")
    sub = parser.add_subparsers(dest="command", required=True)

    p_install = sub.add_parser("install", help="install a preset into the detected agent")
    p_install.add_argument("--preset", required=True)
    p_install.add_argument("--agent", default=None, help="force an agent adapter")
    p_install.add_argument("--user", action="store_true", help="install into ~ instead of the repo")
    p_install.add_argument("--dry-run", action="store_true")
    p_install.set_defaults(func=cmd_install)

    p_list = sub.add_parser("list", help="list presets + detected agent")
    p_list.set_defaults(func=cmd_list)
    return parser


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    return args.func(args)
```

- [ ] **Step 4: Run test to verify it passes**

Run: `uv run --with pytest python -m pytest tests/test_installer_cli.py -v`
Expected: PASS (4 passed)

- [ ] **Step 5: Commit**

```bash
git add scripts/installer/cli.py tests/test_installer_cli.py
git commit -m "feat(installer): install/list CLI over the adapter seam"
```

---

### Task 6: Packaging — console entry point + bundle presets into the wheel

**Files:**

- Modify: `pyproject.toml`
- Test: `tests/test_installer_cli.py` (add a packaging smoke test)

- [ ] **Step 1: Write the failing test**

```python
# add to tests/test_installer_cli.py
def test_presets_root_default_is_under_the_package():
    # The CLI's default PRESETS_ROOT must live inside the installed package so a
    # `uv tool install`'d copy can find bundled presets without a checkout.
    from scripts.installer import cli

    assert cli.PRESETS_ROOT.name == "presets"
    assert cli.PRESETS_ROOT.parent.name == "installer"
```

- [ ] **Step 2: Run test to verify it fails (or passes trivially)**

Run: `uv run --with pytest python -m pytest tests/test_installer_cli.py::test_presets_root_default_is_under_the_package -v`
Expected: PASS (the path is already correct from Task 5) — this test pins the packaging contract so it can't regress. If it fails, fix `PRESETS_ROOT` in `cli.py`.

- [ ] **Step 3: Add the entry point + preset bundling to `pyproject.toml`**

Add a `[project.scripts]` table and a build-time force-include that copies the built `dist/<preset>/` trees into `scripts/installer/presets/<preset>/` so they ship in the wheel:

```toml
[project.scripts]
claude-workflow = "scripts.installer.cli:main"

[tool.hatch.build.targets.wheel.force-include]
"scripts/installer/presets" = "scripts/installer/presets"
```

Then add a documented build step (run before `uv build`) that populates the bundled presets from the existing build pipeline:

```bash
# scripts/installer/presets/ is generated, gitignored. Regenerate before building:
rm -rf scripts/installer/presets && mkdir -p scripts/installer/presets
for preset in analysis claude-tooling data-pipeline full-stack python-api; do
  uv run python scripts/build_preset.py "$preset"
  cp -r "dist/$preset" "scripts/installer/presets/$preset"
done
```

Add `scripts/installer/presets/` to `.gitignore`.

- [ ] **Step 4: Verify the entry point resolves + suite green**

Run: `uv run claude-workflow list` (after running the build step above so presets exist)
Expected: prints presets + `detected here: ...`

Run: `uv run --with pytest python -m pytest -q`
Expected: PASS (whole suite green)

- [ ] **Step 5: Commit**

```bash
git add pyproject.toml tests/test_installer_cli.py .gitignore
git commit -m "build(installer): console entry point + bundle presets into the wheel"
```

---

## Follow-on (separate plan, after a research spike)

- **CortexCodeAdapter** — research Snowflake Cortex Code's local skill/extension mechanism first (spec Open Items), then add a `CortexCodeAdapter(AgentAdapter)` + `register(...)` + tests, degrading to a context-file install (reporting hooks/sub-agents as skipped) if Cortex has no plugin equivalent. The seam built here takes it with no core change.
- **Vault + afk consume claude-workflow presets** — the architectural refactor (separate spec already scoped as a non-goal here).

---

## Self-Review

- **Spec coverage:** canonical bundle → Task 2 + Task 6 (packaging). Adapter seam → Task 3. ClaudeCodeAdapter → Task 4. CLI (install/list/--user/--dry-run, idempotent) → Task 5. Distribution/wheel bundling → Task 6. Testing (per-adapter temp-dir, CLI, packaging smoke) → Tasks 2/4/5/6. CortexCodeAdapter → explicitly deferred (research-gated) with the seam ready. Error handling (unknown preset/agent, skip-reporting) → Tasks 4/5. ✓
- **Placeholder scan:** every code step has complete code; no TBD/TODO. ✓
- **Type consistency:** `Bundle.load/available`, `InstallReport.add_installed/add_skipped`, `Scope.PROJECT/USER`, adapter `install/uninstall/detect`, `get_adapter/detect_adapter/adapter_names/register`, `cli.PRESETS_ROOT/main` are used identically across tasks. ✓
