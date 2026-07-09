---
name: vault-mr-review-packet
description: >
  Run Charles's My Brain /mr-review-packet workflow to generate a self-guided reviewer packet for a large merge request. Trigger when Charles invokes /mr-review-packet, mentions /mr-review-packet, or asks for a review packet / reviewer walkthrough for a big MR.
---

# Vault MR Review Packet

Use this skill only inside Charles Coonce's My Brain vault, or when helping install/test the vault plugin for that vault.

## Required Reading

1. Read [vault-operating-principles.md](references/vault-operating-principles.md).
2. Read [command.md](references/command.md).
3. Follow the command reference exactly, adapting tool names to the current agent environment.

## Execution

- If the command accepts arguments, parse them from the user's message and pass them through to the referenced workflow.
- Prefer the vault's existing scripts and managers over hand-rolled logic.
- Report concise results with paths, decisions, validations, and any blocked steps.
