"""AST-only check: no module under evals/ may call a model or the claude CLI.

evals/_harness/scorer.py and the guard runner must stay pure — nothing under
evals/ dispatches a subagent or talks to a model. This parses a module's AST
(never imports it, so a broken or malicious module cannot execute) and flags:

- an ``import``/``from`` of ``anthropic`` or ``claude_agent_sdk`` (any dotted
  form)
- a ``subprocess``/``os`` call whose command string, or first argv element,
  is ``"claude"`` or starts with ``"claude "``
"""

from __future__ import annotations

import ast
from pathlib import Path

_MODEL_MODULE_PREFIXES = ("anthropic", "claude_agent_sdk")
_SHELL_NAMESPACES = {"subprocess", "os"}


def _is_model_import(node: ast.AST) -> str | None:
    """Return the offending module name if *node* imports a model client."""
    if isinstance(node, ast.Import):
        for alias in node.names:
            if alias.name.split(".")[0] in _MODEL_MODULE_PREFIXES:
                return alias.name
    elif isinstance(node, ast.ImportFrom):
        if node.module and node.module.split(".")[0] in _MODEL_MODULE_PREFIXES:
            return node.module
    return None


def _first_command_token(node: ast.Call) -> str | None:
    """Return the literal command string or first argv element of a call."""
    if not node.args:
        return None
    first = node.args[0]
    if isinstance(first, ast.Constant) and isinstance(first.value, str):
        return first.value
    if isinstance(first, (ast.List, ast.Tuple)) and first.elts:
        head = first.elts[0]
        if isinstance(head, ast.Constant) and isinstance(head.value, str):
            return head.value
    return None


def _is_claude_cli_call(node: ast.AST) -> str | None:
    """Return the offending command token if *node* invokes the claude CLI."""
    if not isinstance(node, ast.Call):
        return None
    func = node.func
    if not isinstance(func, ast.Attribute):
        return None
    if not isinstance(func.value, ast.Name) or func.value.id not in _SHELL_NAMESPACES:
        return None
    token = _first_command_token(node)
    if token is not None and (token == "claude" or token.startswith("claude ")):
        return token
    return None


def find_violations(source: str) -> list[str]:
    """Return one message per model-client import or claude-CLI call in *source*.

    Parameters
    ----------
    source : str
        Python source to parse. Never executed or imported.

    Returns
    -------
    list[str]
        Empty if *source* is clean.
    """
    tree = ast.parse(source)
    violations: list[str] = []
    for node in ast.walk(tree):
        offender = _is_model_import(node)
        if offender is not None:
            violations.append(f"imports model client {offender!r}")
            continue
        offender = _is_claude_cli_call(node)
        if offender is not None:
            violations.append(f"invokes the claude CLI: {offender!r}")
    return violations


def check_file(path: Path) -> list[str]:
    """Return `find_violations` on *path*'s source, read as text."""
    return find_violations(path.read_text(encoding="utf-8"))
