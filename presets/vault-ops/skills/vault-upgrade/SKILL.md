---
name: vault-upgrade
description: >
  Run Charles's vault (The Vault) /vault-upgrade workflow to re-vendor the vault's managed machinery from the-workshop with strict drift checks and per-file refusal triage. Trigger when Charles invokes /vault-upgrade, mentions /vault-upgrade, or asks to upgrade the vault's vendored machinery.
---

# Vault Upgrade

Use this skill only inside Charles Coonce's The Vault, or when helping maintain another vault vendored from the-workshop's vault-ops preset.

## Required Reading

1. Read [vault-operating-principles.md](references/vault-operating-principles.md).
2. Read [command.md](references/command.md).
3. Follow the command reference exactly, adapting tool names to the current agent environment.

## Execution

- Run the strict drift check before and after the upgrade; never apply over unexplained drift.
- NEVER blind-force: every REFUSE in the plan gets a per-file decision (upstream the edit, keep it locally, or overwrite deliberately).
- Run the upgrade to completion in one sitting — never leave a half-applied state for the Stop auto-sync to push.
- Report concise results with the plan summary, per-refusal decisions, and the commit that landed.
