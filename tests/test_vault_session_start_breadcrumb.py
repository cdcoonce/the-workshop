"""The SessionStart breadcrumb identifies the plugin copy that actually ran.

`vault-session-start.py` writes `.vault/plugin-state*.json` so the vault can tell
which plugin root/version served a session. Each test runs the real hook from a
fake plugin cache laid out under a scratch HOME, so the platform is decided by
the root path (not by environment variables) exactly as it is in production.
"""

from __future__ import annotations

import json
import os
import shutil
import subprocess
import sys
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parents[1]
PLUGIN = REPO_ROOT / "plugins" / "workbench"
SCRIPTS = PLUGIN / "hooks" / "scripts"
GITIGNORE_TMPL = PLUGIN / "machinery" / "scaffold" / "gitignore.tmpl"
CHECK_PLUGIN = PLUGIN / "machinery" / "scaffold" / "vault" / "check-plugin.sh"

ROOTS = {
    "claude-code": ".claude/plugins/cache/the-workshop/workbench/9.9.9",
    "codex": ".codex/plugins/cache/the-workshop/workbench/9.9.9",
    "cortex": ".snowflake/cortex/plugins/workbench",
    "other": "somewhere/else/workbench",
}


def _fake_plugin(home: Path, relative: str, version: str = "9.9.9") -> Path:
    root = home / relative
    (root / "hooks").mkdir(parents=True)
    shutil.copytree(SCRIPTS, root / "hooks" / "scripts", ignore=shutil.ignore_patterns("__pycache__"))
    (root / ".claude-plugin").mkdir()
    (root / ".claude-plugin" / "plugin.json").write_text(json.dumps({"name": "workbench", "version": version}))
    engine = root / "machinery" / "engine"
    engine.mkdir(parents=True)
    # Stand-in engine: records what it was handed on stdin, then does nothing.
    (engine / "session-start.py").write_text(
        "import os, sys\n"
        "open(os.path.join(os.environ['CLAUDE_PROJECT_DIR'], 'engine-stdin.txt'), 'w')"
        ".write(sys.stdin.read())\n"
    )
    return root


def _run(
    root: Path, home: Path, vault: Path | None, stdin: str = "", plugin_root_env: bool = True
) -> subprocess.CompletedProcess[str]:
    env = {"PATH": os.environ["PATH"], "HOME": str(home)}
    if vault is not None:
        env["CLAUDE_PROJECT_DIR"] = str(vault)
    if plugin_root_env:
        env["CLAUDE_PLUGIN_ROOT"] = str(root)
    return subprocess.run(
        [sys.executable, str(root / "hooks" / "scripts" / "vault-session-start.py")],
        input=stdin,
        capture_output=True,
        text=True,
        timeout=30,
        env=env,
    )


def _payload(path: Path) -> dict:
    return json.loads(path.read_text())


@pytest.fixture
def home(tmp_path: Path) -> Path:
    path = tmp_path / "home"
    path.mkdir()
    return path.resolve()


@pytest.fixture
def vault(tmp_path: Path) -> Path:
    path = tmp_path / "vault"
    (path / ".vault").mkdir(parents=True)
    return path


@pytest.mark.parametrize("platform", sorted(ROOTS))
def test_platform_comes_from_the_root_path_not_the_environment(
    home: Path, vault: Path, platform: str
) -> None:
    root = _fake_plugin(home, ROOTS[platform])

    result = _run(root, home, vault, plugin_root_env=True)

    assert result.returncode == 0, result.stderr
    record = _payload(vault / ".vault" / f"plugin-state.{platform}.json")
    assert record["platform"] == platform
    assert record["root"] == str(root.resolve())
    assert record["version"] == "9.9.9"


def test_codex_root_with_claude_plugin_root_set_reports_codex(home: Path, vault: Path) -> None:
    root = _fake_plugin(home, ROOTS["codex"])

    _run(root, home, vault, plugin_root_env=True)

    assert _payload(vault / ".vault" / "plugin-state.json")["platform"] == "codex"
    assert not (vault / ".vault" / "plugin-state.claude-code.json").exists()


def test_two_platforms_in_one_vault_keep_separate_records(home: Path, vault: Path) -> None:
    claude = _fake_plugin(home, ROOTS["claude-code"], version="8.10.0")
    codex = _fake_plugin(home, ROOTS["codex"], version="8.10.1")

    _run(claude, home, vault)
    _run(codex, home, vault)

    first = _payload(vault / ".vault" / "plugin-state.claude-code.json")
    second = _payload(vault / ".vault" / "plugin-state.codex.json")
    assert (first["version"], first["platform"]) == ("8.10.0", "claude-code")
    assert (second["version"], second["platform"]) == ("8.10.1", "codex")


def test_legacy_breadcrumb_is_still_written_and_parses_under_check_plugin(
    home: Path, vault: Path
) -> None:
    root = _fake_plugin(home, ROOTS["claude-code"], version="9.9.9")
    (vault / ".vault" / "vault.json").write_text('{"min_plugin_version": "1.0.0"}\n')
    shutil.copy2(CHECK_PLUGIN, vault / ".vault" / "check-plugin.sh")

    _run(root, home, vault)

    legacy = vault / ".vault" / "plugin-state.json"
    assert _payload(legacy)["version"] == "9.9.9"
    check = subprocess.run(
        ["bash", str(vault / ".vault" / "check-plugin.sh")], capture_output=True, text=True, timeout=30
    )
    assert check.returncode == 0
    assert check.stderr == ""
    assert not (vault / ".vault" / ".plugin-miss-count").exists()


def test_successive_sessions_with_unchanged_root_and_version_are_distinguishable(
    home: Path, vault: Path
) -> None:
    root = _fake_plugin(home, ROOTS["claude-code"])
    target = vault / ".vault" / "plugin-state.claude-code.json"

    _run(root, home, vault, stdin=json.dumps({"session_id": "sess-one"}))
    first = target.read_text()
    _run(root, home, vault, stdin=json.dumps({"session_id": "sess-two"}))
    second = target.read_text()

    assert first != second
    assert json.loads(first)["session"] == "sess-one"
    assert json.loads(second)["session"] == "sess-two"
    assert json.loads(first)["root"] == json.loads(second)["root"]


def test_identical_rewrite_is_not_skipped(home: Path, vault: Path) -> None:
    root = _fake_plugin(home, ROOTS["claude-code"])
    target = vault / ".vault" / "plugin-state.claude-code.json"
    stdin = json.dumps({"session_id": "same"})

    _run(root, home, vault, stdin=stdin)
    os.utime(target, ns=(1, 1))
    _run(root, home, vault, stdin=stdin)

    assert target.stat().st_mtime_ns != 1, "an identical payload was skipped instead of rewritten"


@pytest.mark.parametrize("stdin", ["", "not json", "[]", json.dumps({"session_id": 5}), json.dumps({"session_id": ""})])
def test_session_falls_back_to_a_utc_timestamp_without_a_session_id(
    home: Path, vault: Path, stdin: str
) -> None:
    root = _fake_plugin(home, ROOTS["codex"])

    _run(root, home, vault, stdin=stdin)

    session = _payload(vault / ".vault" / "plugin-state.codex.json")["session"]
    assert isinstance(session, str) and session
    assert session.endswith("+00:00") or session.endswith("Z")


def test_engine_still_receives_the_hook_payload(home: Path, vault: Path) -> None:
    root = _fake_plugin(home, ROOTS["claude-code"])
    stdin = json.dumps({"session_id": "sess-x", "source": "startup"})

    _run(root, home, vault, stdin=stdin)

    assert (vault / "engine-stdin.txt").read_text() == stdin


def test_hook_fails_open_when_the_breadcrumb_cannot_be_written(home: Path) -> None:
    root = _fake_plugin(home, ROOTS["claude-code"])

    result = _run(root, home, None)  # no CLAUDE_PROJECT_DIR at all

    assert result.returncode == 0
    assert "Traceback" not in result.stderr


def test_docstring_no_longer_cites_commit_churn() -> None:
    source = (SCRIPTS / "vault-session-start.py").read_text()
    assert "churn" not in source
    assert "manufacture a commit" not in source


@pytest.mark.parametrize("platform", ["claude-code", "codex", "cortex", "other"])
def test_scaffolded_gitignore_covers_every_per_platform_breadcrumb(
    tmp_path: Path, platform: str
) -> None:
    repo = tmp_path / "repo"
    (repo / ".vault").mkdir(parents=True)
    subprocess.run(["git", "init", "-q"], cwd=repo, check=True)
    (repo / ".gitignore").write_text(GITIGNORE_TMPL.read_text())

    result = subprocess.run(
        ["git", "check-ignore", "-q", f".vault/plugin-state.{platform}.json"], cwd=repo
    )

    assert result.returncode == 0


@pytest.mark.skipif(sys.platform == "win32", reason="needs POSIX fd semantics")
def test_closed_stdin_still_runs_the_engine(home: Path, vault: Path) -> None:
    """With fd 0 closed, ``sys.stdin`` is None; the breadcrumb must not abort the hook."""
    root = _fake_plugin(home, ROOTS["codex"])
    (root / "machinery" / "engine" / "session-start.py").write_text(
        "import os\n"
        "open(os.path.join(os.environ['CLAUDE_PROJECT_DIR'], 'engine-stdin.txt'), 'w').write('ran')\n"
    )
    env = {"PATH": os.environ["PATH"], "HOME": str(home), "CLAUDE_PROJECT_DIR": str(vault)}

    result = subprocess.run(
        [sys.executable, str(root / "hooks" / "scripts" / "vault-session-start.py")],
        capture_output=True,
        text=True,
        timeout=30,
        env=env,
        preexec_fn=lambda: os.close(0),
    )

    assert result.returncode == 0
    assert "Traceback" not in result.stderr
    assert (vault / "engine-stdin.txt").exists()


def test_worktree_session_refreshes_the_worktree_breadcrumb(home: Path, vault: Path) -> None:
    """A session running in a linked worktree writes its breadcrumb there too.

    For a worktree session Claude Code's ``CLAUDE_PROJECT_DIR`` names the main
    checkout, so the worktree's own gitignored breadcrumb was never refreshed.
    It kept naming a plugin root long since pruned from the cache, and the
    vault's local gate (``tests/test_vault_gate.py``) failed on it from inside
    the worktree while the main checkout's copy was fresh. The hook payload's
    ``cwd`` is where the session actually runs; sessions routinely start in a
    subdirectory, so the breadcrumb goes to the vault root enclosing it.
    """
    root = _fake_plugin(home, ROOTS["claude-code"])
    worktree = vault / ".claude" / "worktrees" / "nifty"
    (worktree / ".vault").mkdir(parents=True)
    (worktree / ".vault" / "vault.json").write_text("{}\n")  # tracked: every worktree has it
    stale = {"platform": "claude-code", "root": str(home / "pruned" / "8.15.6"), "version": "8.15.6"}
    (worktree / ".vault" / "plugin-state.json").write_text(json.dumps(stale))
    (worktree / "notes").mkdir()

    result = _run(
        root, home, vault, stdin=json.dumps({"session_id": "wt", "cwd": str(worktree / "notes")})
    )

    assert result.returncode == 0, result.stderr
    for name in ("plugin-state.json", "plugin-state.claude-code.json"):
        record = _payload(worktree / ".vault" / name)
        assert record["root"] == str(root.resolve()), name
        assert record["version"] == "9.9.9", name
        assert record["session"] == "wt", name
    assert _payload(vault / ".vault" / "plugin-state.json")["root"] == str(root.resolve())


def test_cwd_outside_any_vault_leaves_only_the_project_breadcrumb(home: Path, vault: Path) -> None:
    """A cwd that is in no vault (``~`` on /clear) must not sprout a ``.vault/``."""
    root = _fake_plugin(home, ROOTS["claude-code"])
    elsewhere = home / "elsewhere"
    elsewhere.mkdir()

    result = _run(root, home, vault, stdin=json.dumps({"cwd": str(elsewhere)}))

    assert result.returncode == 0, result.stderr
    assert _payload(vault / ".vault" / "plugin-state.json")["version"] == "9.9.9"
    assert not (elsewhere / ".vault").exists()
    assert not (home / ".vault").exists()


def test_ordinary_checkout_cwd_writes_nowhere_new(home: Path, vault: Path) -> None:
    """In a plain checkout the cwd's vault IS the project dir: one root, as before."""
    root = _fake_plugin(home, ROOTS["claude-code"])
    (vault / ".vault" / "vault.json").write_text("{}\n")
    (vault / "notes").mkdir()

    _run(root, home, vault, stdin=json.dumps({"session_id": "plain", "cwd": str(vault / "notes")}))

    assert _payload(vault / ".vault" / "plugin-state.json")["session"] == "plain"
    assert not (vault / "notes" / ".vault").exists()


def _seed_shared(vault: Path, platform: str, root: Path, version: str) -> None:
    record = {"platform": platform, "root": str(root), "version": version, "session": "seed"}
    (vault / ".vault" / "plugin-state.json").write_text(json.dumps(record))


def test_other_platforms_live_shared_record_is_not_overwritten(home: Path, vault: Path) -> None:
    """The shared file is last-writer-wins; a live record from another platform stays.

    Codex starting after Claude Code must not replace a shared record whose root
    still exists, or one platform's start decides the other's vault gate.
    """
    claude = _fake_plugin(home, ROOTS["claude-code"], version="8.43.0")
    codex = _fake_plugin(home, ROOTS["codex"], version="8.46.2")
    _run(claude, home, vault)

    _run(codex, home, vault)

    assert _payload(vault / ".vault" / "plugin-state.json")["platform"] == "claude-code"
    assert _payload(vault / ".vault" / "plugin-state.codex.json")["version"] == "8.46.2"


def test_dangling_shared_record_from_another_platform_is_replaced(home: Path, vault: Path) -> None:
    """A Codex record whose cache copy was pruned must not outlive the next session."""
    claude = _fake_plugin(home, ROOTS["claude-code"], version="8.43.0")
    _seed_shared(vault, "codex", home / ".codex/plugins/cache/the-workshop/workbench/8.37.8", "8.37.8")

    _run(claude, home, vault)

    shared = _payload(vault / ".vault" / "plugin-state.json")
    assert (shared["platform"], shared["version"]) == ("claude-code", "8.43.0")


def test_same_platform_always_refreshes_the_shared_record(home: Path, vault: Path) -> None:
    old = _fake_plugin(home, ROOTS["codex"], version="8.37.8")
    _run(old, home, vault)
    new = _fake_plugin(home, ".codex/plugins/cache/the-workshop/workbench/9.9.10", version="9.9.10")

    _run(new, home, vault)

    assert _payload(vault / ".vault" / "plugin-state.json")["version"] == "9.9.10"


def test_unreadable_shared_record_is_replaced(home: Path, vault: Path) -> None:
    root = _fake_plugin(home, ROOTS["codex"])
    (vault / ".vault" / "plugin-state.json").write_text("not json")

    _run(root, home, vault)

    assert _payload(vault / ".vault" / "plugin-state.json")["platform"] == "codex"
