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
(Dagster pulls, dbt marts, ingestion pipelines). `dev` is the integration
branch; `main` is the release branch. One concern moves through the pipeline at
a time.

**Scope.** GitLab pipeline repos only. This is _not_ the-workshop (GitHub-native
`dev → main`, deploy gated on `main`; its GitLab fork is a downstream mirror —
never push/merge it there). If the repo's own `AGENTS.md`/`CLAUDE.md` states a
different policy, that wins — resolve repository policy first (see
`using-workflow`).

## The pipeline

```
<type>/<slug>  ──MR──▶  dev  ──promote──▶  main
   (one concern)      (1 approval,        (CI-push, solo;
                       CI green,           main CI green
                       dev instance)       = prod release)
```

1. **Cut a branch off `dev`.** Name `<type>/<kebab-slug>` using Conventional
   Commit types (`feat/`, `fix/`, `docs/`, `refactor/`, `test/`, `chore/`,
   `ci/`, `perf/`, `style/`). One concern per branch — never bundle unrelated
   changes. No vendor/agent prefixes.

2. **MR into `dev`.** Every dev MR needs **1 approval** from the designated dev
   reviewer (currently Biodun); any member may approve per the GitLab rule.
   CI must be green to merge. Create the MR with `gitlab-mr-create` — do not
   invoke `glab mr create` directly.

3. **`dev` is integration/staging.** Merging to `dev` may deploy to a **dev
   instance** of the app/tool _where one exists_ — that is expected. It must
   **never** deploy to production.

4. **Promote `dev → main`** once dev CI is green. This is the owner's solo
   CI-push promote (Charles); it does not go through MR review. Do not
   self-merge feature branches straight to `main`.

5. **`main` CI passing = the production release.** Production deploys
   **only** through the `main` CI path. Never ship prod off `dev` or off a
   feature branch.

## Guardrails

- One concern at a time from branch through promote. Split unrelated work into
  separate branches and MRs.
- Do not merge your own feature branch into `dev` without the required
  approval; do not bypass CI on either hop.
- Watch CI for the pushed SHA and confirm every job is green before calling a
  push or promote done — proactively, unprompted.
- Fix CI/SAST findings at the source; do not path-exclude or suppress to make a
  gate pass.
