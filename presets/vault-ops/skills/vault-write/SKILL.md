---
name: vault-write
description: >
  Draft Outlook or Teams messages in Charles's voice using the My Brain /write communication rules. Trigger when Charles invokes /write, mentions /write, or asks for this vault workflow by name.
---

# Vault Write

Use this skill only inside Charles Coonce's My Brain vault, or when helping install/test the vault plugin for that vault.

## Required Reading

1. Read [vault-operating-principles.md](references/vault-operating-principles.md).
2. Read [command.md](references/command.md).
3. Follow the command reference exactly, adapting tool names to the current agent environment.

## Execution

- If the command accepts arguments, parse them from the user's message and pass them through to the referenced workflow.
- Prefer the vault's existing scripts and managers over hand-rolled logic.
- Report concise results with paths, decisions, validations, and any blocked steps.
