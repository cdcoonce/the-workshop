---
name: vault-clickup-task-sync
description: >
  Run Charles's My Brain /clickup-task-sync workflow to sync vault action items into ClickUp without duplicating tasks. Trigger when Charles invokes /clickup-task-sync, mentions /clickup-task-sync, or asks to sync action items / a 1:1 recap into ClickUp.
---

# Vault ClickUp Task Sync

Use this skill only inside Charles Coonce's My Brain vault, or when helping install/test the vault plugin for that vault.

## Required Reading

1. Read [vault-operating-principles.md](references/vault-operating-principles.md).
2. Read [command.md](references/command.md).
3. Follow the command reference exactly, adapting tool names to the current agent environment (this skill assumes a ClickUp MCP/connector is available; if none is connected, say so rather than guessing at an API call).

## Execution

- If the command accepts arguments, parse them from the user's message and pass them through to the referenced workflow.
- Prefer the vault's existing scripts and managers over hand-rolled logic.
- Report concise results with paths, decisions, validations, and any blocked steps.
