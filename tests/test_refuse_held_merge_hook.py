"""Tests for the refuse-held-merge PreToolUse hook (the-workshop#1018).

The hook runs as a real subprocess. The scanner it calls is a counting stub
that CLAUDE_PLUGIN_ROOT points at, so each test sees the exact argv the hook
passed. Fake ``gh`` and ``glab`` on PATH record any invocation: the hook must
make none, because the scanner owns every GitHub/GitLab read.
"""

from __future__ import annotations

import importlib.util
import json
import os
import stat
import subprocess
import sys
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parents[1]
HOOK_PATH = REPO_ROOT / "plugins" / "workbench" / "hooks" / "scripts" / "refuse-held-merge.py"

ACK_INSTRUCTION = (
    "Ask the human whether to merge anyway. If they say yes, post a PR comment whose first "
    "line is `hold-scan: acknowledged` followed by their reason, then retry."
)

STUB = """\
import json, os, sys, time
with open(os.environ["STUB_LOG"], "a") as fh:
    fh.write(json.dumps(sys.argv[1:]) + "\\n")
time.sleep(float(os.environ.get("STUB_SLEEP", "0")))
sys.stdout.write(os.environ["STUB_RESPONSE"])
"""

CLEAN = {"verdict": "NO-HOLD-FOUND", "hits": [], "acknowledgement": None, "scanned": []}


def hit(source, ts=None, quote="a quote", url="https://x/1"):
    return {"source": source, "url_or_path": url, "quote": quote, "timestamp": ts}


def ack(ts):
    return {"url_or_path": "https://x/ack", "timestamp": ts}


def found(*hits, acknowledgement=None):
    return {"verdict": "HOLD-FOUND", "hits": list(hits), "acknowledgement": acknowledgement, "scanned": []}


@pytest.fixture
def rig(tmp_path):
    root = tmp_path / "plugin"
    script = root / "skills" / "hold-scan" / "scripts" / "hold_scan.py"
    script.parent.mkdir(parents=True)
    script.write_text(STUB)
    bin_dir = tmp_path / "bin"
    bin_dir.mkdir()
    cli_log = tmp_path / "cli.log"
    for tool in ("gh", "glab"):
        p = bin_dir / tool
        p.write_text(f'#!/bin/sh\necho "{tool} $@" >> "{cli_log}"\nexit 1\n')
        p.chmod(p.stat().st_mode | stat.S_IEXEC)
    log = tmp_path / "stub.log"

    class Rig:
        def run(self, command, response=CLEAN, cwd=None, tool="Bash", sleep=0, payload=None, plugin_root=True):
            env = dict(os.environ)
            env["PATH"] = f"{bin_dir}{os.pathsep}{env['PATH']}"
            env["STUB_LOG"] = str(log)
            env["STUB_RESPONSE"] = response if isinstance(response, str) else json.dumps(response)
            env["STUB_SLEEP"] = str(sleep)
            if plugin_root:
                env["CLAUDE_PLUGIN_ROOT"] = str(root)
            else:
                env.pop("CLAUDE_PLUGIN_ROOT", None)
            data = payload or {"tool_name": tool, "tool_input": {"command": command}, "cwd": str(cwd or tmp_path)}
            return subprocess.run(
                [sys.executable, str(HOOK_PATH)], input=json.dumps(data), capture_output=True, text=True,
                env=env, timeout=60,
            )

        @property
        def scans(self):
            return [json.loads(line) for line in log.read_text().splitlines()] if log.exists() else []

        @property
        def cli_calls(self):
            return cli_log.read_text().splitlines() if cli_log.exists() else []

    rig = Rig()
    rig.root = root
    rig.log = log
    return rig


def git_repo(tmp_path, origin):
    repo = tmp_path / "repo"
    repo.mkdir()
    subprocess.run(["git", "-C", str(repo), "init", "-q"], check=True)
    if origin:
        subprocess.run(["git", "-C", str(repo), "remote", "add", "origin", origin], check=True)
    return repo


# ---- must-flip --------------------------------------------------------------


def test_must_flip(rig):
    resp = found(hit("thread", "2026-08-17T00:54:25Z", "Holding this unmerged", "https://x/c"),
                 hit("label", None, "afk:hold label on closing issue #7", "https://x/i7"))
    r = rig.run("gh pr merge 112 -R cdcoonce/breakroom --rebase", resp)
    assert r.returncode == 2
    for needle in ("Holding this unmerged", "afk:hold label on closing issue #7", "thread", "label", ACK_INSTRUCTION):
        assert needle in r.stderr
    assert rig.scans == [["--repo", "cdcoonce/breakroom", "--pr", "112", "--json"]]


# ---- shape rules ------------------------------------------------------------


@pytest.mark.parametrize("cmd", ["gh pr merge $P -R cdcoonce/breakroom", "gh pr merge -R cdcoonce/breakroom",
                                 "gh pr merge feature-branch -R cdcoonce/breakroom",
                                 "gh pr merge $(git rev-parse x) -R cdcoonce/breakroom"])
def test_missing_literal_number(rig, cmd):
    r = rig.run(cmd)
    assert r.returncode == 2 and "literal" in r.stderr and "number" in r.stderr
    assert rig.scans == []


@pytest.mark.parametrize("cmd", ["for p in 1 2; do gh pr merge $p; done", "gh pr merge 1 && gh pr merge 2",
                                 "for p in 1; do gh pr merge 1 -R a/b; done", "echo 1 2 | xargs gh pr merge",
                                 "gh pr merge 1 -R a/b; glab mr merge 2 -R g/p",
                                 "while true\ndo\n  gh pr merge 1 -R a/b\ndone"])
def test_one_merge_per_call(rig, cmd):
    r = rig.run(cmd)
    assert r.returncode == 2 and "one merge per call" in r.stderr
    assert rig.scans == []


def test_shape_rule_a_precedes_b(rig):
    r = rig.run("gh pr merge $A && gh pr merge $B")
    assert r.returncode == 2 and "one merge per call" in r.stderr


@pytest.mark.parametrize("cmd", [
    "gh pr view 112 --comments", "git merge main",
    'gh issue comment 5 --body "run gh pr merge $P later"',
    "gh pr merge 112 -R cdcoonce/breakroom --disable-auto",
    'echo "gh pr merge 5"',
])
def test_unrelated_commands_pass_without_a_scan(rig, cmd):
    r = rig.run(cmd, found(hit("thread")))
    assert r.returncode == 0 and r.stderr == ""
    assert rig.scans == [] and rig.cli_calls == []


def test_non_bash_tool_is_unrelated(rig):
    r = rig.run("gh pr merge 1 -R a/b", found(hit("thread")), tool="Edit")
    assert r.returncode == 0 and rig.scans == []


@pytest.mark.parametrize("tool", ["Bash", "bash", "shell"])
def test_bash_tool_ids(rig, tool):
    assert rig.run("gh pr merge 1 -R a/b", tool=tool).returncode == 0
    assert len(rig.scans) == 1


@pytest.mark.parametrize("prefix", ["", "cd /tmp && ", "true; ", "false || ", "echo x | ", "(", "$(", "if x; then ", "FOO=1 "])
def test_merge_found_where_a_command_starts(rig, prefix):
    rig.run(f"{prefix}gh pr merge 5 -R a/b")
    assert rig.scans == [["--repo", "a/b", "--pr", "5", "--json"]]


def test_unparseable_with_merge_phrase_exits_2(rig):
    r = rig.run("gh pr merge 5 -R a/b --body 'unterminated")
    assert r.returncode == 2 and "own call" in r.stderr and rig.scans == []


def test_unparseable_without_merge_phrase_exits_0(rig):
    assert rig.run("echo 'unterminated").returncode == 0


# ---- repo resolution --------------------------------------------------------


@pytest.mark.parametrize("cmd", [
    "gh pr merge 112 --repo cdcoonce/breakroom",
    "gh pr merge 112 --repo=cdcoonce/breakroom",
    "gh pr merge 112 -R cdcoonce/breakroom",
    "gh pr merge https://github.com/cdcoonce/breakroom/pull/112",
])
def test_repo_forms(rig, cmd):
    rig.run(cmd)
    assert rig.scans == [["--repo", "cdcoonce/breakroom", "--pr", "112", "--json"]]


def test_origin_of_cwd(rig, tmp_path):
    repo = git_repo(tmp_path, "git@github.com:cdcoonce/breakroom.git")
    rig.run("gh pr merge 112", cwd=repo)
    assert rig.scans == [["--repo", "cdcoonce/breakroom", "--pr", "112", "--json"]]


def test_https_origin(rig, tmp_path):
    repo = git_repo(tmp_path, "https://github.com/cdcoonce/breakroom")
    rig.run("gh pr merge 112", cwd=repo)
    assert rig.scans[0][:2] == ["--repo", "cdcoonce/breakroom"]


def test_literal_cd_moves_the_repo(rig, tmp_path):
    repo = git_repo(tmp_path, "git@github.com:cdcoonce/breakroom.git")
    elsewhere = tmp_path / "elsewhere"
    elsewhere.mkdir()
    rig.run(f"cd {repo} && gh pr merge 112", cwd=elsewhere)
    assert rig.scans == [["--repo", "cdcoonce/breakroom", "--pr", "112", "--json"]]


def test_relative_cd(rig, tmp_path):
    git_repo(tmp_path, "git@github.com:cdcoonce/breakroom.git")
    rig.run("cd repo && gh pr merge 112", cwd=tmp_path)
    assert rig.scans[0][:2] == ["--repo", "cdcoonce/breakroom"]


def test_non_literal_cd_refuses_naming_dash_r(rig, tmp_path):
    repo = git_repo(tmp_path, "git@github.com:cdcoonce/breakroom.git")
    r = rig.run("cd $D && gh pr merge 112", cwd=repo)
    assert r.returncode == 2 and "-R" in r.stderr and rig.scans == []


def test_no_origin_refuses_naming_dash_r(rig, tmp_path):
    r = rig.run("gh pr merge 112", cwd=git_repo(tmp_path, None))
    assert r.returncode == 2 and "-R" in r.stderr and rig.scans == []


def test_gitlab(rig):
    rig.run("glab mr merge 42 -R group/project")
    assert rig.scans == [["--gitlab", "group/project", "--mr", "42", "--json"]]


def test_gitlab_origin_with_subgroups(rig, tmp_path):
    repo = git_repo(tmp_path, "git@gitlab.com:grp/sub/proj.git")
    rig.run("glab mr merge 42", cwd=repo)
    assert rig.scans == [["--gitlab", "grp/sub/proj", "--mr", "42", "--json"]]


def test_gitlab_url(rig):
    rig.run("glab mr merge https://gitlab.com/grp/sub/proj/-/merge_requests/42")
    assert rig.scans == [["--gitlab", "grp/sub/proj", "--mr", "42", "--json"]]


def test_value_flags_do_not_eat_the_number(rig):
    rig.run('gh pr merge 112 -R a/b --body "x" --subject y --match-head-commit abc')
    assert rig.scans == [["--repo", "a/b", "--pr", "112", "--json"]]
    rig.run('gh pr merge -R a/b --body "x" 7')
    assert rig.scans[-1] == ["--repo", "a/b", "--pr", "7", "--json"]


# ---- scanner results --------------------------------------------------------


def test_no_hold_exits_0(rig):
    assert rig.run("gh pr merge 1 -R a/b").returncode == 0


def test_scan_error_names_the_failed_call(rig):
    resp = {"verdict": "SCAN-ERROR", "hits": [], "acknowledgement": None,
            "scanned": [{"name": "gh pr view 1 --repo a/b", "status": "failed", "detail": "exit 1"},
                        {"name": "vault", "status": "skipped", "detail": "none"}]}
    r = rig.run("gh pr merge 1 -R a/b", resp)
    assert r.returncode == 2 and "gh pr view 1 --repo a/b" in r.stderr


def test_unparseable_scanner_output_fails_closed(rig):
    r = rig.run("gh pr merge 1 -R a/b", "not json")
    assert r.returncode == 2 and "hold_scan" in r.stderr


def test_unknown_verdict_fails_closed(rig):
    assert rig.run("gh pr merge 1 -R a/b", {"verdict": "WAT", "hits": []}).returncode == 2


def test_missing_scanner_fails_closed(rig, tmp_path):
    (tmp_path / "plugin" / "skills" / "hold-scan" / "scripts" / "hold_scan.py").unlink()
    r = rig.run("gh pr merge 1 -R a/b")
    assert r.returncode == 2


def test_timeout_fails_closed(rig, monkeypatch):
    spec = importlib.util.spec_from_file_location("refuse_held_merge", HOOK_PATH)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    assert mod.SCAN_TIMEOUT == 45
    monkeypatch.setattr(mod, "SCAN_TIMEOUT", 1)
    monkeypatch.setenv("STUB_SLEEP", "5")
    monkeypatch.setenv("STUB_LOG", str(rig.log))
    monkeypatch.setenv("STUB_RESPONSE", "{}")
    payload = {"tool_name": "Bash", "tool_input": {"command": "gh pr merge 1 -R a/b"}, "cwd": "."}
    code, message = mod.evaluate(payload, plugin_root=rig.root)
    assert code == 2 and "timed out" in message and "1s" in message


# ---- acknowledgement --------------------------------------------------------

T = "2026-09-01T10:00:00Z"
AFTER = "2026-09-01T10:01:00Z"
BEFORE = "2026-09-01T09:59:00Z"


def test_ack_after_thread_hit_clears(rig):
    assert rig.run("gh pr merge 1 -R a/b", found(hit("thread", T), acknowledgement=ack(AFTER))).returncode == 0


@pytest.mark.parametrize("ts", [BEFORE, T])
def test_ack_not_strictly_after_does_not_clear(rig, ts):
    r = rig.run("gh pr merge 1 -R a/b", found(hit("thread", T), acknowledgement=ack(ts)))
    assert r.returncode == 2 and ACK_INSTRUCTION in r.stderr


def test_label_is_never_cleared(rig):
    r = rig.run("gh pr merge 1 -R a/b", found(hit("label"), acknowledgement=ack(AFTER)))
    assert r.returncode == 2 and "afk:hold" in r.stderr and "label" in r.stderr


def test_vault_cleared_by_any_ack_only(rig):
    h = hit("vault", None)
    assert rig.run("gh pr merge 1 -R a/b", found(h, acknowledgement=ack(BEFORE))).returncode == 0
    assert rig.run("gh pr merge 1 -R a/b", found(h)).returncode == 2


def test_unknown_source_never_cleared(rig):
    r = rig.run("gh pr merge 1 -R a/b", found(hit("mystery", T), acknowledgement=ack(AFTER)))
    assert r.returncode == 2


def test_partial_clear_prints_only_remaining(rig):
    resp = found(hit("thread", BEFORE, "old hold"), hit("thread", AFTER, "newer hold"), acknowledgement=ack(T))
    r = rig.run("gh pr merge 1 -R a/b", resp)
    assert r.returncode == 2 and "newer hold" in r.stderr and "old hold" not in r.stderr


def test_thread_hit_with_null_timestamp_is_not_cleared(rig):
    r = rig.run("gh pr merge 1 -R a/b", found(hit("thread", None), acknowledgement=ack(AFTER)))
    assert r.returncode == 2


def test_hook_makes_no_gh_or_glab_call(rig):
    for resp in (found(hit("thread", T), acknowledgement=ack(AFTER)), found(hit("label")), CLEAN):
        rig.run("gh pr merge 1 -R a/b", resp)
        rig.run("glab mr merge 2 -R g/p", resp)
    assert rig.cli_calls == []


# ---- fail-open --------------------------------------------------------------


@pytest.mark.parametrize("stdin", ["", "  \n", "not json", "[]", "null", '"x"'])
def test_malformed_input_exits_0(rig, stdin):
    r = subprocess.run([sys.executable, str(HOOK_PATH)], input=stdin, capture_output=True, text=True, timeout=30)
    assert r.returncode == 0 and r.stderr == ""


@pytest.mark.parametrize("command", [None, 5, ["gh"]])
def test_non_string_command_exits_0(rig, command):
    assert rig.run(command).returncode == 0


def test_plugin_root_derived_from_own_path(rig, tmp_path):
    """Without CLAUDE_PLUGIN_ROOT the hook finds skills/hold-scan next to hooks/ in its own plugin."""
    r = rig.run("gh pr merge 1", plugin_root=False, cwd=git_repo(tmp_path, None))
    assert r.returncode == 2 and "-R" in r.stderr  # reached the repo step: no crash on root lookup
    spec = importlib.util.spec_from_file_location("rhm", HOOK_PATH)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    assert mod.default_plugin_root() == REPO_ROOT / "plugins" / "workbench"
    assert (mod.default_plugin_root() / "skills" / "hold-scan" / "scripts" / "hold_scan.py").is_file()
