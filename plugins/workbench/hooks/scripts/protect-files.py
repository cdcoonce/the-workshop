#!/usr/bin/env python3
"""Pre-edit hook: block edits to sensitive/generated files."""

import json
import sys
from pathlib import PurePath

try:
    data = json.load(sys.stdin)
except (json.JSONDecodeError, ValueError):
    # Fail open: an unparseable payload names no file, so there is nothing
    # to protect — never surface an error on an unrelated edit.
    sys.exit(0)

if not isinstance(data, dict):
    # Fail open: a payload that isn't a JSON object isn't ours to act on.
    sys.exit(0)

tool_input = data.get("tool_input")
file_path = tool_input.get("file_path", "") if isinstance(tool_input, dict) else ""

if not isinstance(file_path, str) or not file_path:
    sys.exit(0)

PROTECTED_DIRS = ["node_modules", ".git"]
PROTECTED_FILENAMES = ["package-lock.json", "uv.lock"]
PROTECTED_BASENAME_PREFIXES = [".env"]
ALLOWED_TEMPLATE_SUFFIXES = [".example", ".sample", ".template", ".dist"]

path = PurePath(file_path)
basename = path.name

for directory in PROTECTED_DIRS:
    if directory in path.parts[:-1]:
        print(
            f"Blocked: {file_path} matches protected pattern '{directory}/'",
            file=sys.stderr,
        )
        sys.exit(2)

for filename in PROTECTED_FILENAMES:
    if basename == filename:
        print(
            f"Blocked: {file_path} matches protected pattern '{filename}'",
            file=sys.stderr,
        )
        sys.exit(2)

for prefix in PROTECTED_BASENAME_PREFIXES:
    if basename.startswith(prefix):
        if any(basename.endswith(suffix) for suffix in ALLOWED_TEMPLATE_SUFFIXES):
            continue
        print(
            f"Blocked: {file_path} matches protected pattern '{prefix}'",
            file=sys.stderr,
        )
        sys.exit(2)
