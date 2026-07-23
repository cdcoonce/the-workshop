# Vault Operating Principles

These skills implement slash commands for Charles Coonce's vault, **The Vault** (formerly “My Brain”), when the slash-command registry is not available.

## Before Acting

1. Confirm the active repository is The Vault. Look for `AGENTS.md` with the vault operating manual and `.vault-context` with `work` or `personal`.
2. Read the root `AGENTS.md`. If touching `work/`, `personal/`, or `perf/`, also read that folder's scoped `AGENTS.md` if it exists.
3. Treat the vault as the source of truth. Do not rely on machine-local auto-memory for durable facts.
4. Use existing vault scripts under `.claude/scripts/` whenever the command spec names them. Do not recreate script logic in the chat.

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
