---
name: gitlab-promotion-flow
description: >
  Integration and promotion policy for Clearway GitLab data repos (Dagster,
  dbt, ingestion). Use when starting work, choosing a branch or merge target,
  opening a merge request into dev, promoting dev to main, or releasing to
  production in one of these repos.
---

# GitLab promotion flow

The fixed integration model for Clearway **GitLab data-pipeline repos**
(Dagster pulls, dbt marts, ingestion pipelines). `dev` is the shared
integration branch; `main` is the release branch. Each merge is one concern.

**Scope.** GitLab pipeline repos only. This is _not_ the-workshop (GitHub-native
`dev → main`, deploy gated on `main`; its GitLab fork is a downstream mirror —
never push/merge it there). If the repo's own `AGENTS.md`/`CLAUDE.md` states a
different policy, that wins — resolve repository policy first (see
`using-workflow`).

## Choose a path

- **Direct** — a single self-contained concern. One branch, one MR into `dev`.
- **Grouped** — several related issues that should land in `dev` together as one
  reviewed unit. Stage them on an `integration/<slug>` branch first.

## Direct path

```
<type>/<slug>  ──MR──▶  dev  ──promote──▶  main
   (one concern)      (1 approval,        (CI-push, solo;
                       CI green,           main CI green
                       dev instance)       = prod release)
```

1. **Cut a branch off `dev`.** Name `<type>/<kebab-slug>` using Conventional
   Commit types (`feat/`, `fix/`, `docs/`, `refactor/`, `test/`, `chore/`,
   `ci/`, `perf/`, `style/`). One concern per branch. No vendor/agent prefixes.
2. **MR into `dev`** — **1 approval** (designated reviewer, currently Biodun;
   any member may approve), CI green. Use `gitlab-mr-create`; never invoke
   `glab mr create` directly.

## Grouped path

```
<type>/<slug> ─MR─┐
<type>/<slug> ─MR─┼─▶ integration/<slug> ─MR─▶ dev ─promote─▶ main
<type>/<slug> ─MR─┘   (CI green,               (one MR,
                       no approval)             1 approval, CI green)
```

1. **Cut `integration/<slug>` off `dev`.** It is a staging branch for one group
   of related issues; nothing merges to it that is not part of the group.
2. **Each issue is a `<type>/<slug>` branch cut off the integration branch**,
   one concern each, and opens its **own MR into `integration/<slug>`**. These
   MRs require **CI green but no approval** — the integration branch is not a
   protected review gate.
3. **One MR from `integration/<slug>` into `dev`** — **1 approval**, CI green.
   This is the single aggregate merge into `dev` and the only review gate for
   the group. Rebase the integration branch on `dev` first if `dev` has moved.

## Into `dev` and beyond (both paths)

3. **`dev` is integration/staging.** Merging to `dev` may deploy to a **dev
   instance** of the app/tool _where one exists_ — that is expected. It must
   **never** deploy to production.
4. **Promote `dev → main`** once dev CI is green — the owner's solo CI-push
   promote (Charles), no MR review. Never self-merge a branch straight to `main`.
5. **`main` CI passing = the production release.** Production deploys **only**
   through the `main` CI path. Never ship prod off `dev` or a feature branch.

## Guardrails

- One concern per branch and per MR, on every hop. Split unrelated work apart.
- **The only required approval gate is a merge into `dev` (1 approval)** —
  whether from a feature branch (direct path) or an integration branch (grouped
  path). Issue → integration MRs need CI green but no approval. `dev → main` is
  the owner's solo promote. Never require or add approvals on any other hop.
- Never bypass CI on any MR hop.
- Reach for the grouped path only for genuinely related issues; a lone concern
  goes direct — do not spin up an integration branch for one branch.
- Watch CI for the pushed SHA and confirm every job is green before calling a
  push or promote done — proactively, unprompted.
- Fix CI/SAST findings at the source; do not path-exclude or suppress to pass a
  gate.
