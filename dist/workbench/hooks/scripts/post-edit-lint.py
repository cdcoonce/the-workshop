#!/usr/bin/env python3
"""Post-edit hook: auto-format and lint edited files with whatever toolchain is
present — Ruff (Python), Prettier (web/markup/config), ESLint (JS/TS), Stylelint
(CSS). Each tool is guarded by file extension and no-ops when the tool is absent,
so the single workbench hook covers every project type the old per-preset hooks
did (Ruff-only / +Prettier / +ESLint+Stylelint) without misformatting a project
that lacks a given tool."""

import json
import os
import shutil
import subprocess
import sys

try:
    data = json.load(sys.stdin)
except json.JSONDecodeError:
    # Fail open: a malformed/empty stdin payload should no-op, not traceback.
    sys.exit(0)
file_path = data.get("tool_input", {}).get("file_path", "")

if not file_path:
    sys.exit(0)

actions = []


def run(cmd, label):
    """Run a command silently, ignoring failures (missing tool or nonzero exit)."""
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

# Prettier on web, markup, and config files (npx --no-install no-ops if absent)
if file_path.endswith((".html", ".css", ".js", ".ts", ".jsx", ".tsx", ".md", ".json")):
    run(["npx", "--no-install", "prettier", "--write", file_path], "prettier")

# ESLint on JS/TS files
if file_path.endswith((".js", ".ts", ".jsx", ".tsx")):
    run(["npx", "--no-install", "eslint", "--fix", file_path], "eslint")

# Stylelint on CSS files
if file_path.endswith(".css"):
    run(["npx", "--no-install", "stylelint", "--fix", file_path], "stylelint")

if actions:
    print(f"Hook ran: {', '.join(actions)} on {os.path.basename(file_path)}", file=sys.stderr)
