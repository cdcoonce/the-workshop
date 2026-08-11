#!/usr/bin/env python3
"""UserPromptSubmit hook script — classifies user messages and injects routing hints.

Called by Claude Code on every user message.
Reads hook event JSON from stdin, classifies the message content,
and outputs routing hints via hookSpecificOutput.

Exit codes:
    0 — classification complete (or nothing to classify)
"""

from __future__ import annotations

import json
import sys
import traceback
from pathlib import Path

# Add scripts dir to path
SCRIPTS_DIR = Path(__file__).resolve().parent
sys.path.insert(0, str(SCRIPTS_DIR))

from content_classifier import classify, routing_hook_output


def main() -> int:
    try:
        raw = sys.stdin.read()
        if not raw.strip():
            return 0

        event = json.loads(raw)
    except Exception:
        return 0

    # Extract user message from the hook event
    prompt = event.get("prompt", "")
    if not prompt or not prompt.strip():
        return 0

    # Classify the message
    result = classify(prompt)

    # Only inject hints if we matched something (not the default "thought")
    if result.category == "thought":
        return 0

    print(json.dumps(routing_hook_output(result)))
    return 0


if __name__ == "__main__":
    try:
        sys.exit(main())
    except Exception:
        traceback.print_exc(file=sys.stderr)
        sys.exit(0)  # Don't block on classification errors
