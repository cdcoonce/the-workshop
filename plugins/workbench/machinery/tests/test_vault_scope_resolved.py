"""Tests for vault_scope_resolved — the per-name owner-override seam.

The vault's ``vault_scope.py`` is owner-owned: rendered once at init and never
touched by upgrade. Engine code therefore must never hard-require a name from
it — a config rendered before a name existed would brick the engine on import
(the 1.3.1 incident). ``vault_scope_resolved`` prefers the owner's value
per-name and falls back to the shipped default.

Resolution anchors on the **vault root**, not on a bare ``import vault_scope``
(#691). The fixtures install a real file in a real vault; see this suite's
``conftest.py`` for why installing a module object into ``sys.modules`` was not
a faithful stand-in for what production does.
"""

from __future__ import annotations

import sys
from pathlib import Path
from types import ModuleType

import pytest

from conftest import _clear_owner_scope_cache

SCRIPTS_DIR = Path(__file__).resolve().parent.parent / "engine"
sys.path.insert(0, str(SCRIPTS_DIR))


class TestOwnerOverrideWins:
    def test_owner_defined_name_is_returned(self, owner_scope):
        owner_scope(TASKS_DIR="custom/tasks")
        import vault_scope_resolved

        assert vault_scope_resolved.TASKS_DIR == "custom/tasks"

    def test_resolution_ignores_a_module_registered_under_the_name(
        self, owner_scope, monkeypatch
    ):
        """The name ``vault_scope`` is not the mechanism, and must not become one.

        This is #691 stated as a contract. The engine used to ship a module
        called ``vault_scope``, and because every hook entry point prepends the
        engine directory to ``sys.path``, that copy won the name lookup ahead of
        the owner's config — permanently, on every vault. Whatever else answers
        to the name, the owner's file is what must be read.
        """
        impostor = ModuleType("vault_scope")
        impostor.TASKS_DIR = "impostor/tasks"
        monkeypatch.setitem(sys.modules, "vault_scope", impostor)
        owner_scope(TASKS_DIR="custom/tasks")
        import vault_scope_resolved

        assert vault_scope_resolved.TASKS_DIR == "custom/tasks"


class TestStaleConfigFallsBack:
    def test_missing_name_falls_back_to_shipped_default(self, owner_scope):
        # A config rendered before BATCH_MODEL existed — the 1.3.1 incident.
        owner_scope(TASKS_DIR="custom/tasks")
        import vault_scope_defaults
        import vault_scope_resolved

        assert vault_scope_resolved.BATCH_MODEL == vault_scope_defaults.BATCH_MODEL
        assert vault_scope_resolved.TASKS_DIR == "custom/tasks"


class TestNoOwnerConfigAtAll:
    def test_every_name_serves_shipped_defaults(self, no_owner_scope):
        import vault_scope_defaults
        import vault_scope_resolved

        assert vault_scope_resolved.TASKS_DIR == vault_scope_defaults.TASKS_DIR
        assert vault_scope_resolved.GOVERNED_NOTE_DIRS == (
            vault_scope_defaults.GOVERNED_NOTE_DIRS
        )

    def test_unknown_name_still_raises_attribute_error(self, no_owner_scope):
        import vault_scope_resolved

        with pytest.raises(AttributeError):
            vault_scope_resolved.NO_SUCH_NAME

    def test_vault_without_a_config_file_serves_defaults(self, tmp_path, monkeypatch):
        """A vault marker with no config beside it is a legitimate, silent state."""
        import vault_scope_defaults
        import vault_scope_resolved

        vault = tmp_path / "bare-vault"
        (vault / ".vault").mkdir(parents=True)
        (vault / ".vault" / "vault.json").write_text('{"vault": "bare"}\n')
        monkeypatch.setenv("CLAUDE_PROJECT_DIR", str(vault))
        _clear_owner_scope_cache()

        assert vault_scope_resolved.TASKS_DIR == vault_scope_defaults.TASKS_DIR


class TestBrokenConfigIsAnnounced:
    """Exists-but-unloadable is the one state that must not stay silent."""

    def test_broken_config_reports_and_falls_back(self, tmp_path, monkeypatch, capsys):
        import vault_scope_defaults
        import vault_scope_resolved

        vault = tmp_path / "broken-vault"
        config_dir = vault / ".vault" / "config"
        config_dir.mkdir(parents=True)
        (vault / ".vault" / "vault.json").write_text('{"vault": "broken"}\n')
        (config_dir / "vault_scope.py").write_text("TASKS_DIR = (  # unclosed\n")
        monkeypatch.setenv("CLAUDE_PROJECT_DIR", str(vault))
        _clear_owner_scope_cache()

        # Fails open: a typo in the owner's config must not take the session down.
        assert vault_scope_resolved.TASKS_DIR == vault_scope_defaults.TASKS_DIR
        # Matched on the diagnostic's own wording: a bare "vault_scope" would
        # also match an unhandled traceback, which is the failure this guards.
        assert "did not load" in capsys.readouterr().err


class TestConsumersSurviveStaleConfig:
    """The 1.3.1 incident, as a regression test.

    A vault whose ``vault_scope.py`` predates the task/model constants must
    still import the engine consumers, which then run with shipped-default
    behavior.
    """

    def test_managers_import_and_use_defaults(self, owner_scope):
        import importlib

        # Stale config: defines the graph taxonomy names that have existed
        # since the owner tier appeared, but none of the newer constants.
        owner_scope(GOVERNED_NOTE_DIRS=("brain",), GRAPH_NOTE_DIRS=("brain",))

        import task_manager
        import vault_scope_defaults
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
    default — otherwise a config rendered before that name existed has
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
