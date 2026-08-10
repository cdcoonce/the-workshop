#!/usr/bin/env bash
# Portable hook runner — resolves script location via BASH_SOURCE.
# Works in Claude Code ($CLAUDE_PLUGIN_ROOT), Cortex Code Desktop (CoCo), and Codex.
# Usage: bash run-hook.sh [--uv] <script-name> [args...]
# Extra args after the script name are forwarded to the Python hook.
#
# --uv runs the script under `uv run` instead of python3, so a hook that carries
# a PEP-723 `# /// script` block gets its own resolved environment. Hooks that
# need nothing but the stdlib take the default path and stay dependency-free.
HOOK_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
# Self-located root, always correct regardless of which env var (if any) got
# this script invoked. Export it so the Python hooks below — which only ever
# check CLAUDE_PLUGIN_ROOT — see a real value on platforms (Cortex) that never
# set it themselves.
export CLAUDE_PLUGIN_ROOT="$(cd "$HOOK_DIR/.." && pwd)"
if [ "$1" = "--uv" ]; then
  shift
  exec uv run "$HOOK_DIR/scripts/$1" "${@:2}"
fi
exec python3 "$HOOK_DIR/scripts/$1" "${@:2}"
