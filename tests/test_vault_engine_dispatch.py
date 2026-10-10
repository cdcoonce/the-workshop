"""The vault hook wrappers share one fail-open runpy dispatcher.

Each `vault-*.py` hook is a thin entry point that keeps only its top-level
`WORKSHOP_HOOK` literal (read statically by `scripts/stamp.py`) and delegates to
`_vault_engine_dispatch.run_engine_script`, instead of re-declaring the same
try/runpy/except block six times.
"""

from __future__ import annotations

import ast
import importlib.util
import sys
from pathlib import Path
from types import ModuleType

import pytest

REPO_ROOT = Path(__file__).resolve().parents[1]
SCRIPTS = REPO_ROOT / "plugins" / "workbench" / "hooks" / "scripts"
DISPATCH = SCRIPTS / "_vault_engine_dispatch.py"

WRAPPERS = {
    "vault-pre-compact.py": "pre-compact.py",
    "vault-session-start.py": "session-start.py",
    "vault-stop-1-notebook-update.py": "notebook-update.py",
    "vault-stop-2-graph-gardener.py": "graph_gardener.py",
    "vault-stop-3-session-sync.py": "session-stop.py",
    "vault-validate-write.py": "validate-write.py",
}


def _load_dispatch() -> ModuleType:
    assert DISPATCH.exists(), "shared dispatcher missing"
    spec = importlib.util.spec_from_file_location("_vault_engine_dispatch", DISPATCH)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


@pytest.fixture
def dispatch(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> ModuleType:
    module = _load_dispatch()
    engine = tmp_path / "engine"
    engine.mkdir()
    monkeypatch.setattr(module, "ENGINE_DIR", engine)
    monkeypatch.setattr(sys, "path", list(sys.path))
    monkeypatch.setattr(sys, "argv", ["wrapper.py"])
    return module


def _engine_script(module: ModuleType, name: str, body: str) -> Path:
    path = module.ENGINE_DIR / name
    path.write_text(body)
    return path


def test_dispatcher_runs_the_engine_script_as_main(
    dispatch: ModuleType, tmp_path: Path
) -> None:
    marker = tmp_path / "ran.txt"
    target = _engine_script(
        dispatch,
        "ok.py",
        f"import sys\nif __name__ == '__main__':\n"
        f"    open({str(marker)!r}, 'w').write(repr(sys.argv))\n",
    )

    dispatch.run_engine_script("ok.py")

    assert marker.read_text() == repr([str(target)])
    assert str(dispatch.ENGINE_DIR) in sys.path


def test_dispatcher_forwards_extra_argv(dispatch: ModuleType, tmp_path: Path) -> None:
    marker = tmp_path / "argv.txt"
    target = _engine_script(
        dispatch, "args.py", f"import sys\nopen({str(marker)!r}, 'w').write(repr(sys.argv))\n"
    )

    dispatch.run_engine_script("args.py", extra_argv=["--explicit-sync"])

    assert marker.read_text() == repr([str(target), "--explicit-sync"])


def test_dispatcher_propagates_the_engine_exit_code(dispatch: ModuleType) -> None:
    _engine_script(dispatch, "exits.py", "import sys\nsys.exit(3)\n")

    with pytest.raises(SystemExit) as info:
        dispatch.run_engine_script("exits.py")

    assert info.value.code == 3


@pytest.mark.parametrize("script", ["boom.py", "missing.py"])
def test_dispatcher_fails_open_on_a_broken_or_missing_engine(
    dispatch: ModuleType, capsys: pytest.CaptureFixture[str], script: str
) -> None:
    _engine_script(dispatch, "boom.py", "raise RuntimeError('kaput')\n")

    with pytest.raises(SystemExit) as info:
        dispatch.run_engine_script(script)

    assert info.value.code == 0
    assert f"vault hook {script} failed" in capsys.readouterr().err


def test_before_hook_runs_first_and_fails_open(
    dispatch: ModuleType, tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    marker = tmp_path / "engine-ran.txt"
    _engine_script(dispatch, "e.py", f"open({str(marker)!r}, 'w').write('x')\n")

    def _bad_before() -> None:
        raise OSError("disk on fire")

    with pytest.raises(SystemExit) as info:
        dispatch.run_engine_script("e.py", before=_bad_before)

    assert info.value.code == 0
    assert "disk on fire" in capsys.readouterr().err


@pytest.mark.parametrize("wrapper", sorted(WRAPPERS))
def test_wrapper_is_declaration_plus_one_dispatch_call(wrapper: str) -> None:
    source = (SCRIPTS / wrapper).read_text()
    tree = ast.parse(source)

    assert "runpy" not in source, f"{wrapper} still re-implements the runpy block"
    assert WRAPPERS[wrapper] in source

    declares = [
        n
        for n in tree.body
        if isinstance(n, ast.Assign)
        and any(isinstance(t, ast.Name) and t.id == "WORKSHOP_HOOK" for t in n.targets)
    ]
    assert len(declares) == 1
    ast.literal_eval(declares[0].value)  # stamp.py reads it statically

    calls = [
        n
        for n in ast.walk(tree)
        if isinstance(n, ast.Call)
        and getattr(n.func, "id", None) == "run_engine_script"
    ]
    assert len(calls) == 1
