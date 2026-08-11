# Phase 6 — Delivery, PR, and Install

## Pre-delivery privacy check

Before anything leaves the machine, re-read every file destined for the repo and
confirm it is role-generic: no owner name in content (preset naming is already
role-based), no employer specifics beyond the field, no personal texture from the
interview, nothing quoted from memory or preferences. Anything personal found here
moves to the owner's local seed. This check is the last line of the privacy
property — do not skip it because "the interview already separated things".

## PR path (machine has write access to this repo)

1. `git fetch origin`, branch `feat/advisor-<role>` off `origin/main` — never off
   current HEAD.
2. Add the preset; `make docs`; `make build`; smoke-test the new preset; `uv run
pytest`. The layering test and the persona's own tests.md suite must be green.
3. Conventional commit, stage explicitly (never `git add .`), no agent attribution.
4. Push, open the PR: what the persona is, who owns it, tests.md results table,
   pack list with researched-on dates. The maintainer reviews and merges; merge →
   dist rebuild → marketplace → the owner receives it as a plugin update.

## Patch-bundle fallback (no write access — e.g. the owner's own machine)

Detect before attempting: `gh auth status` + push permission on the repo. If
absent, do not half-push. Instead produce `advisor-<role>-bundle/` containing the
preset directory, a `git format-patch`-style diff against the repo's main, the
tests.md results, and a one-paragraph handoff note. The owner sends the bundle to
the maintainer, who applies it on a fresh branch and runs the same gate. The
builder must say plainly which path it took and why.

## Install walkthrough (with the owner, per harness)

- **Claude Code / desktop:** add the marketplace once, install the `advisor-<role>`
  plugin, verify the skill loads. Updates arrive as plugin updates.
- **Codex / Cortex Code:** the built preset already carries `.codex-plugin/` and
  `.cortex-plugin/` manifests; install per that platform's plugin flow. Codex is
  smoke-tested support — say so honestly if asked.
- Then, on the owner's machine: create `local/` from the personal seed file
  (tuning.md starter + private seed), delete the seed from anywhere shared, and
  run the **first-conversation ritual**: one real scenario, one deliberate
  correction, wrap-up retune, confirm the tuning diff applied and memory wrote.
  The persona is not "delivered" until that ritual has happened.
- Walk the owner through `README.md` (the owner guide) before leaving them with
  it — at minimum on/off, what updates touch vs never touch, and where memory
  lives. The guide exists so this walkthrough survives the conversation.

## After delivery

- Log the persona (owner, preset name, version, date) in the PR description — the
  repo's history is the registry.
- Refresh diffs and promotions ride the same two paths above.
- A persona update that changes the base layer must re-run tests.md before its PR.
