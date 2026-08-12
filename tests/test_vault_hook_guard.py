"""Guards the vault hook runner: it must cost nothing outside a vault.

The flat reorg moved the vault's engine into `plugins/workbench/machinery/`,
so the vault's seven hooks now have to fire from the plugin rather than from a
vendored `.claude/scripts/`. Those hooks are wired into workbench's
`hooks.json`, which every consumer of workbench loads -- so they run on every
session in every repo, vault or not.

That makes the guard load-bearing in a way a normal hook is not: a non-vault
repo must pay nothing. Not "exit early in Python" -- `uv run` on a cold cache
is the expensive part, and a Python-level check has already paid it.

So the assertions here count PROCESS SPAWNS, not exit codes. A guard that
exits 0 correctly while still having spawned `uv` passes an exit-code test and
fails the actual requirement. `run-vault-hook.sh` is driven as a real
subprocess with a fake `uv` and a fake `python3` on PATH that record every
invocation to a file; the test reads that file.
"""

import os
import shutil
import subprocess
import sys
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parents[1]
RUNNER = REPO_ROOT / "plugins" / "workbench" / "hooks" / "run-vault-hook.sh"


def _spy_bin(tmp_path: Path) -> Path:
    """A PATH dir whose `uv` and `python3` only append their argv to a log."""
    bin_dir = tmp_path / "spybin"
    bin_dir.mkdir(parents=True, exist_ok=True)
    log = tmp_path / "spawns.log"
    for name in ("uv", "python3", "python"):
        shim = bin_dir / name
        shim.write_text(f'#!/usr/bin/env bash\necho "{name} $*" >> "{log}"\nexit 0\n')
        shim.chmod(0o755)
    return bin_dir


def _spawns(tmp_path: Path) -> list[str]:
    log = tmp_path / "spawns.log"
    return log.read_text().splitlines() if log.exists() else []


def _run(project_dir: Path, tmp_path: Path, *args: str) -> subprocess.CompletedProcess:
    env = dict(os.environ)
    env["PATH"] = f"{_spy_bin(tmp_path)}:{env['PATH']}"
    env["CLAUDE_PROJECT_DIR"] = str(project_dir)
    return subprocess.run(
        ["bash", str(RUNNER), "session-start.py"],
        capture_output=True,
        text=True,
        env=env,
        cwd=str(project_dir),
    )


def _make_vault(root: Path) -> Path:
    (root / ".vault").mkdir(parents=True, exist_ok=True)
    (root / ".vault" / "vault.json").write_text('{"min_plugin_version": "4.1.0"}\n')
    return root


@pytest.fixture
def plain_repo(tmp_path: Path) -> Path:
    repo = tmp_path / "some-project"
    (repo / "src").mkdir(parents=True)
    (repo / "CLAUDE.md").write_text("# A normal project that is not the vault\n")
    return repo


def test_non_vault_repo_spawns_nothing(plain_repo: Path, tmp_path: Path) -> None:
    """The whole point: no `uv`, no `python3`, in a repo that is not a vault."""
    result = _run(plain_repo, tmp_path)
    assert result.returncode == 0, result.stderr
    assert _spawns(tmp_path) == [], (
        "the guard spawned a process in a non-vault repo; exiting 0 is not "
        f"enough, it must cost nothing: {_spawns(tmp_path)}"
    )


def test_vault_repo_does_spawn_the_hook(tmp_path: Path) -> None:
    """The mirror image -- a guard that never fires would pass the test above.

    Without this, deleting the runner's body entirely would leave the suite
    green while every vault hook silently stopped running.
    """
    vault = _make_vault(tmp_path / "the-vault")
    result = _run(vault, tmp_path)
    assert result.returncode == 0, result.stderr
    spawns = _spawns(tmp_path)
    assert spawns, "the guard refused to run the hook inside a real vault"
    assert any("session-start.py" in s for s in spawns), (
        f"the hook script was not the thing invoked: {spawns}"
    )


def test_vault_marker_is_found_from_a_subdirectory(tmp_path: Path) -> None:
    """Sessions start in subdirectories; the marker lives at the vault root."""
    vault = _make_vault(tmp_path / "the-vault")
    nested = vault / "work" / "active"
    nested.mkdir(parents=True)
    result = _run(nested, tmp_path)
    assert result.returncode == 0, result.stderr
    assert _spawns(tmp_path), "walking up from a subdirectory failed to find the vault"


def test_marker_is_what_gates_not_merely_a_claude_md(
    plain_repo: Path, tmp_path: Path
) -> None:
    """`.vault/vault.json` is the marker -- a CLAUDE.md must not be enough.

    `plain_repo` already ships a CLAUDE.md, which many repos do. Matching on
    that is the exact bug `vault_utils.find_vault_root` was hardened against
    after the auto-commit ran inside a non-vault repo.
    """
    result = _run(plain_repo, tmp_path)
    assert result.returncode == 0
    assert _spawns(tmp_path) == []

    _make_vault(plain_repo)
    result = _run(plain_repo, tmp_path)
    assert result.returncode == 0, result.stderr
    assert _spawns(tmp_path), "adding the marker did not enable the hook"


def test_runner_survives_an_unset_project_dir(tmp_path: Path) -> None:
    """Cortex and Codex do not set CLAUDE_PROJECT_DIR; cwd must be the fallback."""
    vault = _make_vault(tmp_path / "the-vault")
    env = dict(os.environ)
    env["PATH"] = f"{_spy_bin(tmp_path)}:{env['PATH']}"
    env.pop("CLAUDE_PROJECT_DIR", None)
    result = subprocess.run(
        ["bash", str(RUNNER), "session-start.py"],
        capture_output=True,
        text=True,
        env=env,
        cwd=str(vault),
    )
    assert result.returncode == 0, result.stderr
    assert _spawns(tmp_path), "cwd fallback failed when CLAUDE_PROJECT_DIR was unset"


def test_extra_args_reach_the_hook(tmp_path: Path) -> None:
    """`session-stop.py --explicit-sync` must keep its flag."""
    vault = _make_vault(tmp_path / "the-vault")
    env = dict(os.environ)
    env["PATH"] = f"{_spy_bin(tmp_path)}:{env['PATH']}"
    env["CLAUDE_PROJECT_DIR"] = str(vault)
    subprocess.run(
        ["bash", str(RUNNER), "vault-session-stop.py", "--explicit-sync"],
        capture_output=True,
        text=True,
        env=env,
        cwd=str(vault),
    )
    assert any("--explicit-sync" in s for s in _spawns(tmp_path)), (
        f"forwarded args were dropped: {_spawns(tmp_path)}"
    )


def test_runner_is_executable_and_present() -> None:
    assert RUNNER.exists(), f"{RUNNER} is missing"
    assert shutil.which("bash"), "bash is required to run these guards"


# --------------------------------------------------------------------------- #
# Wiring: the seven hooks the vault actually runs, and their order
# --------------------------------------------------------------------------- #

import json  # noqa: E402

HOOKS_JSON = REPO_ROOT / "plugins" / "workbench" / "hooks" / "hooks.json"


def _vault_wiring() -> dict[str, list[str]]:
    """Event -> ordered vault hook scripts, as generated into hooks.json."""
    doc = json.loads(HOOKS_JSON.read_text())["hooks"]
    out: dict[str, list[str]] = {}
    for event, entries in doc.items():
        for entry in entries:
            for hook in entry.get("hooks", []):
                command = hook.get("command", "")
                if "run-vault-hook.sh" in command:
                    out.setdefault(event, []).append(command.rsplit(" ", 1)[-1])
    return out


def test_all_seven_vault_hooks_are_wired() -> None:
    """The vault ran seven hooks before the cutover; it must run seven after.

    Sourced from the vault's own settings.json at the time of #667. A hook that
    silently fails to move is the failure mode this whole issue exists to
    prevent, and it is invisible until someone notices a thing stopped working.
    """
    wiring = _vault_wiring()
    assert wiring.get("SessionStart") == ["vault-session-start.py"]
    assert wiring.get("UserPromptSubmit") == ["vault-user-prompt-classify.py"]
    assert wiring.get("PreCompact") == ["vault-pre-compact.py"]
    assert wiring.get("PostToolUse") == ["vault-validate-write.py"]
    assert len(wiring.get("Stop", [])) == 3
    assert sum(len(v) for v in wiring.values()) == 7


def test_session_sync_runs_last_on_stop() -> None:
    """Ordering is load-bearing: the sync commits what the others wrote.

    render_hooks_json sorts by script name, so the numeric prefixes in
    `vault-stop-N-*.py` ARE the ordering mechanism. Renaming one without
    renumbering would reorder the Stop chain silently, and the symptom would be
    a session's notebook update landing one commit late.
    """
    stop = _vault_wiring().get("Stop", [])
    assert stop == [
        "vault-stop-1-notebook-update.py",
        "vault-stop-2-graph-gardener.py",
        "vault-stop-3-session-sync.py",
    ], f"Stop chain order changed: {stop}"


def test_vault_hooks_route_through_the_guard_not_the_plain_runner() -> None:
    """A vault hook on `run-hook.sh` would run in every repo, unguarded."""
    doc = json.loads(HOOKS_JSON.read_text())["hooks"]
    for event, entries in doc.items():
        for entry in entries:
            for hook in entry.get("hooks", []):
                command = hook.get("command", "")
                script = command.rsplit(" ", 1)[-1]
                if script.startswith("vault-"):
                    assert "run-vault-hook.sh" in command, (
                        f"{script} ({event}) bypasses the guard: {command}"
                    )


def test_machinery_declares_its_own_dependencies() -> None:
    """Engine deps live with the engine, not in the vault owner's pyproject."""
    pyproject = REPO_ROOT / "plugins" / "workbench" / "machinery" / "pyproject.toml"
    assert pyproject.exists(), "machinery/pyproject.toml is missing"
    text = pyproject.read_text()
    for dep in ("pyyaml", "numpy", "graphmark"):
        assert dep in text, f"{dep} is imported by the engine but not declared"


ENGINE = REPO_ROOT / "plugins" / "workbench" / "machinery" / "engine"

# An owner `context_paths.py`. Both names are required: the engine imports them
# in one `from context_paths import A, B`, so a config missing either falls back
# wholesale. The value is deliberately unlike any shipped default, so a passing
# assertion can only mean the owner's file was the source.
_OWNER_CONTEXT_PATHS = """\
COMMON_NOTE_PATHS = {"sentinel": "sentinel/owner-note.md"}
CONTEXT_NOTE_PATHS = {}
"""


def test_owner_config_dir_is_exported_onto_pythonpath(tmp_path: Path) -> None:
    """`.vault/config/` must be on PYTHONPATH, or owner overrides vanish silently.

    Three owner-config modules -- `context_paths`, `content_routing`, and
    `budget_burn_config` -- are still resolved by bare name inside a
    `try: import / except ImportError: use shipped default`, and this export is
    the only thing that makes them findable. That fallback is SILENT, so a
    runner that drops the export reverts every one of those overrides with
    nothing logged and nothing failing.

    `vault_scope` is deliberately no longer in that list: it anchors on the
    vault root instead, because the export alone could never deliver it while
    the engine shipped a module of the same name (#691).

    Asserted through the spy: PYTHONPATH is exported into the child's env. That
    is all this test can see -- whether the export then does its job is
    `test_owner_config_actually_reaches_the_engine` below, and the two are
    separate on purpose. An earlier version of this test asserted only the
    export while claiming to protect `vault_scope` overrides, and passed for as
    long as those overrides were in fact being discarded.
    """
    vault = _make_vault(tmp_path / "the-vault")
    (vault / ".vault" / "config").mkdir(parents=True, exist_ok=True)
    bin_dir = _spy_bin(tmp_path)
    # Overwrite the uv spy so it records PYTHONPATH rather than argv.
    (bin_dir / "uv").write_text(
        f'#!/usr/bin/env bash\necho "PYTHONPATH=$PYTHONPATH" >> "{tmp_path}/spawns.log"\nexit 0\n'
    )
    (bin_dir / "uv").chmod(0o755)

    env = dict(os.environ)
    env["PATH"] = f"{bin_dir}:{env['PATH']}"
    env["CLAUDE_PROJECT_DIR"] = str(vault)
    env.pop("PYTHONPATH", None)
    subprocess.run(
        ["bash", str(RUNNER), "vault-session-start.py"],
        capture_output=True,
        text=True,
        env=env,
        cwd=str(vault),
    )
    recorded = "\n".join(_spawns(tmp_path))
    assert str(vault / ".vault" / "config") in recorded, (
        "the owner config dir is not on PYTHONPATH, so the name-imported owner "
        f"config modules would silently fall back to shipped defaults: {recorded!r}"
    )


def test_owner_config_actually_reaches_the_engine(tmp_path: Path) -> None:
    """The export must deliver a value, not merely be present in the environment.

    This is the assertion the previous guard was missing. It checked that
    PYTHONPATH carried the config dir and stopped there -- an input that cannot
    separate "the override arrived" from "the override was shadowed by a
    shipped module of the same name", so it passed under both.

    Arranged exactly as a vault hook does: the engine directory prepended to
    `sys.path` (which is what put it ahead of PYTHONPATH and caused #691), the
    owner config directory on PYTHONPATH. Run as a real subprocess, because in
    this process the engine modules are already imported and module caching,
    not path ordering, would decide the result.
    """
    vault = _make_vault(tmp_path / "the-vault")
    config_dir = vault / ".vault" / "config"
    config_dir.mkdir(parents=True, exist_ok=True)
    (config_dir / "context_paths.py").write_text(_OWNER_CONTEXT_PATHS)

    env = dict(os.environ)
    env["PYTHONPATH"] = str(config_dir)
    env["CLAUDE_PROJECT_DIR"] = str(vault)
    probe = (
        f"import sys; sys.path.insert(0, {str(ENGINE)!r})\n"
        "import context_loader\n"
        "print(context_loader.COMMON_NOTE_PATHS)\n"
    )
    result = subprocess.run(
        [sys.executable, "-c", probe],
        capture_output=True,
        text=True,
        env=env,
        cwd=str(vault),
    )

    assert result.returncode == 0, result.stderr
    assert "sentinel/owner-note.md" in result.stdout, (
        "the owner's context_paths override did not reach the engine; the "
        f"config dir is on PYTHONPATH but something outranks it: {result.stdout!r}"
    )
