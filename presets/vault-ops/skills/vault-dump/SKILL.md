---
name: vault-dump
description: >
  Run Charles's vault (The Vault) /dump capture workflow for routing freeform input into durable vault notes, tasks, indexes, and wikilinks. Trigger when Charles invokes /dump, mentions /dump, or asks for this vault workflow by name.
---

# Vault Dump

Use this skill only inside Charles Coonce's The Vault, or when helping install/test the vault plugin for that vault.

## Required Reading

1. Read [vault-operating-principles.md](references/vault-operating-principles.md).
2. Read [command.md](references/command.md).
3. Follow the command reference exactly, adapting tool names to the current agent environment.

## Execution

- If the command accepts arguments, parse them from the user's message and pass them through to the referenced workflow.
- Prefer the vault's existing scripts and managers over hand-rolled logic.
- Report concise results with paths, decisions, validations, and any blocked steps.
