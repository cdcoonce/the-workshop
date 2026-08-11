---
name: vault-essay
description: >
  Draft long-form prose (essays and posts) in Charles's voice using The Vault's /essay writing rules. Trigger when Charles invokes /essay, mentions /essay, or asks to draft an essay or post in his voice.
---

# Vault Essay

Use this skill only inside Charles Coonce's The Vault, or when helping install/test the vault plugin for that vault.

## Required Reading

1. Read [vault-operating-principles.md](references/vault-operating-principles.md).
2. Read [command.md](references/command.md).
3. Follow the command reference exactly, adapting tool names to the current agent environment.

## Execution

- If the command accepts arguments, parse them from the user's message and pass them through to the referenced workflow.
- Prefer the vault's existing scripts and managers over hand-rolled logic.
- Report concise results with paths, decisions, validations, and any blocked steps.
