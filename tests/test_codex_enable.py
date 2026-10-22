"""Contract for the `codex-enable` skill (#486).

The skill vendors a Codex-functional `.codex/hooks.json` into a target repo by
wrapping `render_codex_hooks`. The pins here grade the behaviors a teammate
relies on: the file is byte-identical to what wiring_gen renders, a rerun is a
no-op, a hand-authored file is never overwritten without `--force`, a refusal
leaves the target untouched (never a half-install), and the two Codex trust
steps are printed because hooks stay silently dead without them.
"""

import importlib.util
import json
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parents[1]
WORKBENCH = REPO_ROOT / "plugins" / "workbench"
SKILL_DIR = WORKBENCH / "skills" / "codex-enable"
SCRIPT = SKILL_DIR / "scripts" / "codex_enable.py"
WIRING_GEN = WORKBENCH / "machinery" / "tools" / "wiring_gen.py"


def _load(name: str, path: Path):
    spec = importlib.util.spec_from_file_location(name, path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


@pytest.fixture(scope="module")
def ce():
    return _load("codex_enable_under_test", SCRIPT)


@pytest.fixture(scope="module")
def wg():
    return _load("wiring_gen_under_test", WIRING_GEN)


def _expected_hooks(ce, wg) -> str:
    entries = json.loads(ce.SPEC_PATH.read_text(encoding="utf-8"))["entries"]
    return wg._dump_json(wg.render_codex_hooks(entries))


def _tree(root: Path) -> dict:
    return {
        str(p.relative_to(root)): p.read_bytes()
        for p in sorted(root.rglob("*"))
        if p.is_file()
    }


def test_hooks_json_is_byte_identical_to_wiring_gen_render(ce, wg, tmp_path, capsys):
    assert ce.main([str(tmp_path)]) == 0
    written = (tmp_path / ".codex" / "hooks.json").read_text(encoding="utf-8")
    assert written == _expected_hooks(ce, wg)


def test_only_the_codex_functional_hook_is_wired(ce, tmp_path):
    ce.main([str(tmp_path)])
    body = json.loads((tmp_path / ".codex" / "hooks.json").read_text(encoding="utf-8"))
    commands = [
        h["command"]
        for groups in body["hooks"].values()
        for g in groups
        for h in g["hooks"]
    ]
    assert len(commands) == 1
    assert "verify-tests-before-stop.py" in commands[0]
    assert set(body["hooks"]) == {"Stop"}


def test_runtime_is_vendored_byte_identical_and_command_resolves(ce, tmp_path):
    ce.main([str(tmp_path)])
    scripts = tmp_path / ".claude" / "scripts"
    assert sorted(p.name for p in scripts.iterdir()) == [
        "_git_baseline.py",
        "run-hook.sh",
        "verify-tests-before-stop.py",
    ]
    for name in ("verify-tests-before-stop.py", "_git_baseline.py"):
        assert (scripts / name).read_bytes() == (
            WORKBENCH / "hooks" / "scripts" / name
        ).read_bytes()
    assert (scripts / "run-hook.sh").read_bytes() == (
        WORKBENCH / "machinery" / "engine" / "run-hook.sh"
    ).read_bytes()
    # the rendered command points at the vendored runner location
    assert ".claude/scripts/run-hook.sh" in (
        tmp_path / ".codex" / "hooks.json"
    ).read_text(encoding="utf-8")


def test_rerun_is_idempotent(ce, tmp_path, capsys):
    ce.main([str(tmp_path)])
    before = _tree(tmp_path)
    capsys.readouterr()
    assert ce.main([str(tmp_path)]) == 0
    out = capsys.readouterr().out
    assert _tree(tmp_path) == before
    assert "unchanged" in out and "written" not in out


def test_refuses_hand_authored_hooks_json_without_force(ce, tmp_path, capsys):
    target = tmp_path / ".codex" / "hooks.json"
    target.parent.mkdir()
    target.write_text('{"hooks": {}}\n', encoding="utf-8")
    before = _tree(tmp_path)
    assert ce.main([str(tmp_path)]) != 0
    assert _tree(tmp_path) == before  # never a half-install
    assert "--force" in capsys.readouterr().out


def test_refuses_conflicting_runtime_file_and_writes_nothing(ce, tmp_path):
    runner = tmp_path / ".claude" / "scripts" / "run-hook.sh"
    runner.parent.mkdir(parents=True)
    runner.write_text("#!/bin/sh\necho mine\n", encoding="utf-8")
    before = _tree(tmp_path)
    assert ce.main([str(tmp_path)]) != 0
    assert _tree(tmp_path) == before
    assert not (tmp_path / ".codex").exists()


def test_force_overwrites_hand_authored_file(ce, wg, tmp_path):
    target = tmp_path / ".codex" / "hooks.json"
    target.parent.mkdir()
    target.write_text('{"hooks": {}}\n', encoding="utf-8")
    assert ce.main([str(tmp_path), "--force"]) == 0
    assert target.read_text(encoding="utf-8") == _expected_hooks(ce, wg)


def test_trust_steps_printed_on_success_only(ce, tmp_path, capsys):
    ce.main([str(tmp_path)])
    out = capsys.readouterr().out
    assert 'trust_level = "trusted"' in out
    assert "~/.codex/config.toml" in out
    assert "per-hook" in out.lower()
    (tmp_path / ".codex" / "hooks.json").write_text("{}\n", encoding="utf-8")
    ce.main([str(tmp_path)])
    assert 'trust_level = "trusted"' not in capsys.readouterr().out


def test_missing_target_is_an_error(ce, tmp_path):
    assert ce.main([str(tmp_path / "nope")]) == 2


def test_every_spec_script_ships_as_a_workbench_hook(ce):
    entries = json.loads(ce.SPEC_PATH.read_text(encoding="utf-8"))["entries"]
    for entry in entries:
        assert (WORKBENCH / "hooks" / "scripts" / entry["script"]).is_file()


def test_skill_documents_the_classification():
    text = " ".join((SKILL_DIR / "SKILL.md").read_text(encoding="utf-8").split())
    assert text.startswith("---")
    for needle in (
        "#486",
        "COMPATIBILITY.md",
        "verify-tests-before-stop.py",
        "protect-files.py",
        "verify-subagent-evidence.py",
        "--force",
    ):
        assert needle in text
