"""Tests for the warn-off-trunk SessionEnd hook.

Drives the hook as a real subprocess against scratch git repos (and, for the
linked-worktree case, a real `git worktree add`) so branch resolution, TOML
parsing, and worktree detection are exercised for real, not mocked.
"""

from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]
HOOK_PATH = REPO_ROOT / "plugins" / "workbench" / "hooks" / "scripts" / "warn-off-trunk.py"


def run_hook(payload: dict) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        [sys.executable, str(HOOK_PATH)],
        input=json.dumps(payload),
        capture_output=True,
        text=True,
        timeout=30,
    )


# Runs the hook as __main__ with chosen modules made unimportable. A None entry
# in sys.modules makes `import <name>` raise ModuleNotFoundError — the same
# failure a pre-3.11 interpreter gives for `import tomllib`.
_BLOCKING_RUNNER = """
import runpy, sys
hook_path, blocked, alias_tomli = sys.argv[1], sys.argv[2], sys.argv[3] == "1"
if alias_tomli:
    import tomllib
    sys.modules["tomli"] = tomllib
for name in filter(None, blocked.split(",")):
    sys.modules[name] = None
sys.argv = [hook_path]
runpy.run_path(hook_path, run_name="__main__")
"""


def run_hook_without(
    payload: dict, blocked: list[str], alias_tomli: bool = False
) -> subprocess.CompletedProcess[str]:
    """Run the hook with ``blocked`` modules unimportable.

    ``alias_tomli`` stands the stdlib ``tomllib`` in for the third-party
    ``tomli`` backport (same API), so the fallback is exercised without
    ``tomli`` being installed.
    """
    return subprocess.run(
        [
            sys.executable,
            "-c",
            _BLOCKING_RUNNER,
            str(HOOK_PATH),
            ",".join(blocked),
            "1" if alias_tomli else "0",
        ],
        input=json.dumps(payload),
        capture_output=True,
        text=True,
        timeout=30,
    )


def _init_git_repo(path: Path, branch: str = "main") -> None:
    subprocess.run(["git", "init", "-q", "-b", branch], cwd=path, check=True)
    subprocess.run(
        ["git", "config", "user.email", "test@example.com"], cwd=path, check=True
    )
    subprocess.run(["git", "config", "user.name", "Test"], cwd=path, check=True)
    (path / "README.md").write_text("init\n")
    subprocess.run(["git", "add", "-A"], cwd=path, check=True)
    subprocess.run(["git", "commit", "-q", "-m", "init"], cwd=path, check=True)


def _write_config(path: Path, body: str) -> None:
    afk_dir = path / ".afk"
    afk_dir.mkdir(exist_ok=True)
    (afk_dir / "config.toml").write_text(body)


def test_no_afk_config_is_silent(tmp_path: Path) -> None:
    _init_git_repo(tmp_path, branch="feature/x")

    result = run_hook({"cwd": str(tmp_path)})

    assert result.returncode == 0
    assert result.stderr == ""


def test_warn_off_trunk_false_is_silent(tmp_path: Path) -> None:
    _init_git_repo(tmp_path, branch="feature/x")
    _write_config(tmp_path, "[hooks]\nwarn_off_trunk = false\n")

    result = run_hook({"cwd": str(tmp_path)})

    assert result.returncode == 0
    assert result.stderr == ""


def test_on_trunk_is_silent(tmp_path: Path) -> None:
    _init_git_repo(tmp_path, branch="main")
    _write_config(tmp_path, 'trunk_branch = "main"\n')

    result = run_hook({"cwd": str(tmp_path)})

    assert result.returncode == 0
    assert result.stderr == ""


def test_feature_branch_warns(tmp_path: Path) -> None:
    _init_git_repo(tmp_path, branch="feature/thing")
    _write_config(tmp_path, 'trunk_branch = "main"\n')

    result = run_hook({"cwd": str(tmp_path)})

    assert result.returncode == 0
    assert "feature/thing" in result.stderr
    assert "main" in result.stderr


def test_main_when_trunk_is_dev_warns(tmp_path: Path) -> None:
    _init_git_repo(tmp_path, branch="main")
    _write_config(tmp_path, 'trunk_branch = "dev"\n')

    result = run_hook({"cwd": str(tmp_path)})

    assert result.returncode == 0
    assert "main" in result.stderr
    assert "dev" in result.stderr


def test_trunk_branch_absent_defaults_to_main_and_is_silent(tmp_path: Path) -> None:
    _init_git_repo(tmp_path, branch="main")
    _write_config(tmp_path, "[hooks]\nwarn_off_trunk = true\n")

    result = run_hook({"cwd": str(tmp_path)})

    assert result.returncode == 0
    assert result.stderr == ""


def test_detached_head_is_silent(tmp_path: Path) -> None:
    _init_git_repo(tmp_path, branch="main")
    sha = subprocess.run(
        ["git", "rev-parse", "HEAD"],
        cwd=tmp_path,
        capture_output=True,
        text=True,
        check=True,
    ).stdout.strip()
    subprocess.run(["git", "checkout", "-q", sha], cwd=tmp_path, check=True)
    _write_config(tmp_path, 'trunk_branch = "main"\n')

    result = run_hook({"cwd": str(tmp_path)})

    assert result.returncode == 0
    assert result.stderr == ""


def test_linked_worktree_is_silent(tmp_path: Path) -> None:
    main_repo = tmp_path / "main"
    main_repo.mkdir()
    _init_git_repo(main_repo, branch="main")
    _write_config(main_repo, 'trunk_branch = "main"\n')
    subprocess.run(["git", "add", "-A"], cwd=main_repo, check=True)
    subprocess.run(["git", "commit", "-q", "-m", "add config"], cwd=main_repo, check=True)

    worktree_path = tmp_path / "wt"
    subprocess.run(
        ["git", "worktree", "add", "-q", "-b", "feature/wt", str(worktree_path)],
        cwd=main_repo,
        check=True,
    )

    result = run_hook({"cwd": str(worktree_path)})

    assert result.returncode == 0
    assert result.stderr == ""


def test_malformed_toml_is_silent(tmp_path: Path) -> None:
    _init_git_repo(tmp_path, branch="feature/bad")
    _write_config(tmp_path, "this is not [ valid toml")

    result = run_hook({"cwd": str(tmp_path)})

    assert result.returncode == 0
    assert result.stderr == ""


def test_no_toml_parser_is_silent(tmp_path: Path) -> None:
    # A pre-3.11 interpreter with no tomli installed — the headless afk
    # executor's environment. The repo would otherwise warn, so silence here
    # proves the hook skipped rather than crashed.
    _init_git_repo(tmp_path, branch="feature/thing")
    _write_config(tmp_path, 'trunk_branch = "main"\n')

    result = run_hook_without({"cwd": str(tmp_path)}, blocked=["tomllib", "tomli"])

    assert result.returncode == 0
    assert result.stderr == ""


def test_tomli_fallback_still_warns(tmp_path: Path) -> None:
    _init_git_repo(tmp_path, branch="feature/thing")
    _write_config(tmp_path, 'trunk_branch = "main"\n')

    result = run_hook_without(
        {"cwd": str(tmp_path)}, blocked=["tomllib"], alias_tomli=True
    )

    assert result.returncode == 0
    assert "feature/thing" in result.stderr
    assert "Traceback" not in result.stderr
