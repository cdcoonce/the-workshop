"""Tests for vault_scope_resolved — the per-name scaffold-override seam.

The vault's ``vault_scope.py`` is scaffold-owned: rendered once at init and
never touched by upgrade. Engine code therefore must never hard-require a
name from it — a scaffold rendered before a name existed would brick the
engine on import (the 1.3.1 incident). ``vault_scope_resolved`` prefers the
scaffold's value per-name and falls back to the shipped default.
"""

from __future__ import annotations

import sys
from pathlib import Path
from types import ModuleType

import pytest

# Add scripts dir to path
SCRIPTS_DIR = Path(__file__).resolve().parent.parent / "engine"
sys.path.insert(0, str(SCRIPTS_DIR))


@pytest.fixture
def scaffold(monkeypatch):
    """Install a stand-in scaffold-rendered vault_scope module.

    The real file is rendered into the vault's script dir at init; the seam
    under test is name resolution against whatever that snapshot defines.
    """

    def _install(**names) -> ModuleType:
        module = ModuleType("vault_scope")
        for key, value in names.items():
            setattr(module, key, value)
        monkeypatch.setitem(sys.modules, "vault_scope", module)
        return module

    return _install


class TestScaffoldOverrideWins:
    def test_scaffold_defined_name_is_returned(self, scaffold):
        scaffold(TASKS_DIR="custom/tasks")
        import vault_scope_resolved

        assert vault_scope_resolved.TASKS_DIR == "custom/tasks"


class TestStaleScaffoldFallsBack:
    def test_missing_name_falls_back_to_shipped_default(self, scaffold):
        # A scaffold rendered before BATCH_MODEL existed — the 1.3.1 incident.
        scaffold(TASKS_DIR="custom/tasks")
        import vault_scope_defaults
        import vault_scope_resolved

        assert vault_scope_resolved.BATCH_MODEL == vault_scope_defaults.BATCH_MODEL
        assert vault_scope_resolved.TASKS_DIR == "custom/tasks"


class TestNoScaffoldAtAll:
    def test_every_name_serves_shipped_defaults(self, monkeypatch):
        # sys.modules[name] = None makes `import vault_scope` raise ImportError.
        monkeypatch.setitem(sys.modules, "vault_scope", None)
        import vault_scope_defaults
        import vault_scope_resolved

        assert vault_scope_resolved.TASKS_DIR == vault_scope_defaults.TASKS_DIR
        assert vault_scope_resolved.GOVERNED_NOTE_DIRS == (
            vault_scope_defaults.GOVERNED_NOTE_DIRS
        )

    def test_unknown_name_still_raises_attribute_error(self, monkeypatch):
        monkeypatch.setitem(sys.modules, "vault_scope", None)
        import vault_scope_resolved

        with pytest.raises(AttributeError):
            vault_scope_resolved.NO_SUCH_NAME


class TestConsumersSurviveStaleScaffold:
    """The 1.3.1 incident, as a regression test.

    A vault whose scaffolded ``vault_scope.py`` predates the task/model
    constants must still import the engine consumers, which then run with
    shipped-default behavior.
    """

    def test_managers_import_and_use_defaults(self, scaffold):
        import importlib

        # Stale scaffold: defines the graph taxonomy names that have existed
        # since the scaffold tier appeared, but none of the newer constants.
        scaffold(GOVERNED_NOTE_DIRS=("brain",), GRAPH_NOTE_DIRS=("brain",))

        import vault_scope_defaults
        import task_manager
        import work_task_manager

        task_manager = importlib.reload(task_manager)
        work_task_manager = importlib.reload(work_task_manager)

        assert task_manager.TASKS_DIR == vault_scope_defaults.TASKS_DIR
        assert (
            work_task_manager.WORK_TASKS_FILENAME
            == vault_scope_defaults.WORK_TASKS_FILENAME
        )


class TestDefaultsCoverEveryEngineImport:
    """Structural guard: the incident class cannot recur.

    Any name an engine module imports from the scope surface must ship a
    default — otherwise a scaffold rendered before that name existed has
    nothing to fall back to, and the resolver's guarantee is hollow.
    """

    def test_every_resolved_import_has_a_shipped_default(self):
        import ast

        import vault_scope_defaults

        missing: list[str] = []
        for path in SCRIPTS_DIR.glob("*.py"):
            tree = ast.parse(path.read_text(encoding="utf-8"))
            for node in ast.walk(tree):
                if (
                    isinstance(node, ast.ImportFrom)
                    and node.module in ("vault_scope_resolved", "vault_scope")
                ):
                    for alias in node.names:
                        if not hasattr(vault_scope_defaults, alias.name):
                            missing.append(f"{path.name}: {alias.name}")
        assert not missing, (
            "engine imports scope names with no shipped default "
            f"(add them to vault_scope_defaults.py): {missing}"
        )
