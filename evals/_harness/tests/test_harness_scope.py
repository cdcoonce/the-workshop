"""Guards that evals/_harness/ code never imports paired_ab.py or plugins/."""

from __future__ import annotations

import ast
from pathlib import Path

_HARNESS_ROOT = Path(__file__).resolve().parent.parent


def _imported_names(path: Path) -> list[str]:
    tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
    names: list[str] = []
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            names.extend(alias.name for alias in node.names)
        elif isinstance(node, ast.ImportFrom):
            if node.module:
                names.append(node.module)
    return names


def _is_forbidden(name: str) -> bool:
    parts = name.split(".")
    return "paired_ab" in parts or "plugins" in parts


def _scan(root: Path) -> list[tuple[str, str]]:
    violations: list[tuple[str, str]] = []
    for path in sorted(root.rglob("*.py")):
        for name in _imported_names(path):
            if _is_forbidden(name):
                violations.append((str(path.relative_to(root)), name))
    return violations


def test_harness_never_imports_paired_ab_or_plugins():
    """Scans every .py file under evals/_harness/ — sibling modules included."""
    assert _scan(_HARNESS_ROOT) == []


def test_scan_detects_a_planted_forbidden_import(tmp_path):
    (tmp_path / "bad_module.py").write_text(
        "import plugins.something\nfrom paired_ab import run\n", encoding="utf-8"
    )

    violations = _scan(tmp_path)

    assert len(violations) == 2
    imported = {name for _path, name in violations}
    assert "plugins.something" in imported
    assert "paired_ab" in imported
