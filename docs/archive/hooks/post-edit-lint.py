#!/usr/bin/env python3
"""Post-edit hook: auto-format and lint Python files with Ruff."""

import json
import os
import shutil
import subprocess
import sys

data = json.load(sys.stdin)
file_path = data.get("tool_input", {}).get("file_path", "")

if not file_path:
    sys.exit(0)

actions = []


def run(cmd, label):
    """Run a command silently, ignoring failures."""
    try:
        result = subprocess.run(cmd, capture_output=True)
        if result.returncode == 0:
            actions.append(label)
    except FileNotFoundError:
        pass


# Ruff on Python files
if file_path.endswith(".py") and shutil.which("ruff"):
    run(["ruff", "check", "--fix", file_path], "ruff-check")
    run(["ruff", "format", file_path], "ruff-format")

if actions:
    print(f"Hook ran: {', '.join(actions)} on {os.path.basename(file_path)}", file=sys.stderr)
