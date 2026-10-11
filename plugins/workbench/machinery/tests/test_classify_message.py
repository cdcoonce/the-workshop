"""Tests for classify-message.py's default-category suppression (#724)."""

from __future__ import annotations

import json
import os
import subprocess
import sys
from pathlib import Path

ENGINE_DIR = Path(__file__).resolve().parent.parent / "engine"
SCRIPT = ENGINE_DIR / "classify-message.py"

_ROUTING = '''\
from content_routing_defaults import CATEGORIES

DEFAULT_CATEGORY = {
    "name": "note",
    "folder": "inbox",
    "template": "none",
    "routing_hint": "plain note",
}
'''


def _run(prompt: str, config_dir: Path | None) -> str:
    env = dict(os.environ)
    paths = [str(ENGINE_DIR)]
    if config_dir is not None:
        paths.insert(0, str(config_dir))
    env["PYTHONPATH"] = os.pathsep.join(paths)
    proc = subprocess.run(
        [sys.executable, str(SCRIPT)],
        input=json.dumps({"prompt": prompt}),
        capture_output=True,
        text=True,
        env=env,
        check=False,
    )
    assert proc.returncode == 0, proc.stderr
    return proc.stdout


def test_unmatched_message_emits_no_hint_with_shipped_default() -> None:
    assert _run("zzz qqq xyzzy", None) == ""


def test_unmatched_message_emits_no_hint_when_default_renamed(tmp_path: Path) -> None:
    (tmp_path / "content_routing.py").write_text(_ROUTING, encoding="utf-8")
    assert _run("zzz qqq xyzzy", tmp_path) == ""


def test_matched_message_still_emits_hint_when_default_renamed(tmp_path: Path) -> None:
    (tmp_path / "content_routing.py").write_text(_ROUTING, encoding="utf-8")
    out = _run("we had a production incident and an outage", tmp_path)
    assert "hookSpecificOutput" in json.loads(out)
