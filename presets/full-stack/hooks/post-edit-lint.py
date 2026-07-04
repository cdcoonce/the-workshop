#!/usr/bin/env python3
"""Post-edit hook: auto-format with Prettier and lint JS/CSS/Python files."""

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


# Prettier on supported file types
if file_path.endswith((".html", ".css", ".js", ".ts", ".jsx", ".tsx", ".md", ".json")):
    run(["npx", "--no-install", "prettier", "--write", file_path], "prettier")

# ESLint on JS/TS files
if file_path.endswith((".js", ".ts", ".jsx", ".tsx")):
    run(["npx", "--no-install", "eslint", "--fix", file_path], "eslint")

# Stylelint on CSS files
if file_path.endswith(".css"):
    run(["npx", "--no-install", "stylelint", "--fix", file_path], "stylelint")

# Ruff on Python files
if file_path.endswith(".py") and shutil.which("ruff"):
    run(["ruff", "check", "--fix", file_path], "ruff-check")
    run(["ruff", "format", file_path], "ruff-format")

if actions:
    print(f"Hook ran: {', '.join(actions)} on {os.path.basename(file_path)}", file=sys.stderr)
