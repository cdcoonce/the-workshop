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
GRAPHMARK_REQUIREMENT = "graphmark>=0.11,<0.12"
# ragmark is not on PyPI: every surface resolves the v0.3.0 release wheel by URL.
# Moving this constant also re-bases test_graphmark_dependencies.teeth.json: its
# wheel rows anchor on the literal v0.3.0, so `make check-teeth-anchors` fails the
# bump until they name the new version.
RAGMARK_WHEEL = (
    "https://github.com/cdcoonce/ragmark/releases/download/v0.3.0/"
    "ragmark-0.3.0-py3-none-any.whl"
)
# ragmark's embedder identity records `fastembed.__version__`, and ragmark
# refuses an index whose recorded identity differs (IndexIdentityError, state
# `identity_mismatch`). The wheel only constrains `fastembed>=0.8,<0.9`, so every
# environment that builds or reads the vault's index must pin the SAME exact
# version the existing index was built with, or a patch release silently
# strands the index. `==` is deliberate: moving this pin is a coordinated act
# (rebuild the index, refresh the runtime snapshot), never a silent drift.
FASTEMBED_VERSION = "0.8.0"
FASTEMBED_REQUIREMENT = f"fastembed=={FASTEMBED_VERSION}"
# Engine scripts known to declare ragmark in their PEP 723 block; discovery must
# still find all of them, or "every script that declares ragmark" is vacuous.
RAGMARK_ENGINE_SCRIPTS = {"graph_cli.py", "semantic_index.py", "vault_mcp.py"}

# The reference regex from PEP 723, so a block is parsed the way uv parses it.
_PEP723_BLOCK = re.compile(
    r"(?m)^# /// (?P<type>[a-zA-Z0-9-]+)$\s(?P<content>(^#(| .*)$\s)+)^# ///$"
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


def _pep723_dependencies(script: Path) -> list[str] | None:
    """Return the script's inline `dependencies`, or None without a script block."""
    for match in _PEP723_BLOCK.finditer(script.read_text(encoding="utf-8")):
        if match.group("type") != "script":
            continue
        content = "".join(
            line[2:] if line.startswith("# ") else line[1:]
            for line in match.group("content").splitlines(keepends=True)
        )
        return tomllib.loads(content).get("dependencies", [])
    return None


def _requirement_name(requirement: str) -> str:
    """Return the lower-cased distribution name a requirement string names."""
    return re.split(r"[\s\[<>=!~@;]", requirement.strip(), maxsplit=1)[0].lower()


def _fastembed_requirements(requirements: list[str]) -> list[str]:
    return [item for item in requirements if _requirement_name(item) == "fastembed"]


def _engine_scripts_declaring_ragmark() -> dict[str, list[str]]:
    declared: dict[str, list[str]] = {}
    for script in sorted((MACHINERY / "engine").glob("*.py")):
        requirements = _pep723_dependencies(script)
        if requirements and any(
            _requirement_name(item) == "ragmark" for item in requirements
        ):
            declared[script.name] = requirements
    return declared


@pytest.mark.parametrize("surface", ["script", "project", "primary-gate"])
def test_graph_runtime_and_primary_gate_share_ragmark_compatible_range(
    surface: str,
) -> None:
    if surface == "script":
        requirements = _pep723_dependencies(MACHINERY / "engine" / "graph_cli.py")
        assert requirements is not None
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
    assert (0, 11) <= version < (0, 12)
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
    assert requirement["specifier"] == ">=0.11,<0.12"


def test_engine_scripts_that_declare_ragmark_pin_the_index_fastembed() -> None:
    declared = _engine_scripts_declaring_ragmark()
    assert RAGMARK_ENGINE_SCRIPTS <= set(declared)
    assert {
        name: _fastembed_requirements(requirements)
        for name, requirements in declared.items()
        if _fastembed_requirements(requirements) != [FASTEMBED_REQUIREMENT]
    } == {}


def test_machinery_project_pins_the_index_fastembed() -> None:
    data = tomllib.loads((MACHINERY / "pyproject.toml").read_text(encoding="utf-8"))
    requirements = data["project"]["dependencies"]
    assert _fastembed_requirements(requirements) == [FASTEMBED_REQUIREMENT]


def test_machinery_lock_resolves_fastembed_to_the_pin() -> None:
    lock = tomllib.loads((MACHINERY / "uv.lock").read_text(encoding="utf-8"))
    assert [
        package["version"] for package in lock["package"] if package["name"] == "fastembed"
    ] == [FASTEMBED_VERSION]
    project = next(
        package
        for package in lock["package"]
        if package["name"] == "workbench-machinery"
    )
    # The `embeddings` extra's own `fastembed>=0.3` carries a marker; the
    # unconditional requirement is the one the default environment resolves.
    requirements = [
        item
        for item in project["metadata"]["requires-dist"]
        if item["name"] == "fastembed" and "marker" not in item
    ]
    assert [item["specifier"] for item in requirements] == [f"=={FASTEMBED_VERSION}"]


def test_default_machinery_gate_pins_the_index_fastembed() -> None:
    requirements = re.findall(r"--with '([^']+)'", _default_machinery_command())
    assert _fastembed_requirements(requirements) == [FASTEMBED_REQUIREMENT]


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
    "spec", sorted(MACHINERY.glob("teeth-spec-*.json")), ids=lambda p: p.stem
)
@pytest.mark.parametrize("command", ["test_command", "collect_command"])
def test_teeth_commands_that_resolve_ragmark_pin_the_index_fastembed(
    spec: Path, command: str
) -> None:
    argv = json.loads(spec.read_text(encoding="utf-8")).get(command, [])
    if any(_requirement_name(item) == "ragmark" for item in argv):
        assert _fastembed_requirements(argv) == [FASTEMBED_REQUIREMENT]


@pytest.mark.parametrize(
    "target", ["test-wrap-up-gate-parity", "test-cold-read-evidence-wikilink-parity"]
)
def test_owner_ci_parity_leg_stays_separate(target: str) -> None:
    recipe = _recipe(target)
    assert "'graphmark>=0.11,<0.12'" in recipe
    assert "cd plugins/workbench/machinery" not in recipe
    assert f"$(MAKE) {target}" in _recipe("test")


# ---------------------------------------------------------------------------
# The release wheel is declared at nine sites; each must name RAGMARK_WHEEL.
# Before these tests only the Makefile gate was compared to the constant, so a
# bump that missed a script header, pyproject.toml or a lock entry passed.
# ---------------------------------------------------------------------------


def _wheel_url(requirement: str) -> str:
    assert "@" in requirement, requirement
    return requirement.split("@", 1)[1].strip()


@pytest.mark.parametrize("name", sorted(_engine_scripts_declaring_ragmark()))
def test_engine_scripts_pin_the_release_wheel(name: str) -> None:
    requirements = _engine_scripts_declaring_ragmark()[name]
    [ragmark] = [item for item in requirements if _requirement_name(item) == "ragmark"]
    assert _wheel_url(ragmark) == RAGMARK_WHEEL


def test_vault_mcp_script_requires_the_ragmark_mcp_extra() -> None:
    # The wheel URL resolves with or without `[mcp]`, so the check above passes a
    # header that drops it; only the extra installs fastmcp, which
    # `ragmark.mcp.build_server` (what vault_mcp.py builds) needs.
    declared = _engine_scripts_declaring_ragmark()
    assert "vault_mcp.py" in declared
    [ragmark] = [
        item for item in declared["vault_mcp.py"] if _requirement_name(item) == "ragmark"
    ]
    extras = re.match(r"ragmark\s*\[([^\]]*)\]", ragmark)
    assert extras is not None, ragmark
    assert "mcp" in {extra.strip() for extra in extras.group(1).split(",")}


def test_machinery_project_pins_the_release_wheel() -> None:
    data = tomllib.loads((MACHINERY / "pyproject.toml").read_text(encoding="utf-8"))
    [ragmark] = [
        item
        for item in data["project"]["dependencies"]
        if _requirement_name(item) == "ragmark"
    ]
    assert _wheel_url(ragmark) == RAGMARK_WHEEL


def test_machinery_lock_pins_the_release_wheel() -> None:
    lock = tomllib.loads((MACHINERY / "uv.lock").read_text(encoding="utf-8"))
    package = next(item for item in lock["package"] if item["name"] == "ragmark")
    project = next(
        item for item in lock["package"] if item["name"] == "workbench-machinery"
    )
    requirement = next(
        item for item in project["metadata"]["requires-dist"] if item["name"] == "ragmark"
    )
    assert package["source"] == {"url": RAGMARK_WHEEL}
    assert [wheel["url"] for wheel in package["wheels"]] == [RAGMARK_WHEEL]
    assert requirement["url"] == RAGMARK_WHEEL
    assert f"/v{package['version']}/" in RAGMARK_WHEEL
