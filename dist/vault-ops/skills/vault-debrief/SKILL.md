---
name: vault-debrief
description: >
  Run Charles's vault (The Vault) /debrief retrospective over recent afk builds. Trigger when Charles invokes /debrief, mentions /debrief, asks how much of the autonomous work needed his hands, asks whether /cold-read is actually earning its cost, or asks which stage keeps producing rework.
---

# Vault Debrief

Use this skill only inside Charles Coonce's The Vault, or when helping install/test the vault plugin for that vault.

## Required Reading

1. Read [vault-operating-principles.md](references/vault-operating-principles.md).
2. Read [command.md](references/command.md).
3. Follow the command reference exactly, adapting tool names to the current agent environment.

## Execution

- If the command accepts arguments, parse them from the user's message and pass them through to the referenced workflow.
- Prefer the vault's existing scripts and managers over hand-rolled logic.
- Report concise results with paths, decisions, validations, and any blocked steps.
