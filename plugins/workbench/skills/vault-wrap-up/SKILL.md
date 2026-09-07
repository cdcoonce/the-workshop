---
name: vault-wrap-up
description: >
  Run Charles's vault (The Vault) /wrap-up session audit, handoff refresh, git sync, and optional post-sync session launches. Trigger when Charles invokes /wrap-up, signals the session is ending, or explicitly asks to run this vault workflow.
---

# Vault Wrap Up

Use this skill only inside Charles Coonce's The Vault, or when helping install/test the vault plugin for that vault.

Discussion, editing, or testing of this skill is not an invocation. Run the
workflow only after an explicit `/wrap-up`, session-end signal, or request to run
it.

## Required Reading

1. Read [vault-operating-principles.md](references/vault-operating-principles.md).
2. Read [command.md](references/command.md).
3. After sync succeeds, read [session-follow-up.md](references/session-follow-up.md).
4. Follow the command references exactly, adapting tool names to the current agent environment.

## Execution

- If the command accepts arguments, parse them from the user's message and pass them through to the referenced workflow.
- Prefer the vault's existing scripts and managers over hand-rolled logic.
- Report concise results with paths, decisions, validations, and any blocked steps.
