---
name: vault-podcast
description: >
  Run Charles's vault (The Vault) /podcast workflow to render NotebookLM-style two-host audio episodes from vault notes (deep-dive) or teach lesson workspaces (lesson). Trigger when Charles invokes /podcast, mentions /podcast, or asks for a podcast or audio episode of vault content.
---

# Vault Podcast

Use this skill only inside Charles Coonce's The Vault, or when helping install/test the vault plugin for that vault.

## Required Reading

1. Read [vault-operating-principles.md](references/vault-operating-principles.md).
2. Read [command.md](references/command.md).
3. Follow the command reference exactly, adapting tool names to the current agent environment.

## Execution

- If the command accepts arguments, parse them from the user's message and pass them through to the referenced workflow.
- Prefer the vault's existing scripts and managers over hand-rolled logic.
- Report concise results with paths, decisions, validations, and any blocked steps.
