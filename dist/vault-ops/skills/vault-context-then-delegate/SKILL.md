---
name: vault-context-then-delegate
description: >
  Run Charles's vault (The Vault) /context-then-delegate workflow to resolve real-world ambiguity (email/SharePoint/Slack) before writing a coding-agent prompt. Trigger when Charles invokes /context-then-delegate, mentions /context-then-delegate, or is about to write a delegated prompt for a task with unresolved domain ambiguity.
---

# Vault Context Then Delegate

Use this skill only inside Charles Coonce's The Vault, or when helping install/test the vault plugin for that vault.

## Required Reading

1. Read [vault-operating-principles.md](references/vault-operating-principles.md).
2. Read [command.md](references/command.md).
3. Follow the command reference exactly, adapting tool names to the current agent environment (this skill assumes email/SharePoint/Slack search tools are available; if none is connected, say so rather than guessing at unresolved facts).

## Execution

- If the command accepts arguments, parse them from the user's message and pass them through to the referenced workflow.
- Prefer the vault's existing scripts and managers over hand-rolled logic.
- Report concise results with paths, decisions, validations, and any blocked steps.
