---
name: vault-init
description: >
  Run Charles's vault (The Vault) /vault-init workflow to scaffold a brand-new second-brain vault from the-workshop's vault-ops machinery. Trigger when Charles invokes /vault-init, mentions /vault-init, or asks to create, bootstrap, or stand up a new vault for himself or someone else.
---

# Vault Init

Use this skill to stand up a brand-new vault from the-workshop's vault-ops preset — for Charles, a teammate, or a separate context. It scaffolds into a NEW directory; it never modifies an existing vault.

## Required Reading

1. Read [vault-operating-principles.md](references/vault-operating-principles.md).
2. Read [command.md](references/command.md).
3. Follow the command reference exactly, adapting tool names to the current agent environment.

## Execution

- Interview the owner first (vault name, note-dir taxonomy, machine contexts, target directory); the init run itself is non-interactive.
- Never point init at a non-empty directory; the tool refuses, and overriding that refusal is the owner's explicit call.
- Walk the printed post-init checklist with the owner rather than dumping it.
- Verify by opening a session in the new vault and running the strict machinery check.
- Report concise results with the target path, chosen taxonomy, and any checklist steps still open.
