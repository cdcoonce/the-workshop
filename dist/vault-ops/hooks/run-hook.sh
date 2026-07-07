#!/usr/bin/env bash
# Portable hook runner — resolves script location via BASH_SOURCE.
# Works in Claude Code ($CLAUDE_PLUGIN_ROOT), Cortex Code Desktop (CoCo), and Codex.
# Usage: bash run-hook.sh <script-name>
HOOK_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
exec python3 "$HOOK_DIR/scripts/$1"
