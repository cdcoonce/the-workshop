"""Tests for ``readers.py``: who else uses a tree, index, venv or cache (#1151).

Real child processes, no mock of ``ps``. Each docstring names the defect the
test guards.
"""

from __future__ import annotations

import json
import os
import plistlib
import re
import shutil
import subprocess
import sys
import uuid
from pathlib import Path

import pytest

SCRIPTS = Path(__file__).resolve().parents[1]
SKILL = SCRIPTS.parent / "SKILL.md"
sys.path.insert(0, str(SCRIPTS))

import readers  # noqa: E402

BLIND = (
    "Blind spots: an open-handle probe misses stores opened per query; nothing "
    "here shows how often a reader is exercised, only that it exists or would "
    "start."
)
SLEEP = "import time; time.sleep(60)"
SECRET = "s3cr3t-value"


def needle_token() -> str:
    return "nd" + uuid.uuid4().hex[:12]


@pytest.fixture
def children():
    started: list[subprocess.Popen] = []

    def spawn(argv, **kwargs):
        child = subprocess.Popen(
            argv,
            stdin=subprocess.DEVNULL,
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
            **kwargs,
        )
        started.append(child)
        return child

    yield spawn
    for child in started:
        child.terminate()
        try:
            child.wait(timeout=10)
        except subprocess.TimeoutExpired:
            child.kill()
            child.wait()


@pytest.fixture
def home(tmp_path) -> Path:
    path = tmp_path / "home"
    path.mkdir()
    return path


def call(argv, capsys, home: Path | None = None):
    """Run ``main`` in JSON mode; return (exit code, parsed object)."""
    full = list(argv) + ["--json"]
    if home is not None:
        full += ["--home", str(home)]
    code = readers.main(full)
    return code, json.loads(capsys.readouterr().out)


def call_text(argv, capsys, home: Path):
    code = readers.main(list(argv) + ["--home", str(home)])
    return code, capsys.readouterr().out


def write_claude(home: Path, data: dict) -> None:
    (home / ".claude.json").write_text(json.dumps(data))


def declared_of(obj) -> list[dict]:
    return obj["declared"]


def long_child(children, tmp_path):
    token = needle_token()
    directory = tmp_path / ("d" * 150) / token
    directory.mkdir(parents=True)
    argv = [sys.executable, "-c", SLEEP, str(directory / "server.py")]
    return children(argv), argv, f"{token}/server.py"


def test_long_command_line_is_matched_and_printed_untruncated(
    children, tmp_path, home, capsys
) -> None:
    """Defect: the command line is cut (cut -c1-160) so the script name is hidden."""
    child, argv, needle = long_child(children, tmp_path)
    command = " ".join(argv)
    assert command.index(needle) + len(needle) > 200

    code, obj = call([needle], capsys, home)
    assert code == 3
    assert obj["processes"][0]["pid"] == child.pid

    code, out = call_text([needle], capsys, home)
    assert code == 3
    lines = out.splitlines()
    assert f"{child.pid} {command}" in lines


def test_text_mode_prints_declared_entry_line(home, capsys) -> None:
    """Defect: declared registrations are counted but never shown."""
    token = needle_token()
    write_claude(
        home, {"projects": {"/proj/a": {"mcpServers": {"srv": {"command": token}}}}}
    )
    code, out = call_text([token], capsys, home)
    assert code == 0
    assert "claude /proj/a srv" in out.splitlines()


def test_incident_shape_venv_process_and_user_registration(
    children, tmp_path, home, capsys
) -> None:
    """Defect: a venv interpreter whose argv0 holds the needle goes unseen."""
    venv = tmp_path / "venv"
    (venv / "bin").mkdir(parents=True)
    (venv / "bin" / "python").symlink_to(sys.executable)
    children([str(venv / "bin" / "python"), "-c", SLEEP])
    write_claude(
        home,
        {
            "projects": {
                "/proj/x": {"mcpServers": {"s": {"command": f"{venv}/bin/python"}}}
            }
        },
    )

    code, obj = call([str(venv)], capsys, home)
    assert code == 3
    assert obj["summary"] == {"live": 1, "declared": 1, "holders": 0}

    code, out = call_text([str(venv)], capsys, home)
    assert code == 3
    assert out.splitlines()[-2] == "READERS needles=1 live=1 declared=1 holders=0"


def test_self_and_every_ancestor_are_excluded(tmp_path, capsys) -> None:
    """Defect: the script reports itself or a launcher ancestor as a reader."""
    token = needle_token()
    spawn = "import subprocess,sys; sys.exit(subprocess.run(sys.argv[1:]).returncode)"
    exe = sys.executable
    argv = [
        exe, "-c", spawn, exe, "-c", spawn, exe,
        str(SCRIPTS / "readers.py"), token, "--json", "--home", str(tmp_path),
    ]  # fmt: skip
    result = subprocess.run(argv, capture_output=True, text=True, timeout=60)
    assert result.returncode == 0, result.stderr
    assert json.loads(result.stdout)["summary"]["live"] == 0


def test_claude_json_sources_scopes_args_and_env(home, capsys) -> None:
    """Defect: wrong scope, command-only or args-only match, env value leaked."""
    n = needle_token()
    write_claude(
        home,
        {
            "mcpServers": {"topsrv": {"command": f"/x/{n}/top"}},
            "projects": {
                "/proj/a": {
                    "mcpServers": {
                        "vault": {"command": f"/x/{n}/bin"},
                        "vault-args": {"command": "/bin/echo", "args": ["--db", n]},
                        "envonly": {
                            "command": "/bin/true",
                            "env": {"API_KEY": f"{SECRET}-{n}"},
                        },
                    }
                }
            },
        },
    )

    code, obj = call([n], capsys, home)
    assert code == 0
    assert declared_of(obj) == [
        {"source": "claude", "scope": "/proj/a", "name": "vault"},
        {"source": "claude", "scope": "/proj/a", "name": "vault-args"},
        {"source": "claude", "scope": "user", "name": "topsrv"},
    ]
    assert obj["summary"]["declared"] == 3
    assert not any(d["name"] == "envonly" for d in obj["declared"])


def secret_absent(capsys, argv, home) -> None:
    readers.main(list(argv) + ["--home", str(home)])
    readers.main(list(argv) + ["--home", str(home), "--json"])
    captured = capsys.readouterr()
    assert SECRET not in captured.out
    assert SECRET not in captured.err


def test_claude_env_value_never_printed(home, capsys) -> None:
    """Defect: an env value (a secret) is matched or printed."""
    n = needle_token()
    write_claude(
        home,
        {
            "mcpServers": {
                "envonly": {"command": "/bin/true", "env": {"K": f"{SECRET}-{n}"}}
            }
        },
    )
    code, obj = call([n], capsys, home)
    assert code == 0 and obj["declared"] == []
    secret_absent(capsys, [n], home)


def test_codex_registrations_and_env(home, capsys) -> None:
    """Defect: codex tables missed, args ignored, or env value matched/printed."""
    n = needle_token()
    config = home / ".codex" / "config.toml"
    config.parent.mkdir()
    config.write_text(
        f'[mcp_servers.cx]\ncommand = "/x/{n}/srv"\n\n'
        f'[mcp_servers.cx-args]\ncommand = "/bin/echo"\nargs = ["--p", "{n}"]\n\n'
        f'[mcp_servers.cx-env]\ncommand = "/bin/true"\n'
        f'[mcp_servers.cx-env.env]\nKEY = "{SECRET}-{n}"\n'
    )
    code, obj = call([n], capsys, home)
    assert code == 0
    assert declared_of(obj) == [
        {"source": "codex", "scope": "user", "name": "cx"},
        {"source": "codex", "scope": "user", "name": "cx-args"},
    ]
    secret_absent(capsys, [n], home)


def test_launchd_program_arguments_and_working_directory(home, capsys) -> None:
    """Defect: launchd matched on ProgramArguments only, or wrong scope/name."""
    n = needle_token()
    agents = home / "Library" / "LaunchAgents"
    agents.mkdir(parents=True)
    (agents / "a.plist").write_bytes(
        plistlib.dumps({"Label": "com.x.job", "ProgramArguments": ["/bin/true", f"/x/{n}"]})
    )
    (agents / "b.plist").write_bytes(
        plistlib.dumps(
            {
                "Label": "com.x.wd",
                "ProgramArguments": ["/bin/true"],
                "WorkingDirectory": f"/w/{n}",
            }
        )
    )
    code, obj = call([n], capsys, home)
    assert code == 0
    assert declared_of(obj) == [
        {"source": "launchd", "scope": "Library/LaunchAgents/a.plist", "name": "com.x.job"},
        {"source": "launchd", "scope": "Library/LaunchAgents/b.plist", "name": "com.x.wd"},
    ]


def test_mcp_json_per_repo_with_env_guard(tmp_path, home, capsys) -> None:
    """Defect: .mcp.json ignored, scope not the --repo argument, env matched."""
    n = needle_token()
    repo = tmp_path / "repo"
    repo.mkdir()
    (repo / ".mcp.json").write_text(
        json.dumps(
            {
                "mcpServers": {
                    "ms": {"command": f"/x/{n}"},
                    "ms-env": {"command": "/bin/true", "env": {"K": f"{SECRET}-{n}"}},
                }
            }
        )
    )
    code, obj = call([n, "--repo", str(repo)], capsys, home)
    assert code == 0
    assert declared_of(obj) == [{"source": "mcp-json", "scope": str(repo), "name": "ms"}]
    secret_absent(capsys, [n, "--repo", str(repo)], home)


def test_cron_line_matched_but_never_printed(tmp_path, home, monkeypatch, capsys) -> None:
    """Defect: the crontab line (which may hold secrets) is echoed."""
    n = needle_token()
    bin_dir = tmp_path / "bin"
    bin_dir.mkdir()
    fake = bin_dir / "crontab"
    fake.write_text(f"#!/bin/sh\necho '0 * * * * /usr/bin/job-{n} secretword'\n")
    fake.chmod(0o755)
    monkeypatch.setenv("PATH", f"{bin_dir}{os.pathsep}{os.environ['PATH']}")

    code, obj = call([n], capsys, home)
    assert code == 0
    assert declared_of(obj) == [{"source": "cron", "scope": "crontab", "name": "1"}]
    readers.main([n, "--home", str(home)])
    readers.main([n, "--home", str(home), "--json"])
    captured = capsys.readouterr()
    assert "secretword" not in captured.out + captured.err


def test_no_needle_is_a_usage_error_with_empty_stdout(capsys) -> None:
    """Defect: a missing needle scans everything or writes to stdout."""
    with pytest.raises(SystemExit) as error:
        readers.main([])
    assert error.value.code == 2
    assert capsys.readouterr().out == ""


def test_matching_is_case_sensitive(children, home, capsys) -> None:
    """Defect: matching folds case and reports unrelated processes."""
    token = "Cs" + uuid.uuid4().hex[:10]
    children([sys.executable, "-c", SLEEP, token])
    code, _ = call([token.lower()], capsys, home)
    assert code == 0
    code, _ = call([token], capsys, home)
    assert code == 3


def test_declared_list_is_sorted_by_source_scope_name(home, capsys) -> None:
    """Defect: declared entries come out in file order."""
    n = needle_token()
    write_claude(
        home,
        {
            "mcpServers": {"z": {"command": n}},
            "projects": {"/p": {"mcpServers": {"a": {"command": n}}}},
        },
    )
    config = home / ".codex" / "config.toml"
    config.parent.mkdir()
    config.write_text(f'[mcp_servers.b]\ncommand = "{n}"\n')
    _, obj = call([n], capsys, home)
    assert declared_of(obj) == [
        {"source": "claude", "scope": "/p", "name": "a"},
        {"source": "claude", "scope": "user", "name": "z"},
        {"source": "codex", "scope": "user", "name": "b"},
    ]


def test_nothing_matching_ends_with_the_two_closing_lines(home, capsys) -> None:
    """Defect: the closing lines drift or vanish when there is nothing to report."""
    code, out = call_text([needle_token()], capsys, home)
    assert code == 0
    assert out.splitlines()[-2:] == [
        "READERS needles=1 live=0 declared=0 holders=0",
        BLIND,
    ]


def test_two_needles_are_or_ed(children, home, capsys) -> None:
    """Defect: only the first needle is used."""
    first, second = needle_token(), needle_token()
    write_claude(home, {"mcpServers": {"s": {"command": first}}})
    children([sys.executable, "-c", SLEEP, second])
    code, out = call_text([first, second], capsys, home)
    assert code == 3
    assert out.splitlines()[-2] == "READERS needles=2 live=1 declared=1 holders=0"


def make_marker(root: Path, pid, version="1") -> Path:
    """Marker layout: ``<plugin cache dir>/<version>/.in_use/<pid>``."""
    directory = root / version / ".in_use"
    directory.mkdir(parents=True, exist_ok=True)
    marker = directory / str(pid)
    marker.write_text("")
    return marker


def test_ignore_pid_clears_exit_and_suppresses_holder(
    children, tmp_path, home, capsys
) -> None:
    """Defect: --ignore-pid is parsed but ignored."""
    child, _, needle = long_child(children, tmp_path)
    cache = tmp_path / "cache"
    make_marker(cache, child.pid)
    code, _ = call([needle], capsys, home)
    assert code == 3
    code, obj = call([needle, "--holders", str(cache), "--ignore-pid", str(child.pid)], capsys, home)
    assert code == 0
    assert obj["holders"] == [] and obj["processes"] == []


def test_repeatable_flags_take_one_value_each(tmp_path, home, capsys) -> None:
    """Defect: nargs='+' swallows the positional needle after two --repo values."""
    n = needle_token()
    for name in ("a", "b"):
        repo = tmp_path / name
        repo.mkdir()
        (repo / ".mcp.json").write_text(
            json.dumps({"mcpServers": {name: {"command": n}}})
        )
    code, obj = call(["--repo", str(tmp_path / "a"), "--repo", str(tmp_path / "b"), n], capsys, home)
    assert code == 0
    assert obj["needles"] == [n]
    assert [d["name"] for d in obj["declared"]] == ["a", "b"]
    with pytest.raises(SystemExit) as error:
        readers.main(["--bogus"])
    assert error.value.code == 2


def test_holders_liveness_names_pid_one_own_pid_and_ancestor(
    children, tmp_path, home, capsys
) -> None:
    """Defect: markers counted without signal 0, bad names counted, ancestors exempted."""
    dead = subprocess.Popen([sys.executable, "-c", "pass"])
    dead.wait()
    cache = tmp_path / "cache"
    for name in (dead.pid, "0", "-1", "abc"):
        make_marker(cache, name)
    code, obj = call([needle_token(), "--holders", str(cache)], capsys, home)
    assert code == 0 and obj["summary"]["holders"] == 0

    pid1 = tmp_path / "c1"
    make_marker(pid1, 1)
    code, obj = call([needle_token(), "--holders", str(pid1)], capsys, home)
    assert code == 3 and obj["summary"]["holders"] == 1

    own = tmp_path / "own"
    marker = make_marker(own, os.getpid())
    code, obj = call([needle_token(), "--holders", str(own)], capsys, home)
    assert code == 3
    assert obj["summary"] == {"live": 0, "declared": 0, "holders": 1}
    assert obj["holders"][0]["path"] == str(marker)
    assert obj["holders"][0]["pid"] == os.getpid()
    code, obj = call([needle_token(), "--holders", str(own), "--ignore-pid", str(os.getpid())], capsys, home)
    assert code == 0

    parent = tmp_path / "parent"
    make_marker(parent, os.getppid())
    code, obj = call([needle_token(), "--holders", str(parent)], capsys, home)
    assert code == 3 and obj["summary"]["holders"] == 1


def test_holder_marker_for_live_child_counts(children, tmp_path, home, capsys) -> None:
    """Defect: a live child's marker is not counted as a holder."""
    child, _, needle = long_child(children, tmp_path)
    cache = tmp_path / "cache"
    make_marker(cache, child.pid)
    code, obj = call([needle, "--holders", str(cache)], capsys, home)
    assert code == 3 and obj["summary"]["holders"] == 1


def git(cwd: Path, *args: str) -> None:
    env = {
        **os.environ,
        "GIT_AUTHOR_NAME": "t", "GIT_AUTHOR_EMAIL": "t@t",
        "GIT_COMMITTER_NAME": "t", "GIT_COMMITTER_EMAIL": "t@t",
    }  # fmt: skip
    subprocess.run(["git", "-C", str(cwd), *args], check=True, capture_output=True, env=env)


def test_worktrees_listed_for_path_needle_only(tmp_path, home, capsys) -> None:
    """Defect: other checkouts are missed, or a non-path needle lists some."""
    repo = tmp_path / "repo"
    repo.mkdir()
    git(repo, "init", "-q")
    git(repo, "commit", "-q", "--allow-empty", "-m", "x")
    other = tmp_path / "other"
    git(repo, "worktree", "add", "-q", str(other), "-b", "side")

    code, obj = call([str(repo)], capsys, home)
    assert code == 0
    assert sorted(Path(p).resolve() for p in obj["worktrees"]) == sorted(
        [repo.resolve(), other.resolve()]
    )
    code, obj = call([needle_token()], capsys, home)
    assert obj["worktrees"] == []


def test_json_is_exactly_one_object_with_the_named_keys(home, capsys) -> None:
    """Defect: the closing lines leak into --json or keys drift."""
    readers.main([needle_token(), "--home", str(home), "--json"])
    out = capsys.readouterr().out
    obj = json.loads(out)
    assert set(obj) == {"needles", "processes", "declared", "holders", "worktrees", "summary"}
    assert set(obj["summary"]) == {"live", "declared", "holders"}
    assert "READERS" not in out and "Blind spots" not in out


def tree_state(root: Path) -> dict[str, tuple[int, int]]:
    return {
        str(p.relative_to(root)): (p.stat().st_size, p.stat().st_mtime_ns)
        for p in sorted(root.rglob("*"))
        if p.is_file() and "__pycache__" not in p.parts
    }


def test_script_is_read_only(children, tmp_path, home, monkeypatch, capsys) -> None:
    """Defect: the script writes caches or state next to what it inspects."""
    child, _, needle = long_child(children, tmp_path)
    write_claude(home, {"mcpServers": {"s": {"command": needle}}})
    cache = tmp_path / "cache"
    make_marker(cache, child.pid)
    repo = tmp_path / "repo"
    repo.mkdir()
    git(repo, "init", "-q")
    (repo / ".mcp.json").write_text(json.dumps({"mcpServers": {"m": {"command": needle}}}))
    cwd = tmp_path / "cwd"
    cwd.mkdir()
    env_dirs = {}
    for name in ("HOME", "TMPDIR", "XDG_CACHE_HOME"):
        env_dirs[name] = tmp_path / f"empty-{name}"
        env_dirs[name].mkdir()
        monkeypatch.setenv(name, str(env_dirs[name]))
    monkeypatch.chdir(cwd)
    roots = [home, cache, repo, cwd, SCRIPTS]
    before = [tree_state(r) for r in roots]

    code, _ = call([needle, str(repo), "--repo", str(repo), "--holders", str(cache)], capsys, home)

    assert code == 3
    assert [tree_state(r) for r in roots] == before
    assert child.poll() is None
    for directory in env_dirs.values():
        assert list(directory.rglob("*")) == []


@pytest.mark.skipif(shutil.which("lsof") is None, reason="lsof missing")
def test_open_handle_probe_misses_what_the_command_line_finds(
    children, tmp_path, home, capsys
) -> None:
    """Defect: trusting lsof +D for a store opened per query."""
    watched = tmp_path / "watched"
    watched.mkdir()
    token = needle_token()
    children([sys.executable, "-c", SLEEP, str(watched / token)], cwd=str(tmp_path))
    probe = subprocess.run(["lsof", "+D", str(watched)], capture_output=True, text=True)
    assert probe.stdout == ""
    code, obj = call([token], capsys, home)
    assert code == 3 and obj["summary"]["live"] == 1


DESCRIPTION = (
    "Check who else uses a git tree, index, venv or cache before you reset, "
    "rebuild, delete, prune or call it dormant: live processes, MCP and launchd "
    "registrations, other sessions. Use before `reset --hard`, `clean`, "
    "`reindex --force` or rm."
)
LOOKUP = (
    'p=$$; while [ "$p" -gt 1 ]; do c=$(ps -o comm= -p "$p"); case "$c" in '
    'claude|*/claude) echo "$p"; break;; esac; p=$(ps -o ppid= -p "$p" | tr -d '
    "' '); done"
)


def skill_parts():
    text = SKILL.read_text()
    return text, text.split("---", 2)[1]


def test_skill_description_is_the_237_character_text() -> None:
    """Defect: the description drifts from the owner-accepted wording."""
    text, frontmatter = skill_parts()
    assert len(DESCRIPTION) == 237
    match = re.search(r"^description:\s*>?\s*(.*?)(?=^\w+:|\Z)", frontmatter, re.S | re.M)
    assert " ".join(match.group(1).split()) == DESCRIPTION
    assert "name: shared-tree-safety" in frontmatter


def test_skill_section_carries_the_required_content() -> None:
    """Defect: the section loses a rule the incident taught, or sits in the wrong place."""
    text, _ = skill_parts()
    heading = "## Before changing something others may read"
    assert text.count(heading) == 1
    headings = re.findall(r"^## .*$", text, flags=re.M)
    assert headings[headings.index("## Before assuming the tree is yours") + 1] == heading
    body = text.split(heading, 1)[1]
    body = re.split(r"^## ", body, flags=re.M)[0]
    for literal in (
        "Live check: <command> -> <READERS line>, exit <code>",
        "Not checked:",
        "READERS",
        "exit 3",
        "do not call it dormant",
        "repo grep",
        "open-handle probe",
        "green status line",
        "--repo",
        "--holders",
        "--ignore-pid",
        LOOKUP,
        'uv run --no-project --python ">=3.11" python "<skill base directory>/scripts/readers.py"',
        "Read the listed holders",
    ):
        assert literal in body, literal
    for word in (
        "rebuild", "delete", "prune", "retire", "unload", "dormant",
        "unreferenced", "safe to remove",
    ):  # fmt: skip
        assert word in body, word
    step3 = next(line for line in text.splitlines() if line.startswith("3. Check for a live worker"))
    assert "lsof +D <dir>" in step3
    assert "(an open-handle probe misses stores opened per query; see the section below)" in step3
