# Vault Operating Principles

These skills implement slash commands for Charles Coonce's vault, **The Vault** (formerly “My Brain”), when the slash-command registry is not available.

## Before Acting

1. Confirm the active repository is The Vault. Look for `AGENTS.md` with the vault operating manual and `.vault-context` with `work` or `personal`.
2. Read the root `AGENTS.md`. If touching `work/`, `personal/`, or `perf/`, also read that folder's scoped `AGENTS.md` if it exists.
3. Treat the vault as the source of truth. Do not rely on machine-local auto-memory for durable facts.
4. Use the existing engine scripts whenever the command spec names them — see [Engine Location](#engine-location). Do not recreate script logic in the chat.

## Engine Location

Command specs write the engine directory as `<engine>`. **Resolve it to a real
absolute path and write that path out in full, every time.** Where it is depends
on how this vault is set up, so check rather than assume:

- **Running from the installed plugin** (the usual case — this skill loaded from
  a plugin cache, and the vault root has a `.vault/vault.json`): the engine is
  `<announced skill base directory>/../../machinery/engine`.
- **Running from a vendored vault** (this skill loaded from `<vault>/.claude/skills/`
  or `<vault>/.codex/skills/`, and the vault has a `machinery.lock.json`): the
  engine is `<vault>/.claude/scripts/`.

Confirm the script you are about to run actually exists at the path you picked
before running it. Both layouts are in service; guessing wrong fails quietly,
because a missing path looks the same as a step that had nothing to do.

`<engine>` is a placeholder you expand while composing the command — **not** a
shell variable. Each command runs in a fresh shell, so an assignment made in one
does not survive into the next: the reference expands to nothing and the path
collapses to a bare script name at the filesystem root. If you want a variable,
assign it and use it inside a _single_ command.

`$CLAUDE_PLUGIN_ROOT` is unusable here for the same family of reason. It is
defined only in the _hook_ environment, never in the shell a skill runs commands
in, so it expands to nothing wherever a skill reaches for it.

Keep whichever runner the command spec names — they are not interchangeable.
Scripts carrying PEP-723 inline dependencies must go through `uv run --script`
(or bare `uv run`); running one of those under plain `python` skips its
dependencies and fails to import.

```bash
uv run --script "/abs/path/to/machinery/engine/semantic_index.py" search "<query>"
uv run python "/abs/path/to/machinery/engine/graph_gardener.py" --queue-summary
python3 "/abs/path/to/machinery/engine/pulse.py"
```

## Tool Mapping

- Claude Code `AskUserQuestion` means the best available user-input mechanism. In Codex, use `request_user_input` when available; otherwise ask a concise plain-text question only when blocked.
- Claude Code `Edit`/`Write` means the safest available file-edit mechanism. In Codex, prefer `apply_patch` for manual edits.
- Subagent delegation means use available cheap-worker/subagent tooling. If unavailable, keep the conductor context lean and read only what is necessary.
- Shell commands should run from the vault root unless the command spec gives another path.

## Vault Invariants

- Every markdown note outside excluded infrastructure must have required YAML frontmatter.
- Notes over 300 characters need at least one resolving `[[wikilink]]`.
- New, moved, or archived notes must update the relevant index.
- Never delete notes, force-push, or auto-resolve conflicts without explicit user approval.
- Generated caches, local indexes, and counters are machine-local unless the vault rules say otherwise.
- Git sync rebases before push and aborts on conflicts.

## Precedence

The active vault's `AGENTS.md`, scoped `AGENTS.md`, and `brain/Constitution.md` win over these portable skill wrappers. The command reference bundled with each skill is the behavior spec for that command.
