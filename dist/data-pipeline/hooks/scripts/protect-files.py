#!/usr/bin/env python3
"""Pre-edit hook: block edits to sensitive/generated files."""

import json
import sys

data = json.load(sys.stdin)
file_path = data.get("tool_input", {}).get("file_path", "")

if not file_path:
    sys.exit(0)

PROTECTED_PATTERNS = [".env", "package-lock.json", "uv.lock", "node_modules/", ".git/"]

for pattern in PROTECTED_PATTERNS:
    if pattern in file_path:
        print(f"Blocked: {file_path} matches protected pattern '{pattern}'", file=sys.stderr)
        sys.exit(2)
