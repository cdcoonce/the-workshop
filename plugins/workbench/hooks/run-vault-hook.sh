#!/usr/bin/env bash
# Guarded runner for the vault hooks that ship inside workbench.
#
# These hooks are wired into workbench's hooks.json, which EVERY consumer of
# workbench loads — so they are dispatched on every session in every repo. Only
# a vault should pay for them. The guard below therefore runs before any
# interpreter starts: `uv run` on a cold cache is the expensive part, and a
# Python-level "am I in a vault?" check has already paid it by the time it can
# answer. Everything here is bash builtins and a file test.
#
# Usage: bash run-vault-hook.sh <script-name.py> [args...]
# Exits 0 and spawns nothing when the session is not inside a vault.

HOOK_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
PLUGIN_ROOT="$(cd "$HOOK_DIR/.." && pwd)"

# `.vault/vault.json` is the marker, deliberately — not `CLAUDE.md`, which
# ordinary project repos carry too. Matching on CLAUDE.md is the bug that once
# let the vault's auto-commit run inside whatever repo the shell was sitting
# in; see vault_utils.find_vault_root.
#
# CLAUDE_PROJECT_DIR is set by Claude Code but not by Cortex or Codex, so cwd
# is the fallback. Walk up from there: sessions routinely start in a
# subdirectory of the vault, not at its root.
start_dir="${CLAUDE_PROJECT_DIR:-$PWD}"
vault_root=""
dir="$start_dir"
while [ -n "$dir" ] && [ "$dir" != "/" ]; do
  if [ -f "$dir/.vault/vault.json" ]; then
    vault_root="$dir"
    break
  fi
  dir="$(dirname "$dir")"
done

# Not a vault. This is the common case for every other repo on the machine,
# and it must cost nothing.
[ -z "$vault_root" ] && exit 0

# The engine reads CLAUDE_PROJECT_DIR (via vault_utils.find_vault_root_from_env)
# and CLAUDE_PLUGIN_ROOT. Export both so the hooks behave identically on
# platforms that set neither.
export CLAUDE_PROJECT_DIR="$vault_root"
export CLAUDE_PLUGIN_ROOT="$PLUGIN_ROOT"

# The owner's scaffold-owned config (`vault_scope.py`) must be importable, or
# `vault_scope_resolved.py` silently falls back to shipped defaults: its lookup
# is `try: import vault_scope / except ImportError: use default`. Nothing logs
# and nothing fails — a vault that added "school" to GOVERNED_NOTE_DIRS would
# just quietly stop governing it. Before the flat reorg this resolved for free,
# because owner config sat in `.claude/scripts/` beside the engine.
export PYTHONPATH="$vault_root/.vault/config${PYTHONPATH:+:$PYTHONPATH}"

# Run from the vault root so cwd-relative resolution inside the engine still
# lands in the vault, and resolve dependencies from the machinery's own
# pyproject rather than the vault's — that separation is the point of #667.
cd "$vault_root" || exit 0
exec uv run --project "$PLUGIN_ROOT/machinery" python "$HOOK_DIR/scripts/$1" "${@:2}"
