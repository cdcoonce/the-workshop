#!/usr/bin/env bash
# Vault-owned presence check. The ONE piece of machinery the vault still owns —
# everything else ships in workbench@the-workshop.
#
# Why it exists: once the vault's hooks live in the plugin, the failure mode is
# silence. The plugin gets uninstalled, or downgraded, or its marketplace entry
# breaks, and the vault simply stops auto-committing, stops loading context,
# stops validating frontmatter — with nothing to notice it. This reads the
# breadcrumb the plugin writes at SessionStart and says so out loud.
#
# Wired as a vault SessionStart hook in .claude/settings.json. Fails open.

set -u
VAULT_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
STATE="$VAULT_ROOT/.vault/plugin-state.json"
MISSES="$VAULT_ROOT/.vault/.plugin-miss-count"

min_version="$(sed -n 's/.*"min_plugin_version"[[:space:]]*:[[:space:]]*"\([^"]*\)".*/\1/p' \
  "$VAULT_ROOT/.vault/vault.json" 2>/dev/null)"

if [ ! -f "$STATE" ]; then
  # One session of grace: on Cortex, SessionStart fires ~1s BEFORE plugin
  # activation, so a window's first restored session legitimately has no
  # breadcrumb yet. Warning on that would train the owner to ignore this.
  misses=$(( $(cat "$MISSES" 2>/dev/null || echo 0) + 1 ))
  echo "$misses" > "$MISSES"
  [ "$misses" -le 1 ] && exit 0
  echo "VAULT PLUGIN MISSING: no .vault/plugin-state.json after $misses sessions." >&2
  echo "  workbench@the-workshop is not running this vault's hooks — no auto-commit," >&2
  echo "  no context load, no frontmatter validation. Reinstall it, or remove" >&2
  echo "  .vault/vault.json if this vault is deliberately unmanaged." >&2
  exit 0
fi

rm -f "$MISSES"
version="$(sed -n 's/.*"version"[[:space:]]*:[[:space:]]*"\([^"]*\)".*/\1/p' "$STATE" 2>/dev/null)"

# Name BOTH versions. "Plugin is stale" without the numbers sends the owner
# hunting for what stale means.
if [ -n "$min_version" ] && [ -n "$version" ] && [ "$version" != "$min_version" ]; then
  older="$(printf '%s\n%s\n' "$version" "$min_version" | sort -V | head -1)"
  if [ "$older" = "$version" ]; then
    echo "VAULT PLUGIN STALE: workbench $version is running, but .vault/vault.json" >&2
    echo "  requires at least $min_version. Run: claude plugin update workbench@the-workshop" >&2
  fi
fi
exit 0
