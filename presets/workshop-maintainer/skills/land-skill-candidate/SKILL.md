---
name: land-skill-candidate
description: >
  Take an already-identified skill candidate — a named gap or improvement
  surfaced against a skill this repo owns, often from a /wrap-up session or
  similar review elsewhere — and ship it into The Workshop: locate the
  canonical source, apply the smallest fix, run the full gate sequence, and
  land it via branch to PR to dev on GitHub. Use when a user hands you a
  candidate (name, gap, evidence) and wants it built, not just drafted as a
  stub in reference/skills/drafts/.
---

# Land Skill Candidate

Companion to `workshop-skill-creator`: that skill designs and implements a
change; this one intakes an already-scoped candidate and owns getting it all
the way to a green PR against `dev`. It does not invent candidates — the
candidate must already exist (surfaced by `/wrap-up`, `improve-skill`, a
review, or the user directly).

## Repository Guard

Run only in The Workshop repository. Verify `core/skills/`, `presets/`,
`scripts/build_preset.py`, and `scripts/build_docs.py` exist. Otherwise stop
and explain this is not a generic skill-authoring workflow.

## 1. Intake the Candidate

Require, and ask for whatever is missing: the target skill (existing slug to
revise, or "new" if none exists yet), the gap or improvement itself, and the
evidence or session that surfaced it (so the commit and PR can cite a real
source, not a vague "improves X"). A candidate with no target skill and no
evidence is not ready to land — route it back to the user or to `grill-me`.

If the candidate is a brand-new skill rather than a revision, hand off to
`workshop-skill-creator`'s Gather and Blueprint steps first; return here only
for Implement and Land once that blueprint is approved.

## 2. Locate and Scope

Find the canonical source: `core/skills/<slug>/` for universal capabilities,
`presets/<preset>/skills/<slug>/` for package-specific ones. Never edit
`dist/` or an installed plugin cache — those are generated consumers. Scope
the smallest change that closes the gap; prefer folding a sentence into
existing prose over adding a new section, especially when the file is near
the 100-line guideline.

## 3. Sync the Integration Branch

`git fetch origin`, then check `git diff origin/dev origin/main --stat`.
Empty output means `dev` is only pointer-stale (safe to branch off `main` and
PR into `dev` — the diff will be clean). Non-empty output means real
divergence: stop and flag it rather than guessing which branch is
authoritative. Branch off the correct base as `<type>/<slug>-<slug-for-fix>`
(Conventional Commit type prefix).

## 4. Implement

Apply `workshop-skill-creator`'s Implement Test-First discipline: smallest
production change, test-first when the skill ships scripts or tests. Bump
every preset whose shipped content changed — `scripts/check_version_bumps.py`
names them; do not guess.

## 5. Gate

Run, in order, repairing until every one passes:

1. `make docs`
2. `make build`
3. `uv run python -m scripts.smoke_test <preset>` for every affected preset
4. `make test`

Never commit on a red gate.

## 6. Land

Commit with a message stating why (the constraint or evidence from step 1),
push the branch, open a PR with base `dev` (never `main` directly, never
GitLab — GitHub is `origin`, GitLab is a downstream mirror). Watch CI
(`gh pr checks <n> --watch`) until it reports green; a pending or absent
check is never a pass. Merge only if the user has already authorized merging
this candidate; otherwise stop once CI is green and ask. Promoting `dev` to
`main` is a separate, later step — never fold it into this skill's own run.

## 7. Report

Report the canonical file(s) changed, any preset version bumps, exact gate
results, the PR URL and its CI status, and whether it merged or is awaiting
approval.

## Boundaries

- Do not invent or scope candidates yourself — that's the source workflow's
  job (`/wrap-up`, `improve-skill`, a review, or the user).
- Do not push directly to `dev` or `main`; always land through a PR.
- Do not touch the GitLab remote — it is a one-way mirror fed by `dev`.
- Do not promote `dev` to `main` as part of landing a candidate.
