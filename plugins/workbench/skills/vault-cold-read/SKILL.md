---
name: vault-cold-read
description: >
  Run Charles's vault /cold-read gate — an adversarial read of an issue's
  SPEC before promotion to the afk executor. Trigger when Charles invokes
  /cold-read, asks if an issue is buildable cold, or is about to promote a
  `proposed` issue.
---

# Vault Cold Read

Use this skill only inside Charles Coonce's The Vault, or when helping install/test the vault plugin for that vault.

## Required Reading

1. Read [vault-operating-principles.md](references/vault-operating-principles.md).
2. Read [command.md](references/command.md).
3. Follow the command reference exactly, adapting tool names to the current agent environment.

## Execution

- If the command accepts arguments, parse them from the user's message and pass them through to the referenced workflow.
- Prefer the vault's existing scripts and managers over hand-rolled logic.
- Report concise results with paths, decisions, validations, and any blocked steps.
