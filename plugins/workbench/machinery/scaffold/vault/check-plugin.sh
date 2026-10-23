#!/usr/bin/env bash
# Vault-owned presence check. The ONE piece of machinery the vault still owns —
# everything else ships in workbench@the-workshop.
#
# Why it exists: once the vault's hooks live in the plugin, the failure mode is
# silence. The plugin gets uninstalled, or downgraded, or its marketplace entry
# breaks, and the vault simply stops auto-committing, stops loading context,
# stops validating frontmatter — with nothing to notice it. This reads the
# breadcrumbs the plugin writes at SessionStart (.vault/plugin-state.json plus
# one .vault/plugin-state.<platform>.json per platform) and says so out loud.
#
# It answers three questions, each with its own warning:
#   1. Is the plugin running?     VAULT PLUGIN MISSING  (no breadcrumb at all)
#                                 VAULT PLUGIN NOT RUNNING  (breadcrumb exists
#                                 but its per-session marker has not changed
#                                 for NOT_RUNNING_AFTER sessions)
#   2. Is it the current copy?    VAULT PLUGIN SUPERSEDED  (the recorded root
#                                 carries the plugin manager's .orphaned_at
#                                 marker: this session's hooks are bound to a
#                                 copy that has since been replaced)
#   3. Do the platforms agree?    VAULT PLUGIN VERSIONS DISAGREE  (per-platform
#                                 breadcrumbs record different versions)
#
# This script and the plugin's SessionStart hook run at the same event with no
# ordering guarantee, so the check can only describe the session before this
# one. A plugin that stopped running is therefore detected one session late.
#
# min_plugin_version in .vault/vault.json is NOT a currency signal. Its only
# job is incompatibility: "versions older than this cannot serve this vault".
# Every release moves the real version up and leaves the number where it is, so
# a floor passes by default and cannot see questions 1-3.
#
# Wired as a vault SessionStart hook in .claude/settings.json. Fails open: every
# path exits 0.

set -u
VAULT_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
STATE="$VAULT_ROOT/.vault/plugin-state.json"
MISSES="$VAULT_ROOT/.vault/.plugin-miss-count"
TRACK="$VAULT_ROOT/.vault/.plugin-session-track"
# Consecutive sessions an unchanged session marker may span before it is a finding.
NOT_RUNNING_AFTER=3

json_field() { # json_field <key> <file>
  sed -n 's/.*"'"$1"'"[[:space:]]*:[[:space:]]*"\([^"]*\)".*/\1/p' "$2" 2>/dev/null | head -1
}

# Per-platform breadcrumbs first: the legacy shared file is last-writer-wins
# across platforms, so another platform's stale write there must not decide the
# version below (#1280). It is read only when no per-platform file exists.
crumbs=()
for f in "$VAULT_ROOT"/.vault/plugin-state.*.json; do
  [ -f "$f" ] && crumbs+=("$f")
done
[ "${#crumbs[@]}" -eq 0 ] && [ -f "$STATE" ] && crumbs+=("$STATE")

min_version="$(sed -n 's/.*"min_plugin_version"[[:space:]]*:[[:space:]]*"\([^"]*\)".*/\1/p' \
  "$VAULT_ROOT/.vault/vault.json" 2>/dev/null)"

if [ "${#crumbs[@]}" -eq 0 ]; then
  # One session of grace: on Cortex, SessionStart fires ~1s BEFORE plugin
  # activation, so a window's first restored session legitimately has no
  # breadcrumb yet. Warning on that would train the owner to ignore this.
  misses=$(( $(cat "$MISSES" 2>/dev/null || echo 0) + 1 ))
  echo "$misses" > "$MISSES"
  [ "$misses" -le 1 ] && exit 0
  echo "VAULT PLUGIN MISSING: no .vault/plugin-state*.json after $misses sessions." >&2
  echo "  workbench@the-workshop is not running this vault's hooks — no auto-commit," >&2
  echo "  no context load, no frontmatter validation. Reinstall it, or remove" >&2
  echo "  .vault/vault.json if this vault is deliberately unmanaged." >&2
  exit 0
fi

rm -f "$MISSES"
version="$(json_field version "${crumbs[0]}")"

# 1. Is it running? The plugin rewrites a per-session marker into every
# breadcrumb each session. Count sessions since the combined markers last
# changed. A breadcrumb with no marker (an older plugin) cannot be judged and is
# never a finding.
signature=""
for f in "${crumbs[@]}"; do
  signature="$signature|$(json_field session "$f")"
done
if [ "$signature" != "$(printf '|%.0s' "${crumbs[@]}")" ]; then
  recorded="$(sed -n 1p "$TRACK" 2>/dev/null)"
  unchanged="$(sed -n 2p "$TRACK" 2>/dev/null)"
  case "$unchanged" in ''|*[!0-9]*) unchanged=0 ;; esac
  if [ "$recorded" = "$signature" ]; then
    unchanged=$(( unchanged + 1 ))
  else
    unchanged=0
  fi
  printf '%s\n%s\n' "$signature" "$unchanged" > "$TRACK" 2>/dev/null
  if [ "$unchanged" -ge "$NOT_RUNNING_AFTER" ]; then
    echo "VAULT PLUGIN NOT RUNNING: workbench ${version:-unknown} last recorded a session, and the" >&2
    echo "  record has not changed for $unchanged sessions. Its hooks are not firing in this" >&2
    echo "  vault — no auto-commit, no context load, no frontmatter validation." >&2
    echo "  Reinstall it, or remove .vault/vault.json if this vault is deliberately unmanaged." >&2
  fi
fi

# 2. Is it the current copy? The breadcrumb's root names the copy that executed.
# The plugin manager drops .orphaned_at into a copy it has replaced; hooks stay
# bound to that copy until the session restarts. A missing marker is never
# evidence: a root that is gone, or a platform that does not keep the
# convention, says nothing.
seen_roots=""
for f in "${crumbs[@]}"; do
  root="$(json_field root "$f")"
  [ -n "$root" ] && [ -f "$root/.orphaned_at" ] || continue
  case "|$seen_roots|" in *"|$root|"*) continue ;; esac
  seen_roots="$seen_roots|$root"
  echo "VAULT PLUGIN SUPERSEDED: this session's hooks run from $root" >&2
  echo "  (workbench $(json_field version "$f")), which the plugin manager has replaced." >&2
  echo "  Restart the session to pick up the current copy; updating the plugin again changes nothing." >&2
done

# 3. Do the platforms agree? Per-platform breadcrumbs only; the legacy file is
# a copy of one of them.
first_platform=""; first_version=""
for f in "$VAULT_ROOT"/.vault/plugin-state.*.json; do
  [ -f "$f" ] || continue
  platform="$(json_field platform "$f")"; pversion="$(json_field version "$f")"
  [ -n "$platform" ] && [ -n "$pversion" ] || continue
  if [ -z "$first_platform" ]; then
    first_platform="$platform"; first_version="$pversion"
  elif [ "$pversion" != "$first_version" ]; then
    echo "VAULT PLUGIN VERSIONS DISAGREE: $first_platform runs workbench $first_version but" >&2
    echo "  $platform runs $pversion. Update the platform that is behind." >&2
    break
  fi
done

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
