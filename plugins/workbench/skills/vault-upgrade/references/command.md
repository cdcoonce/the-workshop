# /vault-upgrade — Re-vendor the Managed Machinery

Upgrade the vault's vendored machinery (engine scripts, agents, skills, hook wiring, lifecycle tools) from the-workshop's `vault-ops` preset. The managed tier is tracked by `.vault/machinery.lock.json`; the tools are `machinery_sync.py` (vendor) and `machinery_check.py` (drift), both vendored at `.claude/scripts/`.

## Usage

```
/vault-upgrade            — full upgrade from the local the-workshop checkout
/vault-upgrade <source>   — upgrade from an explicit machinery dir
```

## Locating the Source

The `--source` is a machinery dir containing `vendor-map.json`:

1. **Local checkout (preferred):** `<the-workshop>/plugins/workbench/machinery` — make sure it is on up-to-date `main` (`git fetch` first; never upgrade from a mid-review branch).
2. **Plugin cache:** the installed vault-ops plugin's `machinery/` directory, when no checkout exists on this machine.

## Process

1. **Pre-check.** Run `python3 .claude/scripts/machinery_check.py --strict`. Understand any non-OK file BEFORE upgrading — a LOCAL-EDIT here will surface as a REFUSE below; an UNTRACKED file needs a home first.
2. **Dry-run the plan.** `python3 .claude/scripts/machinery_sync.py upgrade --target . --source <machinery-dir>` (dry-run is the default). Read every line: `copy`, `skip-identical`, `keep-local`, `REFUSE local-edit`.
3. **Triage every REFUSE — NEVER blind-force.** A refused plan applies nothing (atomic). For each refusal, diff the vault file against the source file and decide:
   - **Vault is ahead** (the local edit is an improvement): copy the file to the workshop checkout, open a PR to `dev`, and re-run the upgrade after it merges — the edit becomes upstream instead of drift.
   - **Vault is behind intentionally** (a deliberate local divergence): re-run with `--keep-local <path>`; the flag is sticky in the lock for later upgrades.
   - **Vault edit is stale or accidental**: re-run with `--force` to overwrite — a deliberate per-file judgment, never a default.
4. **Apply.** Re-run the same command with `--apply` (plus any `--keep-local` flags). Exit 0 and a rewritten lockfile means it landed.
5. **Post-check.** Run `python3 .claude/scripts/machinery_check.py --strict` again — everything must be OK.
6. **Commit.** One commit for the whole upgrade, citing the source version and ref from the fresh lockfile's `source` block, e.g. `chore: upgrade vendored machinery to vault-ops 1.3.0 (<ref>)`.

## Constraints

- **One sitting.** Run steps 1-6 to completion in the same session — never leave a half-applied upgrade for the Stop auto-sync hook to push.
- **Never `--force` the whole plan** to silence refusals; force is per-decision, after reading the diff.
- Scaffold-tier files (e.g. `.claude/scripts/vault_scope.py`, `AGENTS.md`) are owner-owned: upgrade never touches them, and that is correct — do not try to "fix" them into the managed set.
- A json-key refusal on `.claude/settings.json` that reports invalid JSON must be repaired by hand first; the tool refuses even under `--force` to avoid destroying sibling keys.
- If the plan or the check fails in a way you cannot explain, stop and report; do not iterate flags until it exits 0.
