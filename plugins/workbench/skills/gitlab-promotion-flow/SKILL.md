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

**Scope.** GitLab pipeline repos only. This does _not_ apply to repos whose
GitLab presence is a read-only downstream mirror of an integration flow that
lives elsewhere (e.g. the-workshop: GitHub-native `dev → main` — never
push/merge it on GitLab). If the repo's own `AGENTS.md`/`CLAUDE.md` states a
different policy, that wins — resolve repository policy first (see
`using-workflow`).

## Choose a path

- **Direct** — a single self-contained concern. One branch, one MR into `dev`.
- **Grouped** — several related issues that should land in `dev` together as one
  reviewed unit. Stage them on an `integration/<slug>` branch first.

## Direct path

```
<type>/<slug>  ──MR──▶  dev  ──promote MR──▶  main
   (one concern)      (no approval,        (1 approval,
                       CI green,            CI green; main CI
                       dev instance)        = prod release)
```

1. **Cut a branch off `dev`.** Name `<type>/<kebab-slug>` using Conventional
   Commit types (`feat/`, `fix/`, `docs/`, `refactor/`, `test/`, `chore/`,
   `ci/`, `perf/`, `style/`). One concern per branch. No vendor/agent prefixes.
2. **MR into `dev`** — CI green, **no approval required**. Use
   `gitlab-mr-create`; never invoke `glab mr create` directly.

## Grouped path

```
<type>/<slug> ─MR─┐
<type>/<slug> ─MR─┼─▶ integration/<slug> ─MR─▶ dev ─promote MR─▶ main
<type>/<slug> ─MR─┘   (CI green,               (CI green,
                       no approval)             no approval)
```

1. **Cut `integration/<slug>` off `dev`.** It is a staging branch for one group
   of related issues; nothing merges to it that is not part of the group.
2. **Each issue is a `<type>/<slug>` branch cut off the integration branch**,
   one concern each, and opens its **own MR into `integration/<slug>`**. These
   MRs require CI green but no approval.
3. **One MR from `integration/<slug>` into `dev`** — CI green, no approval.
   This is the single aggregate merge into `dev`. Rebase the integration
   branch on `dev` first if `dev` has moved.

## Into `dev` and beyond (both paths)

3. **`dev` is integration/staging.** Merging to `dev` may deploy to a **dev
   instance** of the app/tool _where one exists_ — that is expected. It must
   **never** deploy to production.
4. **Promote `dev → main` by MR** once dev CI is green — **1 approval** (any
   eligible member other than the author), CI green. This promotion MR is the
   **only review gate in the flow**. Direct push to `main` is disabled; never
   merge a feature branch straight to `main`.
5. **`main` CI passing = the production release.** Production deploys **only**
   through the `main` CI path. Never ship prod off `dev` or a feature branch.

## Guardrails

- One concern per branch and per MR, on every hop. Split unrelated work apart.
- **The only required approval gate is the `dev → main` promotion MR
  (1 approval).** Every other hop — feature or integration branch into `dev`,
  issue branches into an integration branch — needs CI green but no approval.
  Never require or add approvals on any other hop: the release hop carries the
  review, so `main` is never easier to reach than `dev`.
- Wiring a repo: the gate is an `any_approver` rule (`approvals_required: 1`)
  scoped to the `main` protected branch, created via a JSON body with
  `Content-Type: application/json` — glab `-f` form fields silently drop
  `protected_branch_ids` and the rule goes live globally. Push access on
  `main` (and normally `dev`) is **No one**; changes land only by MR merge.
- Never bypass CI on any MR hop.
- Reach for the grouped path only for genuinely related issues; a lone concern
  goes direct — do not spin up an integration branch for one branch.
- Watch CI for the pushed SHA and confirm every job is green before calling a
  push or promote done — proactively, unprompted.
- Fix CI/SAST findings at the source; do not path-exclude or suppress to pass a
  gate.
