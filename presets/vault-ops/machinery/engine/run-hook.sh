#!/usr/bin/env bash
# Portable hook runner — resolves script + vault root via BASH_SOURCE instead
# of $CLAUDE_PROJECT_DIR, which Claude Code sets but Cortex Code Desktop and
# Codex do not (that gap made hook commands resolve to "/.claude/scripts/x.py"
# and fail outright). Works regardless of which agent invoked it or its cwd.
# Usage: bash run-hook.sh <script-name.py> [args...]
# Extra args after the script name are forwarded to the Python hook.
SCRIPTS_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
VAULT_ROOT="$(cd "$SCRIPTS_DIR/../.." && pwd)"
exec uv run --directory "$VAULT_ROOT" python "$SCRIPTS_DIR/$1" "${@:2}"
