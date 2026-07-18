#!/usr/bin/env python3
"""Pre-edit hook: block edits to sensitive/generated files."""

import json
import sys
from pathlib import PurePath

data = json.load(sys.stdin)
file_path = data.get("tool_input", {}).get("file_path", "")

if not file_path:
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
