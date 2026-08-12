# /vault-init — Scaffold a Brand-New Vault

Create a fresh second-brain vault from the-workshop's `vault-ops` machinery: operating manual, note templates, taxonomy-parameterized scope rules, the full managed engine/skills/agents/hooks tier, a lockfile, and an initial git commit.

## Usage

```
/vault-init                 — interview, then scaffold
/vault-init <target-dir>    — interview with the target pre-filled
```

## Process

### 1. Interview the Owner

Collect, with sensible defaults offered:

- **Vault name** — human name for the vault (e.g. "The Vault"). Default: the target directory name.
- **Note-dir taxonomy** — the governed note directories. Default: `brain,work,personal,org,perf,reference`. Plain directory names only; this becomes `GOVERNED_NOTE_DIRS` in the scaffolded `vault_scope.py`.
- **Machine contexts** — the `.vault-context` values the vault distinguishes. Default: `personal,work`.
- **Target directory** — must be new or empty.

### 2. Locate the Source

The `--source` is a machinery dir containing `vendor-map.json` and `scaffold/`:

1. **Local checkout (preferred):** `<the-workshop>/plugins/workbench/machinery`, on up-to-date `main`.
2. **Plugin cache:** the installed vault-ops plugin's `machinery/` directory.

### 3. Run Init

```bash
python3 <machinery-dir>/tools/machinery_sync.py init \
  --target <dir> \
  --vault-name "<name>" \
  --note-dirs <a,b,c> \
  --contexts <x,y>
```

Non-interactive by design. Behavior: refuses a non-empty target (`--force-empty-check` overrides — owner's explicit call only), renders the scaffold templates, copies the verbatim trees, and runs `git init` plus an initial commit when the target is not already a repo.

What it writes:

| Path                                         | What it is                                                        |
| -------------------------------------------- | ----------------------------------------------------------------- |
| `AGENTS.md`, `CLAUDE.md`, `SETUP.md`         | Operating manuals, parameterized with the interview answers       |
| `.gitconfig`, `.gitignore`, `pyproject.toml` | Repo conventions                                                  |
| `templates/`                                 | Note templates                                                    |
| `.vault/vault.json`                          | The marker that makes the vault's hooks run at all                |
| `.vault/check-plugin.sh`                     | Presence check for the plugin, wired via `.claude/settings.json`  |
| `.vault/config/vault_scope.py`               | The owner's taxonomy — the one config the interview parameterizes |

Init vendors **nothing** and writes no lockfile. The engine, skills, agents, and hooks all ship in `workbench@the-workshop` and run from the installed plugin.

`.vault/config/` starts with exactly one file. The other owner-config names (`context_paths.py`, `content_routing.py`, `budget_burn_config.py`, `frontmatter_schema.json`) carry no interview answers, so scaffolding them would hand the owner a byte-copy of the shipped defaults that then shadows those defaults wholesale and never receives a later fix. An owner who wants one copies the matching `*_defaults.py` out of `machinery/engine/` into `.vault/config/`, drops the `_defaults` suffix, and edits it.

### 4. Walk the Post-Init Checklist

Init prints the checklist; walk it with the owner step by step:

1. Write `.vault-context` (gitignored, one per machine).
2. Wire git conventions: `git config --local --add include.path '../.gitconfig'`.
3. Install `workbench@the-workshop` from the the-workshop marketplace — the vault's hooks and engine ship in it, so the vault does nothing without it. Init writes `.vault/vault.json` with the source plugin's version as `min_plugin_version`, so `check-plugin.sh` will warn if a stale plugin is later installed over it.
4. Codex only, once per machine: approve hook trust interactively — hooks are silently skipped until trusted (automation may use `codex exec --dangerously-bypass-hook-trust`).
5. Add a private git remote and push, if the vault should sync across machines.

### 5. Verify

- Open an agent session in the new vault: the session-start hook should inject context with no Python errors.
- Confirm the hooks are actually live, not merely installed: make a trivial edit and check the auto-commit fires. A vault missing `.vault/vault.json` looks identical to a healthy one until you look for the thing that did not happen.
- Skim the scaffolded `AGENTS.md` with the owner and fill in the owner section; the placeholder guidance is meant to be replaced as the vault takes shape.

## Constraints

- Interview before running; never guess a taxonomy the owner has to live with.
- Never scaffold over existing content; the emptiness refusal is a safety rail, not an obstacle.
- The scaffolded files are the owner's (scaffold tier): plugin upgrades never touch them.
- `SETUP.md` in the new vault is the canonical new-machine checklist from then on — point the owner there.
