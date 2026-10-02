"""Shared helpers for the commit/C case tests (imported by name; see conftest.py).

The case directory is ``evals/commit/C/``; ``predicates.py`` is loaded by file
path (the way the harness loads it), never imported as a package, so the tests
exercise exactly the module the conductor scores with.
"""

from __future__ import annotations

import importlib.util
import json
import os
import subprocess
import sys
from pathlib import Path

CASE_DIR = Path(__file__).resolve().parents[1]
REPO_ROOT = CASE_DIR.parents[2]

# A fixed identity for the tests' own synthetic commits, so they never depend
# on (or fail for want of) the machine's git configuration.
GIT_TEST_ENV = {
    "GIT_AUTHOR_NAME": "Case Test",
    "GIT_AUTHOR_EMAIL": "case-test@example.invalid",
    "GIT_AUTHOR_DATE": "2026-01-02T03:04:05+00:00",
    "GIT_COMMITTER_NAME": "Case Test",
    "GIT_COMMITTER_EMAIL": "case-test@example.invalid",
    "GIT_COMMITTER_DATE": "2026-01-02T03:04:05+00:00",
    "GIT_CONFIG_GLOBAL": os.devnull,
    "GIT_CONFIG_NOSYSTEM": "1",
}


def git(repo: Path, *args: str) -> str:
    """Run ``git`` in *repo* with the test identity and return its stdout."""
    result = subprocess.run(
        ["git", "-C", str(repo), *args],
        capture_output=True,
        text=True,
        check=True,
        env={**os.environ, **GIT_TEST_ENV},
    )
    return result.stdout


def build(case_dir: Path, dest: Path) -> None:
    """Run *case_dir*'s builder into the not-yet-existing *dest*, as the harness does."""
    subprocess.run(
        [sys.executable, str(case_dir / "build_fixture.py"), str(dest)],
        check=True,
        cwd=REPO_ROOT,
    )


def load_module(path: Path, name: str):
    """Load *path* as a module by file path, without writing bytecode."""
    spec = importlib.util.spec_from_file_location(name, path)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    previous = sys.dont_write_bytecode
    sys.dont_write_bytecode = True
    try:
        spec.loader.exec_module(module)
    finally:
        sys.dont_write_bytecode = previous
    return module


def item_params(case_toml: dict, item_id: str) -> dict:
    """The ``params`` table of the named ``[[items]]`` entry."""
    (item,) = [item for item in case_toml["items"] if item["id"] == item_id]
    return item.get("params", {})


def write_transcript(path: Path, commands: list[str], *, final_text: str = "Done.") -> Path:
    """Write a synthetic subagent transcript in the real Claude Code envelope shape.

    One ``assistant`` line per Bash call (``message.content[]`` holds a
    ``tool_use`` block with ``name``/``input``/``id``), each followed by a
    ``user`` line holding the matching ``tool_result`` block, then a closing
    ``assistant`` text block.
    """
    lines: list[dict] = []
    for index, command in enumerate(commands, start=1):
        tool_use_id = f"toolu_{index:04d}"
        lines.append(
            {
                "type": "assistant",
                "uuid": f"a-{index}",
                "timestamp": f"2026-10-01T10:00:{index:02d}.000Z",
                "message": {
                    "role": "assistant",
                    "model": "claude-sonnet-5-5",
                    "content": [
                        {
                            "type": "tool_use",
                            "id": tool_use_id,
                            "name": "Bash",
                            "input": {"command": command, "description": "run"},
                        }
                    ],
                },
            }
        )
        lines.append(
            {
                "type": "user",
                "uuid": f"u-{index}",
                "timestamp": f"2026-10-01T10:00:{index:02d}.500Z",
                "message": {
                    "role": "user",
                    "content": [
                        {
                            "type": "tool_result",
                            "tool_use_id": tool_use_id,
                            "is_error": False,
                            "content": "ok",
                        }
                    ],
                },
            }
        )
    lines.append(
        {
            "type": "assistant",
            "uuid": "a-final",
            "message": {
                "role": "assistant",
                "model": "claude-sonnet-5-5",
                "content": [{"type": "text", "text": final_text}],
            },
        }
    )
    path.write_text("\n".join(json.dumps(line) for line in lines) + "\n", encoding="utf-8")
    return path


def commit_log_text(subject: str, body: str = "", sha: str = "0123456789abcdef0123456789abcdef01234567") -> str:
    """The text of ``git log -1 --format=%H%n%B`` for a commit with this message."""
    message = subject if not body else f"{subject}\n\n{body}"
    return f"{sha}\n{message}\n\n"


def evidence_from(
    tmp_path: Path,
    *,
    commands: list[str] | None = None,
    logs: list[str] | None = None,
    files: list[str] | None = None,
    workdir: Path | None = None,
):
    """Build an ``Evidence`` from synthetic commands and commit snapshot files.

    ``commands`` becomes one parsed Bash-only subagent transcript;
    ``logs``/``files`` become ``commit-<k>.log`` / ``commit-<k>.files`` in
    ``evidence.end_state``, oldest first.
    """
    from evals._harness.dispatch import Evidence
    from evals._harness.transcript import parse_transcript

    transcript_path = write_transcript(tmp_path / "agent-synthetic.jsonl", commands or [])
    end_state: dict[str, str] = {}
    for position, text in enumerate(logs or [], start=1):
        end_state[f"commit-{position}.log"] = text
    for position, text in enumerate(files or [], start=1):
        end_state[f"commit-{position}.files"] = text
    return Evidence(
        transcripts=[parse_transcript(transcript_path)],
        findings=[],
        workdir=workdir,
        end_state=end_state,
    )


# --- synthetic evidence ------------------------------------------------------

FAKE_SHA = "0123456789abcdef0123456789abcdef01234567"

# A well-formed attempt: the checks run first, two single-unit commits, no
# blanket staging, no `.env`, clean subjects.
GOOD_COMMANDS = [
    "git status",
    "git diff",
    "make test",
    "git add invoice/pricing.py tests/test_pricing.py",
    'git commit -m "feat(invoice): add bulk pricing"',
    "git add names/normalize.py tests/test_names.py",
    'git commit -m "fix(names): collapse inner whitespace"',
]
GOOD_LOGS = [
    commit_log_text("feat(invoice): add bulk pricing"),
    commit_log_text("fix(names): collapse inner whitespace"),
]
GOOD_FILES = [
    "invoice/pricing.py\ntests/test_pricing.py\n",
    "names/normalize.py\ntests/test_names.py\n",
]
