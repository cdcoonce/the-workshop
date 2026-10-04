"""Keep the standalone graph CLI, hook runtime, and primary gate compatible."""

from __future__ import annotations

import json
import os
import re
import shlex
import subprocess
import sys
import tomllib
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
MACHINERY = ROOT / "plugins" / "workbench" / "machinery"
GRAPHMARK_REQUIREMENT = "graphmark>=0.10,<0.11"
# ragmark is not on PyPI: every surface resolves the v0.2.0 release wheel by URL.
RAGMARK_WHEEL = (
    "https://github.com/cdcoonce/ragmark/releases/download/v0.2.0/"
    "ragmark-0.2.0-py3-none-any.whl"
)


def _make_command(*args: str) -> list[str]:
    return ["make", "--no-print-directory", "-f", str(ROOT / "Makefile"), *args]


def _default_machinery_command() -> str:
    env = os.environ.copy()
    for name in ("MACHINERY_TEST_PYTHON", "MAKEFLAGS", "MFLAGS"):
        env.pop(name, None)
    return subprocess.check_output(
        _make_command("-n", "test-machinery"), cwd=ROOT, env=env, text=True
    )


def _recipe(target: str) -> str:
    makefile = (ROOT / "Makefile").read_text(encoding="utf-8")
    match = re.search(rf"^{re.escape(target)}:\n((?:\t.*\n)+)", makefile, re.MULTILINE)
    assert match, f"missing make target {target}"
    return match.group(1)


@pytest.mark.parametrize("surface", ["script", "project", "primary-gate"])
def test_graph_runtime_and_primary_gate_share_ragmark_compatible_range(
    surface: str,
) -> None:
    if surface == "script":
        script = (MACHINERY / "engine" / "graph_cli.py").read_text(encoding="utf-8")
        metadata = script.split("# /// script\n", 1)[1].split("# ///", 1)[0]
        data = tomllib.loads(
            "\n".join(line.removeprefix("# ") for line in metadata.splitlines())
        )
        requirements = data["dependencies"]
    elif surface == "project":
        data = tomllib.loads((MACHINERY / "pyproject.toml").read_text(encoding="utf-8"))
        requirements = data["project"]["dependencies"]
    else:
        requirements = re.findall(r"--with '([^']+)'", _default_machinery_command())

    assert [item for item in requirements if item.startswith("graphmark")] == [
        GRAPHMARK_REQUIREMENT
    ]


def test_machinery_lock_resolves_graphmark_in_the_declared_range() -> None:
    lock = tomllib.loads((MACHINERY / "uv.lock").read_text(encoding="utf-8"))
    graphmark = next(
        package for package in lock["package"] if package["name"] == "graphmark"
    )
    version = tuple(int(part) for part in graphmark["version"].split(".")[:2])
    assert (0, 10) <= version < (0, 11)
    project = next(
        package
        for package in lock["package"]
        if package["name"] == "workbench-machinery"
    )
    requirement = next(
        item
        for item in project["metadata"]["requires-dist"]
        if item["name"] == "graphmark"
    )
    assert requirement["specifier"] == ">=0.10,<0.11"


def test_default_machinery_gate_requires_ragmark_mcp() -> None:
    command = _default_machinery_command()
    assert f"--with 'ragmark[mcp] @ {RAGMARK_WHEEL}'" in command
    assert "-m pytest -q tests" in command


def test_machinery_gate_honors_explicit_interpreter(tmp_path: Path) -> None:
    capture = tmp_path / "capture.py"
    result = tmp_path / "invocation.json"
    capture.write_text(
        "import json, os, sys\n"
        "from pathlib import Path\n"
        f"Path({str(result)!r}).write_text(json.dumps("
        "{'cwd': os.getcwd(), 'args': sys.argv[1:]}))\n",
        encoding="utf-8",
    )
    interpreter = f"{shlex.quote(sys.executable)} {shlex.quote(str(capture))}"
    override = f"MACHINERY_TEST_PYTHON={interpreter}"
    # Fail before executing the recipe if it would ignore the override and
    # invoke uv (which could install dependencies during this fixture test).
    preview = subprocess.check_output(
        _make_command("-n", "test-machinery", override), cwd=ROOT, text=True
    )
    assert interpreter in preview
    assert "uv run" not in preview
    subprocess.run(
        _make_command("test-machinery", override),
        cwd=ROOT,
        check=True,
        capture_output=True,
        text=True,
    )
    assert json.loads(result.read_text()) == {
        "cwd": str(MACHINERY),
        "args": ["-m", "pytest", "-q", "tests"],
    }


@pytest.mark.parametrize(
    "spec", sorted(MACHINERY.glob("teeth-spec-*.json")), ids=lambda p: p.stem
)
@pytest.mark.parametrize("command", ["test_command", "collect_command"])
def test_teeth_commands_do_not_reintroduce_an_incompatible_runtime(
    spec: Path, command: str
) -> None:
    data = json.loads(spec.read_text(encoding="utf-8"))
    requirements = [
        item for item in data.get(command, []) if item.startswith("graphmark")
    ]
    assert all(item == GRAPHMARK_REQUIREMENT for item in requirements)


@pytest.mark.parametrize(
    "target", ["test-wrap-up-gate-parity", "test-cold-read-evidence-wikilink-parity"]
)
def test_owner_ci_parity_leg_stays_separate(target: str) -> None:
    recipe = _recipe(target)
    assert "'graphmark>=0.10,<0.11'" in recipe
    assert "cd plugins/workbench/machinery" not in recipe
    assert f"$(MAKE) {target}" in _recipe("test")
